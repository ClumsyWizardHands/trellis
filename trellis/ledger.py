"""ledger.py — bitemporal, append-only, supersession-not-deletion. (DECISIONS.md D2)

This is the proven pattern from the working atlas-ledger (~/.principles-claw/
memory/atlas-ledger.jsonl) — the one part of the June 2026 architecture spec
that landed and held. Kept, hardened, generalized:

  * Every entry carries BOTH event_time and write_time (clock.Stamp).
  * Every entry carries an author. (The audit found the old ledger had no
    author field; 42 warm files merged distinct humans under user_id=0.
    Attribution is a relational contract — Clare, 2026-03-10.)
  * Nothing is ever rewritten. Corrections append a supersession link.
  * Search builds a throwaway in-memory SQLite index per query, so the index
    can never drift from the file. The file IS the truth.
  * as_of(t) reads the ledger as it was known at time t (bitemporal audit).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .clock import Stamp, TimeGround


class LedgerIntegrityError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str                 # e.g. decision / pass / loop_run / memory / schedule / correction
    author: str               # REQUIRED. No anonymous memory.
    body: dict
    stamp: Stamp
    tags: tuple[str, ...] = ()
    supersedes: Optional[str] = None   # id of the entry this one corrects

    def to_json(self) -> str:
        d = {
            "id": self.id,
            "kind": self.kind,
            "author": self.author,
            "body": self.body,
            **self.stamp.to_dict(),
            "tags": list(self.tags),
        }
        if self.supersedes:
            d["supersedes"] = self.supersedes
        # An entry must ALWAYS serialize — a non-writable outcome is a silent
        # failure, the cardinal sin. Three fallbacks, catching BaseException at
        # each: (1) normal, default=str for exotic types; (2) body → repr, for
        # circular refs that raise before default= runs; (3) if even repr()
        # raises (an object whose __repr__ throws, the #42 round-3 vector), a
        # minimal record with the body dropped. Something valid ALWAYS gets
        # written.
        try:
            return json.dumps(d, ensure_ascii=False, default=str)
        except BaseException:
            pass
        try:
            safe = dict(d)
            safe["body"] = {"_unserializable": True, "repr": repr(self.body)[:4000]}
            return json.dumps(safe, ensure_ascii=False, default=str)
        except BaseException:
            minimal = {"id": self.id, "kind": self.kind, "author": str(self.author)[:200],
                       "body": {"_unwritable": True},
                       **self.stamp.to_dict(), "tags": []}
            if self.supersedes:
                minimal["supersedes"] = self.supersedes
            return json.dumps(minimal, ensure_ascii=False, default=str)

    @staticmethod
    def from_json(line: str) -> "Entry":
        d = json.loads(line)
        return Entry(
            id=d["id"],
            kind=d["kind"],
            author=d["author"],
            body=d["body"],
            stamp=Stamp.from_dict(d),
            tags=tuple(d.get("tags", ())),
            supersedes=d.get("supersedes"),
        )


class Ledger:
    """Append-only JSONL ledger. One file, human-readable, greppable, syncable
    over a shared drive or git — no server to run, nothing to stand up."""

    def __init__(self, path: Path | str, ground: Optional[TimeGround] = None):
        self.path = Path(path)
        self.ground = ground or TimeGround()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        # --- rebuildable read cache (D27) ---------------------------------
        # The FILE is the sole source of truth; this is a performance layer that
        # only ever PARSES EACH LINE ONCE. entries() used to re-parse the whole
        # JSONL on every call, so any read-per-write pattern (DecisionLog.record →
        # active() → entries()) was O(n) per op → O(n^2) as the record compounds —
        # the opposite of the "compounds over time" thesis. The cache is keyed on a
        # byte offset: a sync reads only the bytes appended since last time, parses
        # the new whole lines, and appends them. It is rebuildable from the file at
        # any moment (a shrink/rewrite triggers a full rebuild), so it can never be
        # a second source of truth. A reentrant lock makes it safe for the
        # single-instance multi-thread case the concurrency stress exercises.
        self._lock = threading.RLock()
        self._cache: list[Entry] = []
        self._synced_bytes: int = 0
        self._filesig = None   # ((inode, device), mtime_ns, ctime_ns) at last sync —
                               # detects an out-of-band replacement / same-size rewrite.
                               # ctime_ns is what catches a rewrite that RESTORES mtime
                               # (os.utime), which no caller can do to ctime (Codex#17).
        self._prefix_sha = hashlib.sha256()  # running hash of the synced (immutable)
                               # prefix, so a rebuild can tell a genuine out-of-band
                               # PREFIX rewrite (loud) from benign growth (quiet).
        # cross-process write serialization (Codex#5 / FableG12): the exclusive
        # section holds an fcntl lock on this fd; _lock_depth makes it reentrant
        # within a thread so a write_transaction that also calls append does not
        # try to re-take the file lock and self-deadlock.
        self._lock_depth = 0
        self._write_fh = None

    def _sync_locked(self) -> None:
        """Bring the cache up to the file's current end. Must hold self._lock.
        Parses only the bytes appended since the last sync (each line once).

        The cache's one assumption is that bytes below the synced offset are
        IMMUTABLE — true for the append-only contract this ledger is (append /
        correct / retire only ever GROW the file by whole lines). A full rebuild
        is forced whenever that could be violated by an out-of-band edit, detected
        by a cheap stat signature (the README advertises syncing over git / a
        shared drive, so a live instance's file can be replaced under it):
          * the file was REPLACED — a new (inode, device), as git / rsync / an
            atomic write-and-rename produce → rebuild;
          * the file SHRANK (size < offset) → rebuild;
          * a SAME-SIZE in-place rewrite (size unchanged, mtime advanced) → rebuild.
        The one residual it cannot cheaply catch is a same-inode GROW-in-place
        rewrite that changes bytes below the offset — which no append-only or
        sync/replace workflow performs. A corrupt COMPLETE line raises without
        advancing the offset or mutating the cache, so the error is consistent
        across calls and never leaves a half-synced cache."""
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            self._cache = []
            self._synced_bytes = 0
            self._filesig = None
            self._prefix_sha = hashlib.sha256()
            return
        size = st.st_size
        ino_dev = (st.st_ino, st.st_dev)
        replaced = self._filesig is not None and self._filesig[0] != ino_dev
        # A same-size in-place rewrite is caught by EITHER a moved mtime or a moved
        # ctime. ctime is the load-bearing one: a rewrite that restores mtime with
        # os.utime (the preserved-mtime attack, Codex#17) still moves ctime, which
        # no caller can set — so the stale cache can no longer masquerade as fresh.
        same_size_rewrite = (self._filesig is not None and size == self._synced_bytes
                             and size > 0
                             and (st.st_mtime_ns != self._filesig[1]
                                  or st.st_ctime_ns != self._filesig[2]))
        if replaced or size < self._synced_bytes or same_size_rewrite:
            # the offset is meaningless — the file is not the one we synced. Rebuild.
            # The file is still the source of truth, so we ACCEPT it — but a rebuild
            # whose on-disk prefix differs from the immutable bytes we had synced is
            # an out-of-band edit to history: emit LOUDLY (FableG12c). Silent
            # acceptance on a machine hosting other agents is exactly the tamper the
            # append-only contract is supposed to make visible.
            if self._prefix_diverged(size):
                self._emit(
                    f"[ledger] out-of-band rewrite of {self.path}: the on-disk "
                    "prefix changed under a live instance — cache rebuilt from the "
                    "file (the file is truth), but history below the synced offset "
                    "was altered out of band. Investigate.")
            self._cache = []
            self._synced_bytes = 0
            self._prefix_sha = hashlib.sha256()
        self._filesig = (ino_dev, st.st_mtime_ns, st.st_ctime_ns)
        if size <= self._synced_bytes:
            return
        with self.path.open("rb") as f:
            f.seek(self._synced_bytes)
            chunk = f.read(size - self._synced_bytes)
        last_nl = chunk.rfind(b"\n")
        if last_nl == -1:
            return   # no complete line yet (a writer may be mid-append)
        whole = chunk[: last_nl + 1]
        parsed: list[Entry] = []
        for raw in whole.split(b"\n"):
            s = raw.strip()
            if not s:
                continue
            try:
                parsed.append(Entry.from_json(s.decode("utf-8")))
            except Exception as e:  # a corrupt line is reported, never skipped silently
                raise LedgerIntegrityError(f"{self.path} unreadable near byte "
                                           f"{self._synced_bytes}: {e}") from e
        # only commit once the whole chunk parsed cleanly
        self._cache.extend(parsed)
        self._synced_bytes += len(whole)
        self._prefix_sha.update(whole)   # extend the immutable-prefix fingerprint

    def _prefix_diverged(self, new_size: int) -> bool:
        """Did the on-disk prefix change from the immutable bytes we had synced?
        Called only on the rare rebuild path. A shrink below the synced offset is a
        change by definition; otherwise hash the new file's leading `synced` bytes
        and compare to the running fingerprint. Returns False when nothing was
        synced yet (no prefix to violate)."""
        old = self._synced_bytes
        if old == 0:
            return False
        if new_size < old:
            return True
        try:
            with self.path.open("rb") as f:
                head = f.read(old)
        except OSError:
            return True
        return hashlib.sha256(head).hexdigest() != self._prefix_sha.hexdigest()

    def _emit(self, message: str) -> None:
        """A loud, un-swallowable signal to the operator. stderr, not the ledger,
        so it can never itself wedge or be mistaken for content."""
        print(message, file=sys.stderr, flush=True)

    # ----- write -----------------------------------------------------------

    @contextmanager
    def _exclusive(self, sync: bool = True) -> Iterator:
        """The one write section, serialized across threads (self._lock) AND
        processes (fcntl on the file) so a check-then-append is atomic end to end
        (Codex#5). Reentrant within a thread via _lock_depth: a write_transaction
        that also calls append reuses the held file lock instead of re-taking it.
        On first entry it syncs, so the enclosed check sees every other writer's
        committed lines (`sync=False` for repair, which must read a wedged file
        without the sync raising first)."""
        with self._lock:
            first = self._lock_depth == 0
            if first:
                fh = self.path.open("a", encoding="utf-8")
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                self._write_fh = fh
            self._lock_depth += 1
            try:
                if first and sync:
                    self._sync_locked()
                yield self._write_fh
            finally:
                self._lock_depth -= 1
                if self._lock_depth == 0:
                    fh = self._write_fh
                    self._write_fh = None
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                    finally:
                        fh.close()

    def write_transaction(self):
        """Public exclusive write section (thread- and process-serialized via the
        file lock). A caller that must make a check-then-append atomic across
        processes — e.g. DecisionLog's question-key anti-fork — wraps BOTH the
        check and the append in this, so no second writer can slip between them
        (Codex#5). Reentrant with append's own locking."""
        return self._exclusive()

    def _heal_before_append_locked(self, fh) -> None:
        """Guarantee the file ends on a clean line boundary before we append. The
        ledger NEVER writes a line without a trailing newline, so a file that does
        NOT end in one has a torn (crashed mid-write) tail — bytes that were never
        a committed entry. Left in place, the next append would fuse into them,
        producing a corrupt line that wedges every read AND swallows the new entry
        (FableG12b). Quarantine that partial tail to a sidecar, truncate back to the
        last complete line, and re-terminate — loudly, never silently. Must hold the
        exclusive lock."""
        size = os.stat(self.path).st_size
        if size == 0:
            return
        with self.path.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) == b"\n":
                return
            f.seek(0)
            data = f.read()
        cut = data.rfind(b"\n") + 1     # start of the unterminated tail (0 if none)
        tail = data[cut:]
        with self.path.open("rb+") as f:
            f.truncate(cut)
            f.flush()
            os.fsync(f.fileno())
        qpath = self.path.with_name(self.path.name + ".quarantine")
        with qpath.open("ab") as q:
            q.write(tail + b"\n")
        self._emit(
            f"[ledger] torn tail ({len(tail)} bytes, never a committed entry) "
            f"quarantined to {qpath} and the file re-terminated before append.")

    def append(
        self,
        kind: str,
        author: str,
        body: dict,
        event_time: Optional[datetime] = None,
        tags: Iterable[str] = (),
        supersedes: Optional[str] = None,
    ) -> Entry:
        if not author or not author.strip():
            raise LedgerIntegrityError("author is required — no anonymous memory")
        # The whole check-then-write runs inside the exclusive section, serialized
        # across threads AND processes (Codex#5): the supersession check reads the
        # freshly-synced file and no second writer can append between the check and
        # our write, so concurrent corrections can never fork one lineage into two
        # live heads.
        with self._exclusive() as f:
            if supersedes is not None:
                if self.get(supersedes) is None:
                    raise LedgerIntegrityError(f"supersedes unknown entry: {supersedes}")
                existing = self._superseder_of(supersedes)
                if existing is not None:
                    # corrections form a CHAIN, not a fork: two live heads for one
                    # lineage is a contradictory belief state (found by #14).
                    raise LedgerIntegrityError(
                        f"{supersedes} is already superseded by {existing} — correct "
                        "the current head, not a stale entry")
            entry = Entry(
                id=uuid.uuid4().hex[:12],
                kind=kind,
                author=author.strip(),
                body=body,
                stamp=self.ground.stamp(event_time),
                tags=tuple(tags),
                supersedes=supersedes,
            )
            # A torn tail from a crashed prior write is quarantined and the file
            # re-terminated FIRST, so this entry is always its own clean line and is
            # never fused into partial bytes (FableG12b). The append itself never
            # touches the cache — entries() syncs from the file (the sole truth),
            # parsing each new line exactly once.
            self._heal_before_append_locked(f)
            f.write(entry.to_json() + "\n")
            # Durability: fsync so a committed line survives power loss — otherwise a
            # crash after a remote-accepted send could lose the firing intent and
            # resurrect the action as APPROVED for a clean double-send (FableG12a).
            f.flush()
            os.fsync(f.fileno())
        return entry

    def correct(self, old_id: str, author: str, body: dict,
                event_time: Optional[datetime] = None) -> Entry:
        """The only way to 'change' the past: append a superseding entry.
        History keeps the mistake AND the correction — that lineage is the
        difference between a corrected memory and a gaslit one."""
        old = self.get(old_id)
        if old is None:
            raise LedgerIntegrityError(f"cannot correct unknown entry: {old_id}")
        return self.append(
            kind=old.kind, author=author, body=body,
            event_time=event_time or old.stamp.event_time,
            tags=old.tags, supersedes=old_id,
        )

    def repair_tail(self, author: str) -> Optional[str]:
        """The documented repair ritual for a torn/corrupt FINAL line (FableG12b).

        A complete-but-unparseable line wedges every read with LedgerIntegrityError
        — kept ON PURPOSE as loud tamper-evidence, not silently skipped. When a
        human judges that the final line is a torn write (not history worth
        keeping), this quarantines JUST that line to a sidecar and re-terminates the
        file, so reads recover. It REFUSES to touch a corrupt line anywhere but the
        very end: silently dropping interior history is exactly the gaslight this
        ledger exists to prevent, so an interior corruption still raises and needs a
        human to look at the file directly. Attributable (an author is required) and
        loud (emits an event). Returns the quarantined line, or None if nothing was
        wrong.

        Runs inside the exclusive section WITHOUT the entry-sync (a wedged file
        would make the sync raise before we could repair it)."""
        if not author or not author.strip():
            raise LedgerIntegrityError(
                "repair_tail requires an author — surgery on the source of truth "
                "is attributable, never anonymous")
        with self._exclusive(sync=False):
            with self.path.open("rb") as f:
                data = f.read()
            end = data.rfind(b"\n")
            if end == -1:
                return None            # nothing complete on disk yet
            lines = [ln for ln in data[: end + 1].split(b"\n") if ln.strip()]
            if not lines:
                return None
            bad_idx = None
            for i, ln in enumerate(lines):
                try:
                    Entry.from_json(ln.decode("utf-8"))
                except Exception:
                    bad_idx = i
                    break
            if bad_idx is None:
                return None            # every complete line parses; nothing to repair
            if bad_idx != len(lines) - 1:
                raise LedgerIntegrityError(
                    f"corrupt line at index {bad_idx} of {len(lines)} is NOT the "
                    "final line — refusing to quarantine interior history (that "
                    "would be silent deletion). A human must inspect the file.")
            bad = lines[-1]
            good = b"\n".join(lines[:-1])
            if good:
                good += b"\n"
            with self.path.open("rb+") as f:
                f.truncate(0)
                f.write(good)
                f.flush()
                os.fsync(f.fileno())
            qpath = self.path.with_name(self.path.name + ".quarantine")
            with qpath.open("ab") as q:
                q.write(bad + b"\n")
            # we rewrote the file deliberately — force a clean rebuild on next read
            # WITHOUT the out-of-band-rewrite alarm (this change is authorized).
            self._cache = []
            self._synced_bytes = 0
            self._filesig = None
            self._prefix_sha = hashlib.sha256()
            self._emit(
                f"[ledger] repair_tail by {author}: quarantined a corrupt final "
                f"line to {qpath}; reads restored.")
            return bad.decode("utf-8", "replace")

    RETIREMENT_KIND = "retirement"

    def retire(self, entry_id: str, author: str,
               valid_to: Optional[datetime] = None, reason: str = "",
               event_time: Optional[datetime] = None) -> Entry:
        """Forget without deleting or superseding: append a retirement record
        that closes an entry's validity at `valid_to` (default now). The Entry
        itself is NEVER mutated — the record is append-only. A retired-but-
        unsuperseded entry drops out of `active()` (and therefore every truth-
        serving read), but stays fully in `lineage()` / `as_of()` for audit.
        This is `valid_to` as an appended fact (plan §2d)."""
        target = self.get(entry_id)
        if target is None:
            raise LedgerIntegrityError(f"cannot retire unknown entry: {entry_id}")
        vt = valid_to or self.ground.now()
        return self.append(
            kind=self.RETIREMENT_KIND, author=author,
            body={"retires": entry_id, "valid_to": vt.isoformat(), "reason": reason},
            event_time=event_time, tags=("retirement",),
        )

    @staticmethod
    def _valid_to_map(entries: list[Entry]) -> dict[str, datetime]:
        """entry_id → earliest valid_to across retirement records targeting it
        (earliest wins: the first close of validity is when it stopped being
        current)."""
        m: dict[str, datetime] = {}
        for e in entries:
            if e.kind != Ledger.RETIREMENT_KIND:
                continue
            tid = e.body.get("retires")
            raw = e.body.get("valid_to")
            if not tid or not raw:
                continue
            dt = datetime.fromisoformat(raw)
            if tid not in m or dt < m[tid]:
                m[tid] = dt
        return m

    # ----- read ------------------------------------------------------------

    def entries(self) -> list[Entry]:
        """Every entry, oldest first. Backed by the rebuildable cache (D27): the
        file is re-parsed incrementally (only newly-appended lines), not in full,
        so repeated reads and read-per-write patterns stop being O(n)/O(n^2).
        Returns a fresh list, so a caller iterating it is unaffected by a
        concurrent append. A corrupt line still raises LedgerIntegrityError."""
        with self._lock:
            self._sync_locked()
            return list(self._cache)

    def get(self, entry_id: str) -> Optional[Entry]:
        for e in self.entries():
            if e.id == entry_id:
                return e
        return None

    def _superseder_of(self, entry_id: str) -> Optional[str]:
        for e in self.entries():
            if e.supersedes == entry_id:
                return e.id
        return None

    def active(self, kind: Optional[str] = None) -> list[Entry]:
        """THE single current-truth resolver (plan §2d, flaw #4): 'what is true
        NOW'. An entry is active iff it is (a) not superseded AND (b) still in
        validity at now. This unifies the two rival predicates that used to exist
        (`current()` = supersession only vs a validity notion) so no read path
        can serve a retired-but-unsuperseded sapling. Retirement records are
        machinery, never content, so they are excluded.

        NOW-only ON PURPOSE. An earlier version took an `at` parameter, but that
        mixed now-global existence with past-validity and could return TWO live
        heads for one question at a past instant (the Phase-2 adversary's
        confirmed MED). Historical reconstruction has ONE coherent home:
        `as_of(t)` (bitemporal by write_time). active() answers only 'now'."""
        now = self.ground.now()
        all_entries = self.entries()
        superseded = {e.supersedes for e in all_entries if e.supersedes}
        vt = self._valid_to_map(all_entries)
        out = []
        for e in all_entries:
            if e.kind == self.RETIREMENT_KIND:
                continue
            if e.id in superseded:
                continue
            r = vt.get(e.id)
            if r is not None and r <= now:
                continue
            if kind is not None and e.kind != kind:
                continue
            out.append(e)
        return out

    def current(self, kind: Optional[str] = None) -> list[Entry]:
        """'What do we believe now' — kept as the familiar name, now routed
        through the one validity-aware resolver so it and `active()` can never
        disagree (they are the same predicate)."""
        return self.active(kind)

    def lineage(self, entry_id: str) -> list[Entry]:
        """Full correction chain containing entry_id, oldest first."""
        all_entries = {e.id: e for e in self.entries()}
        if entry_id not in all_entries:
            return []
        # walk back
        cur = all_entries[entry_id]
        chain = [cur]
        while cur.supersedes and cur.supersedes in all_entries:
            cur = all_entries[cur.supersedes]
            chain.append(cur)
        chain.reverse()
        # walk forward
        head = chain[-1]
        while True:
            nxt = next((e for e in all_entries.values() if e.supersedes == head.id), None)
            if nxt is None:
                break
            chain.append(nxt)
            head = nxt
        return chain

    def as_of(self, t: datetime) -> list[Entry]:
        """The ledger as it was KNOWN at time t (by write_time) — what would an
        agent have believed then? This is the anti-gaslighting query."""
        known = [e for e in self.entries() if e.stamp.write_time <= t]
        superseded = {e.supersedes for e in known if e.supersedes}
        vt = self._valid_to_map(known)   # only retirements KNOWN by t count
        out = []
        for e in known:
            if e.kind == self.RETIREMENT_KIND:
                continue
            if e.id in superseded:
                continue
            r = vt.get(e.id)
            if r is not None and r <= t:
                continue
            out.append(e)
        return out

    # ----- search (index never drifts: rebuilt per query) -------------------

    def search(self, query: str, kind: Optional[str] = None, limit: int = 20) -> list[Entry]:
        entries = self.current(kind)
        if not entries:
            return []
        try:
            return self._fts(entries, query, limit)
        except sqlite3.OperationalError:
            q = query.lower()
            return [e for e in entries if q in e.to_json().lower()][:limit]

    @staticmethod
    def _fts(entries: list[Entry], query: str, limit: int) -> list[Entry]:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE ix USING fts5(id, text)")
        con.executemany(
            "INSERT INTO ix VALUES (?, ?)",
            [(e.id, f"{e.kind} {' '.join(e.tags)} {json.dumps(e.body, ensure_ascii=False, default=str)}")
             for e in entries],
        )
        safe = " ".join(re.findall(r"\w+", query)) or query
        rows = con.execute(
            "SELECT id FROM ix WHERE ix MATCH ? ORDER BY bm25(ix) LIMIT ?", (safe, limit)
        ).fetchall()
        con.close()
        by_id = {e.id: e for e in entries}
        return [by_id[r[0]] for r in rows if r[0] in by_id]
