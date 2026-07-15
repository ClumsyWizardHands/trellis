"""decisions.py — the atomic record is the Y/N/T decision. (DECISIONS.md D1)

"The atomic units are recursive SLUTs and the recursive Y/N/T decision SLUTs."
— Brett, 2026-07-13 (explicit self-correction; supersedes 'EMPs are atomic')

The grammar (DAILY-EMPIRE-PROTOCOL, 2026-07-15):
    Y — commit.
    N — decline, but returnable. A real no, on the record. (Of 2,000 nodes an
        agent minted in one week, exactly one was a no — Brett, 2026-07-02.
        The format has to make N cheap and T expensive-but-honest.)
    T — triangulate: a call for AT LEAST THREE named points of view. Never
        "maybe". Every T names its missing piece, an owner, and a revisit
        time. "An unresolved T is a hidden no."

Every decision carries lineage back to the EMP node it expresses — the
breadcrumbs upstream (Brett, 2026-07-12) — and both timestamps, so a decision
about April made in July never masquerades as an April decision.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .clock import TimeGround
from .identity import is_effectively_blank
from .ledger import Ledger, Entry


class Verdict(str, Enum):
    Y = "Y"
    N = "N"
    T = "T"


class IncompleteTriangulationError(Exception):
    """A T without ≥3 named POVs + owner + revisit time is a 'maybe' wearing
    a costume. Refused at creation."""


@dataclass(frozen=True)
class POV:
    """A named point of view contributing to a triangulation. Named means
    attributable — 'some agents thought' is not a POV."""
    holder: str        # who holds this view (human or agent id)
    position: str      # what they actually say
    basis: str = ""    # what it rests on (source, experience, principle)

    def __post_init__(self):
        if not self.holder.strip() or not self.position.strip():
            raise ValueError("a POV requires a named holder and a stated position")


@dataclass
class Decision:
    subject: str                     # what is being decided, plainly
    verdict: Verdict
    rationale: str                   # why — in plain language, no spec-speak
    author: str                      # who/what minted this decision
    emp_lineage: str                 # the EMP node this expresses, e.g. "EMP:ends[1]"
    povs: list[POV] = field(default_factory=list)
    owner: Optional[str] = None      # T: who owns resolving it
    revisit_at: Optional[datetime] = None  # T: when it must be re-decided
    missing: Optional[str] = None    # T: the specific named missing piece
    returnable_note: Optional[str] = None  # N: what would reopen it
    parent_id: Optional[str] = None  # recursion: decisions nest under decisions
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        # coerce/validate the verdict FIRST. A raw string like "t" or "maybe"
        # used to sail past the T-guard and then crash to_body() on .value
        # (found by the adversary, #27 HIGH).
        if not isinstance(self.verdict, Verdict):
            try:
                self.verdict = Verdict(str(self.verdict))
            except ValueError:
                raise ValueError(
                    f"unknown verdict {self.verdict!r} — use Verdict.Y/N/T "
                    "(uppercase Y, N, or T)")
        if not self.subject.strip():
            raise ValueError("a decision needs a subject")
        if not self.rationale.strip():
            raise ValueError("a decision without a rationale is a vibe")
        if is_effectively_blank(self.emp_lineage):
            raise ValueError(
                "every decision carries lineage back to an EMP node — "
                "orphan decisions stuck in silos are the named failure mode "
                "(whitespace / zero-width lineage is still an orphan)")
        if self.verdict == Verdict.T:
            named = {p.holder.strip().lower() for p in self.povs}
            if len(named) < 3:
                raise IncompleteTriangulationError(
                    f"T requires >=3 POVs from distinct named holders, got "
                    f"{len(named)} — a T is a call for perspectives, not a maybe")
            if not self.owner:
                raise IncompleteTriangulationError("T requires an owner")
            if self.revisit_at is None:
                raise IncompleteTriangulationError(
                    "T requires a revisit time — an unresolved T is a hidden no")
            if self.revisit_at.tzinfo is None:
                raise IncompleteTriangulationError(
                    "revisit_at must be timezone-aware — a naive revisit time "
                    "would crash the hidden-no query for the whole board")
            if not self.missing:
                raise IncompleteTriangulationError(
                    "T must name the specific missing piece")

    def to_body(self) -> dict:
        return {
            "decision_id": self.id,
            "subject": self.subject,
            "verdict": self.verdict.value,
            "rationale": self.rationale,
            "emp_lineage": self.emp_lineage,
            "povs": [{"holder": p.holder, "position": p.position, "basis": p.basis}
                     for p in self.povs],
            "owner": self.owner,
            "revisit_at": self.revisit_at.isoformat() if self.revisit_at else None,
            "missing": self.missing,
            "returnable_note": self.returnable_note,
            "parent_id": self.parent_id,
        }


class DecisionLog:
    """Decisions live in the ledger like everything else — same bitemporal
    stamps, same supersession, same search. This class is just the grammar."""

    KIND = "decision"

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground

    def record(self, decision: Decision,
               event_time: Optional[datetime] = None) -> Entry:
        return self.ledger.append(
            kind=self.KIND,
            author=decision.author,
            body=decision.to_body(),
            event_time=event_time,
            tags=("ynt", decision.verdict.value, decision.emp_lineage),
        )

    def resolve(self, decision_id: str, resolution: Decision) -> Entry:
        """Resolve a T (or reopen an N) by superseding it with a new decision.
        The lineage keeps both — you can always walk back upstream."""
        old = self._entry_for(decision_id)
        if old is None:
            raise KeyError(f"unknown decision: {decision_id}")
        resolution.parent_id = decision_id
        return self.ledger.append(
            kind=self.KIND,
            author=resolution.author,
            body=resolution.to_body(),
            tags=("ynt", resolution.verdict.value, resolution.emp_lineage),
            supersedes=old.id,
        )

    def hidden_nos(self) -> list[Entry]:
        """Ts past their revisit time. 'An unresolved T is a hidden no' — this
        query is how the harness makes that visible instead of letting maybes
        rot quietly. An all-green board should show these in red."""
        now = self.ground.now()
        out = []
        for e in self.ledger.current(self.KIND):
            if e.body.get("verdict") != "T":
                continue
            r = e.body.get("revisit_at")
            if r and datetime.fromisoformat(r) < now:
                out.append(e)
        return out

    def upstream(self, decision_id: str) -> list[dict]:
        """Walk a decision's breadcrumbs back toward its EMP node — the
        'Elise, one month in, can read the lineage of decisions and why they
        were made' path (Brett, 2026-07-10)."""
        chain = []
        entries = {e.body.get("decision_id"): e for e in self.ledger.entries()
                   if e.kind == self.KIND}
        cur = entries.get(decision_id)
        seen: set[str] = set()   # a parent_id cycle used to loop forever (#25)
        while cur is not None and cur.body["decision_id"] not in seen:
            seen.add(cur.body["decision_id"])
            chain.append({
                "decision_id": cur.body["decision_id"],
                "subject": cur.body["subject"],
                "verdict": cur.body["verdict"],
                "emp_lineage": cur.body["emp_lineage"],
                "decided": cur.stamp.event_time.isoformat(),
            })
            parent = cur.body.get("parent_id")
            cur = entries.get(parent) if parent else None
        return chain

    def _entry_for(self, decision_id: str) -> Optional[Entry]:
        for e in self.ledger.current(self.KIND):
            if e.body.get("decision_id") == decision_id:
                return e
        return None
