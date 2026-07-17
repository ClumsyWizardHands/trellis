"""navigate.py — memory is navigation, not an automatic saved state.

"You remember nothing. Each session you re-learn the decisions by walking them."
This is the three-verb grammar that makes that safe, composed to fit the EXISTING
Decision constraints (the plan's stress-test proved a naive sketch could not):

    WALK   — re-inhabit a settled decision read-only. Reconstruct the *why*.
             Cannot emit a verdict; writes nothing. (invariant #3: WALK never
             re-decides — it re-reads.)
    REOPEN — something changed; re-surface the node as needing re-triangulation.
             Writes a lightweight reopen-marker, NOT a bare `T` (a real T needs
             ≥3 POVs + owner + revisit + missing — a trigger can't supply them).
    DECIDE — commit Y/N. ONLY on (a) a brand-new question-key, or (b) resolving
             an existing `T`. It REFUSES to mint a second live Y/N on a question
             that already has a live decision — that must go through reopen +
             resolve, so the flip is on the record with lineage.

Reading is navigation over the ledger (cold); the resolved-head cache is the hot
path. Titles are the index — you find the door by its label, then walk through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .decisions import (CollidingDecisionError, Decision, DecisionLog, Verdict,
                        question_key)
from .ledger import Entry, Ledger
from .memory import Workspace


class ReopenRequiredError(Exception):
    """DECIDE hit a live Y/N on the same question. You cannot silently flip a
    settled answer — reopen() it (recording the trigger), then resolve() with
    the new decision, so the change carries lineage."""


@dataclass(frozen=True)
class Walk:
    """A read-only reconstruction of a decision's *why*. There is deliberately
    no way to emit a verdict from a Walk — re-inhabiting is not re-deciding.
    `as_recorded` is the HISTORICAL verdict already on the record (reading it is
    not deciding); the type has no method that writes."""
    decision_id: str
    subject: str
    as_recorded: str                 # the verdict already on record (history, not a new call)
    rationale: str
    povs: list[dict] = field(default_factory=list)
    upstream: list[dict] = field(default_factory=list)
    related_titles: list[tuple[str, str]] = field(default_factory=list)
    reopened: bool = False


@dataclass(frozen=True)
class NavHit:
    kind: str          # "decision" | "memory"
    title: str
    ref: str           # decision_id or workspace path — what you open next


class ResolvedHeadCache:
    """Materialized view: question_key → the validity-aware HEAD of each
    decision chain (plan §2c). Navigation is the cold/audit path; this is the
    hot read.

    Cache key = (ledger length, # retirements EFFECTIVE at now). Length alone is
    NOT sound: `active()`'s validity is time-dependent, so a FUTURE-dated
    `valid_to` can elapse — moving an entry out of the active set — with no new
    append to bump the length (the Phase-2 adversary's HIGH). Both terms are
    monotonic in time, so the tuple changes exactly when the active set can, and
    the cache can never serve a retired head."""

    def __init__(self, log: DecisionLog):
        self.log = log
        self._version: tuple[int, int] = (-1, -1)
        self._heads: dict[str, Entry] = {}

    def _rebuild_if_stale(self) -> None:
        entries = self.log.ledger.entries()
        now = self.log.ledger.ground.now()
        effective_retirements = 0
        for e in entries:
            if e.kind == Ledger.RETIREMENT_KIND:
                raw = e.body.get("valid_to")
                if raw and datetime.fromisoformat(raw) <= now:
                    effective_retirements += 1
        version = (len(entries), effective_retirements)
        if version != self._version:
            self._heads = {self.log._qkey_of(e): e
                           for e in self.log.ledger.active(self.log.KIND)}
            self._version = version

    def head(self, qkey: str) -> Optional[Entry]:
        self._rebuild_if_stale()
        return self._heads.get(qkey)

    def heads(self) -> dict[str, Entry]:
        self._rebuild_if_stale()
        return dict(self._heads)


class Navigator:
    """The three-verb grammar over a DecisionLog + an optional Workspace."""

    def __init__(self, log: DecisionLog, workspace: Optional[Workspace] = None):
        self.log = log
        self.workspace = workspace
        self.cache = ResolvedHeadCache(log)

    # ----- WALK (read-only) --------------------------------------------------

    def walk(self, decision_id: str) -> Optional[Walk]:
        """Re-inhabit a decision. Read-only: nothing is appended; no verdict is
        emitted. Returns None if the id is unknown/inactive."""
        head = self.log._entry_for(decision_id)
        if head is None:
            return None
        qk = self.log._qkey_of(head)
        related = []
        if self.workspace is not None:
            # navigate to memory whose TITLE echoes this question (map, not body)
            related = self.workspace.search_titles(head.body.get("subject", ""))[:5]
        reopened_ids = {e.id for e in self.log.reopened()}
        return Walk(
            decision_id=decision_id,
            subject=head.body.get("subject", ""),
            as_recorded=head.body.get("verdict", ""),
            rationale=head.body.get("rationale", ""),
            povs=head.body.get("povs", []),
            upstream=self.log.upstream(decision_id),
            related_titles=related,
            reopened=head.id in reopened_ids,
        )

    # ----- REOPEN (re-surface, do not re-decide) -----------------------------

    def reopen(self, decision_id: str, trigger: str, author: str,
               event_time: Optional[datetime] = None) -> Entry:
        return self.log.reopen(decision_id, trigger, author, event_time=event_time)

    # ----- DECIDE (commit, anti-fork) ----------------------------------------

    def decide(self, decision: Decision,
               event_time: Optional[datetime] = None) -> Entry:
        """Commit a Y/N/T. Brand-new question → record. Live `T` on the same
        question → resolve it (supersede, with lineage). Live Y/N on the same
        question → REFUSE: reopen()+resolve() is the only lineage-preserving way
        to change a settled answer. This is what enforces 'divergence records,
        never a silent flip'."""
        qk = question_key(decision.subject)
        head = self.cache.head(qk) or self.log.active_head(qk)
        if head is None:
            return self.log.record(decision, event_time=event_time)
        if head.body.get("verdict") == Verdict.T.value:
            return self.log.resolve(head.body["decision_id"], decision)
        raise ReopenRequiredError(
            f"{decision.subject!r} already has a live {head.body.get('verdict')} "
            f"decision ({head.body.get('decision_id')}). Reopen it with the "
            "trigger, then resolve() — do not mint a second live head.")

    def resolve(self, decision_id: str, resolution: Decision) -> Entry:
        """Promote/settle: supersede an existing head (a hidden-no T, or a
        reopened Y/N) with a new decision. The lineage keeps both."""
        return self.log.resolve(decision_id, resolution)

    # ----- title search (the index) ------------------------------------------

    def search_titles(self, keywords: str) -> list[NavHit]:
        """Search TITLES across both stores — decision subjects and memory
        titles — and return findable hits, never bodies. Open the body you want
        with walk(ref) (decision) or workspace.read(ref) (memory)."""
        want = [w for w in keywords.lower().split() if w]
        hits: list[NavHit] = []
        for e in self.log.ledger.active(self.log.KIND):
            subject = e.body.get("subject", "")
            hay = subject.lower()
            score = sum(1 for w in want if w in hay)
            if score:
                hits.append((score, NavHit("decision", subject,
                                           e.body.get("decision_id", e.id))))
        if self.workspace is not None:
            for title, path in self.workspace.search_titles(keywords):
                score = sum(1 for w in want if w in title.lower())
                hits.append((max(score, 1), NavHit("memory", title, path)))
        hits.sort(key=lambda h: (-h[0], h[1].title))
        return [h for _, h in hits]
