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

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .clock import TimeGround
from .identity import fold_text, is_effectively_blank
from .ledger import Ledger, Entry


def question_key(subject: str) -> str:
    """The stable identity of the QUESTION a decision answers. Homoglyph- and
    case-folded (so a Cyrillic-'o' twin of a subject cannot open a second live
    head on the same question), then reduced to a hyphenated keyword slug. Two
    decisions with the same question_key answer the same question — and only one
    may be live at once (plan §2b anti-fork)."""
    # casefold FIRST so uppercase homoglyphs (e.g. Cyrillic 'О') lower to their
    # twin BEFORE the confusable table (whose keys are lowercase) runs inside
    # fold_text — otherwise an uppercase lookalike would dodge the table and open
    # a second live head (Phase-2 adversary). fold_text then does NFKD +
    # confusables + strip-invisible. Not adversarially complete against every
    # exotic glyph (see identity.py's documented limit; the real backstop is
    # human review of the board) — but the ordinary attack is closed.
    folded = fold_text((subject or "").casefold())
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


class Verdict(str, Enum):
    Y = "Y"
    N = "N"
    T = "T"


class IncompleteTriangulationError(Exception):
    """A T without ≥3 named POVs + owner + revisit time is a 'maybe' wearing
    a costume. Refused at creation."""


class CollidingDecisionError(Exception):
    """Two live decisions cannot answer the same question. A fresh Y/N minted on
    a question that already has a live decision is the silent re-decide the crux
    forbids — route it through reopen()/resolve() so the flip is ON THE RECORD
    with lineage (plan §2b, flaw #1)."""


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
    # --- the contemplative-ingestion extension (Phase B) ---
    key: Optional[str] = None        # explicit question_key override (e.g. "obs:<id>"),
                                     # so an observation and its opinion get DISTINCT,
                                     # stable identities instead of colliding on a subject slug
    attributed_to: Optional[list] = None   # for an OBSERVATION: the room's participants
                                     # (whose decision it was) — distinct from `author`
                                     # (who RECORDED it)
    confidence: Optional[float] = None     # how sure, given only the words (0..1)
    provenance: Optional[dict] = None      # Provenance.to_dict(): source_refs, fallibility
    opinion_of: Optional[str] = None       # for an OPINION node: the observation id it's about
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def effective_key(self) -> str:
        """The question identity used for anti-fork. An explicit `key` (a stable
        obs:/op: identity from the source) wins; otherwise the folded subject
        slug (the ordinary case). Keying observations off a stable id, not the
        free-text subject, is what makes re-harvest fold instead of fork."""
        return self.key.strip() if self.key and self.key.strip() else question_key(self.subject)

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
            "question_key": self.effective_key(),
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
            "attributed_to": list(self.attributed_to) if self.attributed_to else None,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "opinion_of": self.opinion_of,
        }


class DecisionLog:
    """Decisions live in the ledger like everything else — same bitemporal
    stamps, same supersession, same search. This class is just the grammar."""

    KIND = "decision"

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground

    def _qkey_of(self, e: Entry) -> str:
        """The question-key of a stored decision, computed defensively for
        entries written before question_key existed."""
        return e.body.get("question_key") or question_key(e.body.get("subject", ""))

    def active_head(self, qkey: str) -> Optional[Entry]:
        """The single live decision answering a question, or None. Routed through
        the validity-aware resolver (plan §2c/2d), so a retired or superseded
        decision is never returned as the head."""
        for e in self.ledger.active(self.KIND):
            if self._qkey_of(e) == qkey:
                return e
        return None

    def record(self, decision: Decision,
               event_time: Optional[datetime] = None) -> Entry:
        # Anti-fork on QUESTION-KEY (flaw #1): the ledger's supersession guard
        # only fires when `supersedes is not None`, so an unlinked fresh Y/N on a
        # settled question would slip through as a second live head. record() is
        # the brand-new-decision path; it refuses a collision outright. Changing
        # a live answer must go through resolve() (which supersedes, with
        # lineage) — reachable via Navigator.reopen()+resolve or decide().
        qk = decision.effective_key()
        clash = self.active_head(qk)
        if clash is not None:
            raise CollidingDecisionError(
                f"a live decision already answers {decision.subject!r} "
                f"(verdict {clash.body.get('verdict')}, id "
                f"{clash.body.get('decision_id')}). Reopen and resolve it — do "
                "not mint a second live head (that is a silent re-decide).")
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
        body = resolution.to_body()
        # A resolution ANSWERS THE SAME QUESTION it supersedes. If the resolution
        # was worded differently its question_key would drift to a new key, and —
        # worse — could COLLIDE with a *different* already-live head, minting two
        # live heads on one question with no supersession link between them (the
        # Phase-2 adversary's confirmed HIGH). Inherit the superseded entry's
        # question_key so the resolution stays bound to its question and the
        # anti-fork holds by construction; the reworded subject is still kept
        # verbatim for readability and lineage.
        inherited = self._qkey_of(old)
        if body.get("question_key") != inherited:
            body = {**body, "question_key": inherited,
                    "reworded_from": old.body.get("subject")}
        return self.ledger.append(
            kind=self.KIND,
            author=resolution.author,
            body=body,
            tags=("ynt", resolution.verdict.value, resolution.emp_lineage),
            supersedes=old.id,
        )

    REOPEN_KIND = "reopen"

    def reopen(self, decision_id: str, trigger: str, author: str,
               event_time: Optional[datetime] = None) -> Entry:
        """Re-surface a settled decision because something changed — WITHOUT
        re-deciding it (plan §2b, flaw #2). A real T needs ≥3 POVs + owner +
        revisit + missing, which a bare trigger cannot supply, so reopen does
        NOT mint a T; it appends a lightweight reopen-marker that makes the node
        show up as needing re-triangulation. A later step assembles the full T
        payload (via resolve) to promote it. The decision itself is untouched —
        divergence RECORDS, it never silently flips."""
        head = self._entry_for(decision_id)
        if head is None:
            raise KeyError(f"unknown or inactive decision: {decision_id}")
        if is_effectively_blank(trigger):
            raise ValueError("reopen needs a trigger — why is this live again?")
        qk = self._qkey_of(head)
        return self.ledger.append(
            kind=self.REOPEN_KIND, author=author,
            body={"reopens": decision_id, "question_key": qk,
                  "subject": head.body.get("subject"), "trigger": trigger},
            event_time=event_time, tags=("reopen", qk),
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

    def reopened(self) -> list[Entry]:
        """Active decision heads carrying an OPEN reopen-marker: a question a
        trigger re-surfaced that has not yet been re-triangulated or resolved.
        A marker is open iff the active head is still the EXACT decision it
        reopened — a resolve() supersedes that decision with a new one (new
        decision_id), which closes the marker. Identity, not timestamps, so a
        frozen or coarse clock can't make a resolved head look unresolved."""
        out, seen = [], set()
        for m in self.ledger.entries():
            if m.kind != self.REOPEN_KIND:
                continue
            qk = m.body.get("question_key")
            reopened_id = m.body.get("reopens")
            head = self.active_head(qk) if qk else None
            if head is None or qk in seen:
                continue
            if head.body.get("decision_id") == reopened_id:
                seen.add(qk)
                out.append(head)
        return out

    def open_questions(self) -> list[Entry]:
        """The single attention rail: unresolved Ts past revisit (hidden nos)
        AND reopened heads — everything the harness should surface 'before
        anything else'. Deduped by entry id."""
        out, seen = [], set()
        for e in self.hidden_nos() + self.reopened():
            if e.id not in seen:
                seen.add(e.id)
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
