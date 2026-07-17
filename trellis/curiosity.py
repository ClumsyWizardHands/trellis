"""curiosity.py — the contemplating mind's open questions, with teeth.

Phase C. Alex's worry, and the plan stress-test's strongest finding, are the same
one: "two questions a day" is itself the green checkmark it claims to abolish, and
an agent will make one search and call it understanding. This module makes
curiosity STRUCTURAL rather than aspirational:

  * Questions are first-class NODES (not prose), each targeting a named
    assumption, with an owner and a REVISIT time — so an open question sits on a
    staleness rail exactly like "an unresolved T is a hidden no": untouched past
    its revisit, it surfaces as needing attention. It nags until pursued.
  * Anti-fork on the ASSUMPTION: the same curiosity reworded tomorrow folds onto
    the same node (a re-ask), never a fresh checkmark.
  * A seek that changes NOTHING is a "dry" seek — it does NOT advance the
    question. Understanding is only recognised when the MAP ACTUALLY MOVED: a new
    observation, a shifted confidence, a sharpened question. "I searched" is not
    "I understand," and the code refuses to treat it as such.

So the daily gate is not "did I write two questions" — it is "did the open set
get honestly pursued, and did anything I claim to understand actually move the
record." That is the anti-satisficing spine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .clock import TimeGround
from .decisions import question_key
from .identity import is_effectively_blank
from .ledger import Entry, Ledger

QUESTION_KIND = "question"
SEEK_KIND = "seek"


def assumption_key(assumption: str) -> str:
    """The stable identity of the ASSUMPTION a question targets — folded, so a
    reworded curiosity maps to the same node."""
    return "q:" + question_key(assumption)


class NotResolvedError(Exception):
    """A question can't be closed as understood without evidence the map moved.
    'I searched' is not 'I understand' — closing on a dry seek is the exact
    satisficing this module refuses."""


@dataclass
class Question:
    title: str                 # 00-grade: what I'm unsure about, findable
    assumption: str            # the assumption it targets (its stable identity)
    what_would_resolve: str    # what evidence/answer would settle it
    owner: str                 # who owns chasing it (the agent, or Alex)
    revisit_at: datetime       # tz-aware; the staleness rail

    def __post_init__(self):
        for name, v in (("title", self.title), ("assumption", self.assumption),
                        ("what_would_resolve", self.what_would_resolve),
                        ("owner", self.owner)):
            if is_effectively_blank(v):
                raise ValueError(f"a question needs a real {name}")
        if self.revisit_at is None or self.revisit_at.tzinfo is None:
            raise ValueError("a question needs a timezone-aware revisit time — "
                             "an un-revisited question is a curiosity that quietly dies")


class QuestionLog:
    """Open assumptions & curiosities as first-class, staleness-railed nodes."""

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground

    def _active_by_akey(self, akey: str) -> Optional[Entry]:
        for e in self.ledger.active(QUESTION_KIND):
            if e.body.get("assumption_key") == akey:
                return e
        return None

    def ask(self, q: Question, author: str) -> Entry:
        """Record a question — or, if this assumption is already open, RE-ASK it
        (refresh its revisit) rather than mint a duplicate checkmark."""
        akey = assumption_key(q.assumption)
        existing = self._active_by_akey(akey)
        if existing is not None:
            # fold, don't fork: supersede with a refreshed node (a re-ask), so
            # the same curiosity reworded daily is ONE node, not a new tally.
            return self.ledger.append(
                kind=QUESTION_KIND, author=author,
                body={**existing.body, "title": q.title,
                      "what_would_resolve": q.what_would_resolve,
                      "revisit_at": q.revisit_at.isoformat(),
                      "reasked": existing.body.get("reasked", 0) + 1},
                event_time=self.ground.now(), tags=("question", akey),
                supersedes=existing.id)
        return self.ledger.append(
            kind=QUESTION_KIND, author=author,
            body={"question_id": uuid.uuid4().hex[:12],
                  "title": q.title, "assumption": q.assumption,
                  "assumption_key": akey, "what_would_resolve": q.what_would_resolve,
                  "owner": q.owner, "revisit_at": q.revisit_at.isoformat(),
                  "status": "open", "reasked": 0},
            event_time=self.ground.now(), tags=("question", akey))

    def open_questions(self) -> list:
        return [e for e in self.ledger.active(QUESTION_KIND)
                if e.body.get("status") == "open"]

    def stale(self, now: Optional[datetime] = None) -> list:
        """Open questions past their revisit — the "hidden no" of curiosity. An
        agent that only *emits* questions and never pursues them lights this up."""
        now = now or self.ground.now()
        out = []
        for e in self.open_questions():
            r = e.body.get("revisit_at")
            if r and datetime.fromisoformat(r) < now:
                out.append(e)
        return out

    # ----- the anti-satisficing core ----------------------------------------

    def record_seek(self, akey: str, what_searched: str, map_changed: bool,
                    delta_refs: list, author: str) -> Entry:
        """Record a pursuit. `map_changed` + `delta_refs` are the honest report
        of whether the record actually MOVED. A dry seek (map_changed=False) is
        recorded — never hidden — but it does NOT advance the question."""
        return self.ledger.append(
            kind=SEEK_KIND, author=author,
            body={"assumption_key": akey, "searched": what_searched,
                  "map_changed": bool(map_changed),
                  "delta_refs": list(delta_refs or [])},
            event_time=self.ground.now(), tags=("seek", akey))

    def dry_streak(self, akey: str) -> int:
        """Consecutive most-recent dry seeks for a question. A long streak means
        the agent keeps looking and nothing moves — a signal to escalate to a
        human, NOT to quietly declare victory."""
        seeks = [e for e in self.ledger.entries()
                 if e.kind == SEEK_KIND and e.body.get("assumption_key") == akey]
        seeks.sort(key=lambda e: e.stamp.write_time)
        streak = 0
        for e in reversed(seeks):
            if e.body.get("map_changed"):
                break
            streak += 1
        return streak

    def resolve(self, akey: str, how: str, evidence_refs: list, author: str) -> Entry:
        """Close a question as UNDERSTOOD — permitted only when the evidence is
        real and POSTDATES the question (the map moved *since* we asked). A
        resolution resting on nothing new, or on a dry seek, is refused: that is
        the "I searched, therefore I understand" laundering, blocked."""
        q = self._active_by_akey(akey)
        if q is None:
            raise KeyError(f"no open question for {akey}")
        asked_at = q.stamp.write_time
        # evidence must be a REAL, ACTIVE map-move — not the loop's own machinery.
        # The adversary's HIGH: a DRY seek (or a re-ask, or the question itself)
        # postdates the question, so a naive "postdates → counts" check let "I
        # searched" launder into "I understand." Exclude the machinery kinds and
        # require the entry to be live (a retired/superseded entry isn't a move).
        machinery = {QUESTION_KIND, SEEK_KIND, "observation_check", "ingest_marker",
                     "affirmation", "retirement"}
        active_ids = {x.id for x in self.ledger.active()}
        chain = {e.id for e in self.ledger.lineage(q.id)}   # the question's own chain
        real = []
        for ref in evidence_refs or []:
            e = self.ledger.get(ref)
            if (e is not None and e.id not in chain and e.kind not in machinery
                    and e.id in active_ids and e.stamp.write_time >= asked_at):
                real.append(ref)
        if not real:
            raise NotResolvedError(
                "a question can't be closed as understood without evidence that "
                "the map genuinely MOVED since it was asked — a new observation, a "
                "shifted confidence, a sharpened decision. A dry seek, a re-ask, or "
                "the question itself is not a move: 'I searched' is not 'I "
                "understand.' Bring a real, live map-change, or leave it open.")
        return self.ledger.append(
            kind=QUESTION_KIND, author=author,
            body={**q.body, "status": "resolved", "resolved_how": how,
                  "resolved_evidence": real},
            event_time=self.ground.now(), tags=("question", akey, "resolved"),
            supersedes=q.id)
