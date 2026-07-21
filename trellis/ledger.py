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

import json
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

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

    def _sync_locked(self) -> None:
        """Bring the cache up to the file's current end. Must hold self._lock.
        Parses only the bytes appended since the last sync (each line once); a
        file smaller than what we've synced (a rewrite/truncate) triggers a full
        rebuild. A corrupt COMPLETE line raises without advancing the offset or
        mutating the cache, so the error is consistent across calls and never
        leaves a half-synced cache (matching the old whole-file-or-raise contract)."""
        try:
            size = os.path.getsize(self.path)
        except FileNotFoundError:
            self._cache = []
            self._synced_bytes = 0
            return
        if size < self._synced_bytes:
            # the file shrank or was rewritten — the offset is meaningless; rebuild.
            self._cache = []
            self._synced_bytes = 0
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

    # ----- write -----------------------------------------------------------

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
        # append only WRITES (an atomic OS append); it never touches the cache, so
        # it stays coherent under multi-instance writes — entries() syncs from the
        # file (the sole truth), parsing each new line exactly once. The OS append
        # is atomic per line, and the sync only parses COMPLETE lines, so a reader
        # can never see a torn write.
        with self.path.open("a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")
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
