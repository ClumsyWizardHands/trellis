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

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .clock import TimeGround
from .ledger import Ledger


class SynthesisTestError(Exception):
    """The write didn't justify its own persistence."""


class CompactionOrderError(Exception):
    """Compaction attempted before the memory flush."""


_BOILERPLATE = {
    "important", "context", "for later", "might need", "just in case",
    "n/a", "na", "none", "misc", "notes", "memory", "todo",
}
# word-level boilerplate: the multi-word phrases above must be split, or a
# single-token test never matches "for later" and pure-filler prose like
# "todo notes misc for later just in case" slips through (#50 round 3).
_BOILERPLATE_WORDS = {w for phrase in _BOILERPLATE for w in phrase.split()}
# Common filler — a justification made ONLY of these has said nothing.
_FILLER = {
    "this", "is", "a", "an", "the", "that", "we", "want", "to", "keep", "it",
    "here", "for", "of", "and", "or", "so", "thing", "stuff", "need", "have",
    "be", "will", "can", "should", "there", "some", "just", "really", "very",
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

    def write(self, rel_path: str, content: str, author: str,
              synthesis_justification: str) -> WriteReceipt:
        problem = _fails_synthesis(synthesis_justification)
        if problem:
            raise SynthesisTestError(problem)
        path = (self.root / rel_path).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError(f"write escapes workspace: {rel_path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        entry = self.ledger.append(
            kind="memory_write", author=author,
            body={"path": str(path.relative_to(self.root)),
                  "bytes": len(content.encode("utf-8")),
                  "synthesis_justification": synthesis_justification},
            tags=("memory",),
        )
        return WriteReceipt(str(path), entry.id, synthesis_justification)

    def read(self, rel_path: str) -> str:
        return (self.root / rel_path).read_text(encoding="utf-8")

    def map(self) -> list[str]:
        """Titles-only map for prompt injection — the navigational cold layer.
        The map, never the territory."""
        out = []
        for p in sorted(self.root.rglob("*.md")):
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
