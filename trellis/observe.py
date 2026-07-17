"""observe.py — understand a transcript as decisions: two linked nodes each.

Phase B. When the contemplating mind finds a decision inside the record, it does
NOT just note "a decision happened." It records two things, joined:

  * an OBSERVATION — what the ROOM decided, attributed to the people in it, with
    the agent's confidence and a standing "the transcript may be wrong; I only
    had the words" caveat. Never the agent's own ruling.
  * an OPINION — the agent's OWN Y/N/T about that decision (agree, doubt, "this
    rests on an assumption"). The contemplating mind having a view.

They are given DISTINCT, STABLE identities (`obs:<id>` / `op:<id>`) keyed off the
source moment — NOT the free-text subject — so (a) the anti-fork guard never
wrongly refuses the pair, and (b) re-reading the same meeting folds onto the same
nodes instead of forking. Each candidate is INDEPENDENTLY confirmed against the
transcript before it becomes a node (finder != confirmer), and the confirmation
is confidence-aware — a binary "verified" would launder a 0.4 into a 1.0.

No model is imported here: a `detect` callable proposes candidates (a model, in
production; a list, in tests) and a `confirm` callable judges each against the
words. The harness stays model-agnostic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from .clock import TimeGround
from .decisions import Decision, DecisionLog, Verdict, question_key
from .ledger import Ledger
from .sources import Provenance, RawItem


def stable_decision_id(source_ref: str, anchor: str, participants: list,
                       subject: str = "") -> str:
    """The identity of an OBSERVED decision. It keys off WHERE (source+anchor) and
    WHO (participants) so it is stable across re-reads and LIGHT rewording — plus
    the FOLDED subject key, so two genuinely DIFFERENT decisions at the same
    anchor do not collide on one id (the adversary's MED), while light rewording
    (which folds to the same key) still lands on the same node. Heavy rewording
    changes the id, but the ingest layer retires all prior derived-for-this-source
    before re-harvesting, so it still folds rather than forking."""
    who = "\x1f".join(sorted(p.strip().lower() for p in participants if p.strip()))
    raw = f"{source_ref}\x1f{anchor.strip().lower()}\x1f{who}\x1f{question_key(subject)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Candidate:
    """A decision the detector thinks it found in the material."""
    anchor: str                 # a stable locator within the item (a quote, a line ref)
    subject: str                # what the room decided, plainly
    verdict: Verdict            # Y/N/T as the ROOM landed it
    rationale: str              # why the room got there (from the words)
    participants: list          # who was in the room / spoke to it
    emp_lineage: str            # which EMP node this bears on
    # the agent's OWN take (the opinion node):
    opinion_verdict: Verdict
    opinion_rationale: str
    # a T observation needs the room's ≥3 POVs; supplied when verdict is T
    povs: list = field(default_factory=list)
    owner: Optional[str] = None
    revisit_at: Optional[datetime] = None
    missing: Optional[str] = None
    # if the agent's OPINION is itself a T, it must carry its own T-payload
    opinion_povs: list = field(default_factory=list)
    opinion_owner: Optional[str] = None
    opinion_revisit_at: Optional[datetime] = None
    opinion_missing: Optional[str] = None


# detect(item) -> list[Candidate];  confirm(candidate, item) -> (accept, confidence, note)
Detector = Callable[[RawItem], list]
Confirmer = Callable[[Candidate, RawItem], tuple]


class DecisionObserver:
    """Harvests observation+opinion node pairs from ingested items. Plugs into
    the Ingestor as its harvester."""

    def __init__(self, ledger: Ledger, agent: str = "witness",
                 ground: Optional[TimeGround] = None,
                 detect: Optional[Detector] = None,
                 confirm: Optional[Confirmer] = None):
        self.ledger = ledger
        self.log = DecisionLog(ledger, ground)
        self.agent = agent
        self.ground = ground or ledger.ground
        self.detect = detect or (lambda item: [])
        # default confirmer: accept, medium confidence — real use passes a model lens
        self.confirm = confirm or (lambda c, item: (True, 0.6, "no independent confirm"))

    def harvest(self, item: RawItem, prov: Provenance) -> list:
        """The Ingestor calls this once per item. Returns the derived entry ids
        (both nodes per accepted candidate) so ingestion can retire them cleanly
        on a correction."""
        derived: list = []
        for cand in self.detect(item):
            accept, confidence, note = self.confirm(cand, item)
            if not accept:
                # record the rejection on the trail — never silently drop
                self.ledger.append("observation_check", self.agent,
                                   {"anchor": cand.anchor, "accepted": False,
                                    "confidence": confidence, "note": note},
                                   event_time=item.event_time, tags=("observe", "rejected"))
                continue
            did = stable_decision_id(prov.source_refs[0], cand.anchor,
                                     cand.participants, cand.subject)
            derived += self._write_pair(cand, did, confidence, prov, item, note)
        return derived

    def _write_pair(self, cand: Candidate, did: str, confidence: float,
                    prov: Provenance, item: RawItem, note: str) -> list:
        obs_key, op_key = f"obs:{did}", f"op:{did}"
        # Construct BOTH nodes BEFORE appending EITHER — so a malformed opinion
        # (e.g. an opinion T with no POVs, an explicitly-allowed verdict) raises
        # at construction and leaves NO half-written pair on the append-only
        # ledger (the adversary's HIGH: a mid-pair crash).
        observation = Decision(
            subject=cand.subject, verdict=cand.verdict, rationale=cand.rationale,
            author=f"observer:{self.agent}", emp_lineage=cand.emp_lineage,
            key=obs_key, attributed_to=list(cand.participants),
            confidence=round(confidence, 3), provenance=prov.to_dict(),
            povs=cand.povs, owner=cand.owner, revisit_at=cand.revisit_at,
            missing=cand.missing)
        opinion = Decision(
            subject=f"[my take] {cand.subject}", verdict=cand.opinion_verdict,
            rationale=cand.opinion_rationale, author=self.agent,
            emp_lineage=cand.emp_lineage, key=op_key, opinion_of=observation.id,
            provenance=prov.to_dict(), povs=cand.opinion_povs,
            owner=cand.opinion_owner, revisit_at=cand.opinion_revisit_at,
            missing=cand.opinion_missing)
        # both valid — now append (observation, its confirmation trail, opinion)
        obs_entry = self.log.record(observation, event_time=item.event_time)
        self.ledger.append("observation_check", self.agent,
                           {"observation_id": observation.id, "accepted": True,
                            "confidence": round(confidence, 3), "note": note},
                           event_time=item.event_time, tags=("observe", "confirmed"))
        op_entry = self.log.record(opinion, event_time=item.event_time)
        return [obs_entry.id, op_entry.id]

    # ----- reading back: the pair, always together --------------------------

    def pair_for(self, observation_id: str) -> dict:
        """An observation and its opinion, so a reader never confuses what the
        room decided with what the agent thinks about it."""
        obs = self.ledger.get(observation_id)
        opinion = None
        for e in self.ledger.active("decision"):
            if e.body.get("opinion_of") == observation_id:
                opinion = e
                break
        return {"observation": obs, "opinion": opinion}


# ----- conversation velocity: density as a proxy for stakes -----------------

@dataclass
class Velocity:
    messages: int
    span_hours: float
    participants: int
    per_hour: float
    burst: bool             # a lot said in a short window — heat the words don't carry

    def caveat(self) -> str:
        return ("velocity is a PROXY for stakes/heat — the agent infers it from "
                "density, it cannot feel the room")


def conversation_velocity(timestamps: list, authors: list,
                          burst_threshold: float = 30.0) -> Velocity:
    """How much conversation happened in how much time — a signal the words alone
    don't carry, recorded honestly as an inference, never as felt emotion."""
    if not timestamps:
        return Velocity(0, 0.0, 0, 0.0, False)
    ts = sorted(timestamps)
    span = (ts[-1] - ts[0]).total_seconds() / 3600.0
    span = max(span, 1e-9)
    per_hour = len(ts) / span
    return Velocity(messages=len(ts), span_hours=round(span, 3),
                    participants=len({a.strip().lower() for a in authors if a.strip()}),
                    per_hour=round(per_hour, 2), burst=per_hour >= burst_threshold)


# ----- provenance-preserving reads (no laundering upward) -------------------

def synthesize_read(observations: list, event_time: datetime) -> dict:
    """Fold several observations into one 'current read' WITHOUT laundering: the
    read's confidence is the FLOOR of its inputs', and its provenance is the
    union (machine-transcribed if ANY input was). A confident read cannot be
    built out of shaky observations."""
    confs = [o.body.get("confidence") for o in observations
             if o.body.get("confidence") is not None]
    provs = [Provenance(
                source_refs=tuple(o.body.get("provenance", {}).get("source_refs", [])),
                event_time=event_time,
                machine_transcribed=o.body.get("provenance", {}).get("machine_transcribed", False),
                event_time_reconstructed=o.body.get("provenance", {}).get("event_time_reconstructed", True),
                transcript_fallible=o.body.get("provenance", {}).get("transcript_fallible", True))
             for o in observations]
    merged = Provenance.merge(provs, event_time) if provs else None
    return {
        "confidence": round(min(confs), 3) if confs else None,   # FLOOR, never max
        "rests_on": [o.body.get("decision_id") for o in observations],
        "provenance": merged.to_dict() if merged else None,
        "machine_transcribed": merged.machine_transcribed if merged else False,
    }
