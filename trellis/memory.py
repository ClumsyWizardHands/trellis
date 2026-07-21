"""memory.py — memory beside the agent; the agent dies. (DECISIONS.md D5)

"The goal is not agents that have memory. The memories are the things
themselves… The agent dies." — Brett, 2026-06-11

Mechanisms, all file-based (the field agrees: Letta abandoned database memory
blocks for files+git in March 2026; Anthropic's memory tool is file ops):

  * Workspace — plain directories. Everything greppable, syncable, versionable.
  * The synthesis test as a REQUIRED ARGUMENT: to persist anything you must
    answer "why couldn't a future agent re-derive this from existing sources?"
    An empty or boilerplate answer refuses the write. This is what keeps the
    store sparse ("sparse maps, forced traversal — the traversal IS the
    learning" — Atlas memory architecture, 2026-06-30).
  * flush-then-compact: compaction may not run until important context has
    been flushed to durable files (the OpenClaw lesson: compaction memory loss
    was the #1 user-reported failure; the flush is the countermeasure).
  * Session epitaph: when a session ends, it writes what survives it. The
    agent dies; the epitaph is what the next agent reads. No continuity
    theater — the file says which session wrote it and when.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .clock import TimeGround
from .ledger import Ledger


class WorkspaceEscapeError(ValueError):
    """A read/write/map path resolved OUTSIDE the workspace root — a `../`
    traversal or a symlink escape. The workspace is the trust boundary (Codex
    High 8)."""


class SynthesisTestError(Exception):
    """The write didn't justify its own persistence."""


class CompactionOrderError(Exception):
    """Compaction attempted before the memory flush."""


class TitleError(Exception):
    """A persisted memory needs a 00-grade, keyword-findable title. Vague or
    empty titles make the memory un-navigable — search-by-title is the whole
    index (plan §2a)."""


_VAGUE_TITLES = {
    "notes", "note", "misc", "todo", "memory", "stuff", "things", "untitled",
    "temp", "tmp", "doc", "document", "draft", "wip", "new", "file", "data",
    "info", "stuff", "misc notes", "no title", "none", "n/a", "na",
}


def _fails_title(title: str) -> Optional[str]:
    """A HEURISTIC title lint (sibling of the synthesis test): catch the lazy
    'notes.md' so the memory stays findable. Not a proof — a human reviews the
    ledger. Applied when a title is given explicitly; a derived title (legacy
    headingless content) is tolerated so old writes keep working."""
    from .identity import is_effectively_blank
    t = (title or "").strip()
    if is_effectively_blank(t):
        return "a persisted memory needs a non-empty title to be findable"
    stripped = re.sub(r"^#+\s*", "", t).strip()   # allow a markdown heading
    key = stripped.lower().strip(" .-_")
    if key in _VAGUE_TITLES:
        return (f"title {title!r} is too vague to navigate to — name the actual "
                "subject (search-by-title is the memory index)")
    words = [w for w in re.findall(r"\w+", stripped) if len(w) >= 2]
    if not words:
        return "title has no keyword-findable words — name the subject plainly"
    return None


_BOILERPLATE = {
    "important", "context", "for later", "might need", "just in case",
    "n/a", "na", "none", "misc", "notes", "memory", "todo",
}
# word-level boilerplate: the multi-word phrases above must be split, or a
# single-token test never matches "for later" and pure-filler prose like
# "todo notes misc for later just in case" slips through (#50 round 3).
_BOILERPLATE_WORDS = {w for phrase in _BOILERPLATE for w in phrase.split()}
# Common filler — a justification made ONLY of these has said nothing. Includes
# discourse adverbs/connectives (round 4 #50: "basically actually obviously
# certainly essentially generally speaking" is vacuous, not substantive).
_FILLER = {
    "this", "is", "a", "an", "the", "that", "we", "want", "to", "keep", "it",
    "here", "for", "of", "and", "or", "so", "thing", "stuff", "need", "have",
    "be", "will", "can", "should", "there", "some", "just", "really", "very",
    "basically", "actually", "obviously", "certainly", "essentially",
    "generally", "speaking", "well", "anyway", "however", "therefore",
    "moreover", "furthermore", "perhaps", "indeed", "quite", "somewhat",
    "literally", "honestly", "simply", "clearly", "definitely", "probably",
    "maybe", "kind", "sort", "like", "stuff", "things", "important", "note",
}


def _fails_synthesis(justification: str) -> Optional[str]:
    """A HEURISTIC BACKSTOP, not a proof. No text test can verify that content
    is genuinely irreducible — a determined writer can pad a meaningful-looking
    sentence past any filter. The real gate is the human who reads the ledger's
    memory_write entries. This catches the lazy 90%, not the adversarial 10%
    (found by the adversary, #50 — honestly labelled rather than oversold)."""
    j = justification.strip().lower()
    words = re.findall(r"\w+", j)
    if len(j.split()) < 6:
        return ("synthesis test requires a real answer (>=6 words) to: why "
                "couldn't a future agent re-derive this from existing sources "
                "(ledger, transcripts, logs, git)?")
    if j in _BOILERPLATE or (words and all(w in _BOILERPLATE_WORDS for w in words)):
        return "synthesis test answered with boilerplate — refuse and re-derive instead"
    # lexical substance: at least 4 distinct non-filler words of length >= 3
    substantive = {w for w in words if len(w) >= 3 and w not in _FILLER}
    if len(substantive) < 4:
        return ("synthesis justification is filler — name the specific thing "
                "that exists nowhere else and why it can't be re-derived")
    return None


@dataclass
class WriteReceipt:
    path: str
    ledger_entry: str
    justification: str


class Workspace:
    """A memory directory an agent works beside. The agent reads its way in;
    nothing is 'in' the agent."""

    def __init__(self, root: Path | str, ledger: Ledger,
                 ground: Optional[TimeGround] = None):
        # resolve() at init: a relative root breaks containment checks later
        # (found by the stress suite, kept as a test — see stress_test.py)
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger
        self.ground = ground or ledger.ground
        self._flush_receipts: set[str] = set()  # session ids that flushed

    # ----- the write gate ---------------------------------------------------

    MEMORY_KIND = "memory_write"

    def _derive_title(self, content: str) -> str:
        for line in content.splitlines():
            if line.strip():
                return line.strip()[:80]
        return "(empty)"

    def _active_write_for(self, rel: str) -> Optional["object"]:
        """The active (validity + supersession aware) memory_write entry for a
        path, or None — the fold-not-clobber lookup."""
        for e in self.ledger.active(self.MEMORY_KIND):
            if e.body.get("path") == rel:
                return e
        return None

    def write(self, rel_path: str, content: str, author: str,
              synthesis_justification: str,
              title: Optional[str] = None) -> WriteReceipt:
        problem = _fails_synthesis(synthesis_justification)
        if problem:
            raise SynthesisTestError(problem)
        # 2a — every persisted memory carries a 00-grade title. An explicit
        # title is linted; a derived one (legacy headingless content) is
        # tolerated so old callers keep working.
        if title is not None:
            tproblem = _fails_title(title)
            if tproblem:
                raise TitleError(tproblem)
            the_title = title.strip()
        else:
            the_title = self._derive_title(content)
        path = self._contained(rel_path)   # the workspace is the trust boundary (High 8)
        rel = str(path.relative_to(self.root.resolve()))
        path.parent.mkdir(parents=True, exist_ok=True)

        # 2e — FOLD, don't clobber. If this path already holds an active write,
        # archive the old body to .history and supersede the prior ledger entry,
        # so the overwritten content is never lost (exploration §3.5 bug).
        prior = self._active_write_for(rel)
        history_ref = None
        if prior is not None and path.exists():
            old = path.read_text(encoding="utf-8")
            stamp = prior.stamp.write_time.isoformat().replace(":", "-")
            hist = self.root / ".history" / (rel + f".{stamp}")
            hist.parent.mkdir(parents=True, exist_ok=True)
            hist.write_text(old, encoding="utf-8")
            history_ref = str(hist.relative_to(self.root))

        path.write_text(content, encoding="utf-8")
        entry = self.ledger.append(
            kind=self.MEMORY_KIND, author=author,
            body={"path": rel,
                  "title": the_title,
                  "bytes": len(content.encode("utf-8")),
                  # a content HASH, not just a byte-count — so vault/ledger drift
                  # (a human editing a note in Obsidian) is DETECTABLE, and the
                  # vault is honestly reconcilable with the ledger (plan v2 §3.2,
                  # the stress-test's "reconstructable from the ledger" flaw).
                  "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
                  "synthesis_justification": synthesis_justification,
                  "prior_history": history_ref},
            tags=("memory",),
            supersedes=prior.id if prior is not None else None,
        )
        return WriteReceipt(str(path), entry.id, synthesis_justification)

    def _contained(self, rel_path: str) -> Path:
        """Resolve rel_path and REFUSE anything that escapes the workspace root —
        a `../` traversal or a symlink pointing outside (Codex High 8: write()
        checked containment but read()/map() did not, so `read('../secret.md')`
        escaped). resolve() follows symlinks, so a symlinked path that lands
        outside the root is caught too. The workspace is the trust boundary."""
        root = self.root.resolve()
        path = (self.root / rel_path).resolve()
        if path != root and root not in path.parents:
            raise WorkspaceEscapeError(
                f"path escapes the workspace: {rel_path!r} → {path}")
        return path

    def read(self, rel_path: str) -> str:
        return self._contained(rel_path).read_text(encoding="utf-8")

    # ----- 2a: search by title (navigate; open bodies on demand) -------------

    def titles(self) -> list[tuple[str, str]]:
        """(title, path) for every ACTIVE memory — the navigable index. Reads
        the ledger (validity-aware), not the disk, so retired/superseded writes
        never appear."""
        return [(e.body.get("title", ""), e.body.get("path", ""))
                for e in self.ledger.active(self.MEMORY_KIND)]

    def search_titles(self, keywords: str) -> list[tuple[str, str]]:
        """Search TITLES only (the map), not bodies (the territory). Returns
        (title, path) hits ranked by how many query words the title matches;
        the caller opens a body with read(path) on a match. This is 'memory is
        navigation': you find the door by its label, then walk through it."""
        want = [w for w in re.findall(r"\w+", keywords.lower()) if w]
        if not want:
            return []
        scored = []
        for title, path in self.titles():
            hay = title.lower()
            hits = sum(1 for w in want if w in hay)
            if hits:
                scored.append((hits, title, path))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [(t, p) for _, t, p in scored]

    def map(self) -> list[str]:
        """Titles-only map for prompt injection — the navigational cold layer.
        The map, never the territory. A symlinked .md pointing OUTSIDE the
        workspace is skipped, never read into the prompt (Codex High 8)."""
        out = []
        root = self.root.resolve()
        for p in sorted(self.root.rglob("*.md")):
            resolved = p.resolve()
            if resolved != root and root not in resolved.parents:
                continue   # a symlink escaping the workspace — do not read it in
            rel = p.relative_to(self.root)
            first = ""
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        first = line.strip()[:80]
                        break
            except Exception:
                first = "(unreadable)"
            out.append(f"{rel} — {first}")
        return out

    # ----- flush-then-compact ------------------------------------------------

    def flush(self, session_id: str, author: str,
              survivors: list[tuple[str, str, str]]) -> list[WriteReceipt]:
        """Before compaction: persist what must survive. `survivors` is a list
        of (rel_path, content, synthesis_justification). An empty list is a
        legitimate flush — 'nothing here passes the synthesis test' — but it
        must be SAID, which is what the receipt records."""
        receipts = []
        for rel_path, content, justification in survivors:
            receipts.append(self.write(rel_path, content, author, justification))
        self.ledger.append(
            kind="memory_flush", author=author,
            body={"session_id": session_id, "persisted": len(receipts),
                  "explicit_nothing": len(receipts) == 0},
            tags=("memory", "flush"),
        )
        self._flush_receipts.add(session_id)
        return receipts

    def compact_allowed(self, session_id: str) -> None:
        """Compaction calls this first. No flush, no compaction — the order is
        the whole point."""
        if session_id not in self._flush_receipts:
            # allow discovery from ledger (fresh process, same session)
            for e in self.ledger.entries():
                if e.kind == "memory_flush" and e.body.get("session_id") == session_id:
                    self._flush_receipts.add(session_id)
                    return
            raise CompactionOrderError(
                f"session {session_id} has not flushed — compacting now would "
                "destroy exactly the context that matters most. Flush first.")

    # ----- the epitaph --------------------------------------------------------

    def epitaph(self, session_id: str, author: str, what_happened: str,
                what_was_learned: str, open_threads: list[str]) -> WriteReceipt:
        """The session's last act: write what survives it. The next agent reads
        this instead of pretending to remember."""
        now = self.ground.now()
        content = "\n".join([
            f"# Epitaph — session {session_id}",
            f"written: {now.isoformat()} by {author}",
            "",
            "This session is over. The agent that wrote this no longer exists.",
            "What follows is the record, not a memory.",
            "",
            "## What happened", what_happened,
            "## What was learned", what_was_learned,
            "## Open threads",
            *[f"- {t}" for t in (open_threads or ["(none)"])],
        ])
        return self.write(
            f"epitaphs/{now.date().isoformat()}-{session_id}.md", content, author,
            synthesis_justification=(
                "session-final state: open threads and learnings exist nowhere "
                "else once this context window is gone"),
        )

    def latest_epitaphs(self, n: int = 3) -> list[str]:
        files = sorted(self.root.glob("epitaphs/*.md"))
        return [f.read_text(encoding="utf-8") for f in files[-n:]]
