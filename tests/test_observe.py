"""Phase B — understanding a transcript as observation+opinion node pairs.

Pins the two-node model's stress-test fixes: distinct stable identities (no
collision, no fork on re-read), confidence-aware confirmation, and provenance
that never launders upward."""

from datetime import timedelta

from trellis.decisions import DecisionLog, Verdict
from trellis.observe import (Candidate, DecisionObserver, conversation_velocity,
                             stable_decision_id, synthesize_read)
from trellis.sources import Ingestor, RawItem


def _cand(anchor="line-12", subject="Adopt the July framing", verdict=Verdict.Y,
          participants=("brett", "alex"), op=Verdict.N):
    return Candidate(anchor=anchor, subject=subject, verdict=verdict,
                     rationale="the room converged on it after Brett's point",
                     participants=list(participants), emp_lineage="EMP:ends[0]",
                     opinion_verdict=op, opinion_rationale="I doubt this — it rests on an "
                     "assumption about the funder that wasn't tested in the room")


def _item(content="brett: let's adopt the july framing", clock=None, item_id="m1",
          kind="message", machine=False):
    return RawItem(source="discord", channel="chiefs", content=content,
                   event_time=clock.t, item_id=item_id, kind=kind,
                   machine_transcribed=machine)


# ----- stable identity ----------------------------------------------------

def test_stable_id_survives_rewording_but_splits_on_different_moment():
    a = stable_decision_id("k1", "line-12", ["brett", "alex"])
    b = stable_decision_id("k1", "line-12", ["alex", "brett"])   # order-independent
    c = stable_decision_id("k1", "line-99", ["brett", "alex"])   # different moment
    assert a == b and a != c


# ----- the two-node harvest ----------------------------------------------

def test_harvest_writes_observation_and_opinion_linked(ledger, clock):
    obs = DecisionObserver(ledger, agent="witness",
                           detect=lambda item: [_cand()],
                           confirm=lambda c, item: (True, 0.7, "supported by the quote"))
    ing = Ingestor(ledger)
    ing.ingest([_item(clock=clock)], obs.harvest)
    decisions = [e for e in ledger.active("decision")]
    assert len(decisions) == 2
    observation = [d for d in decisions if d.author.startswith("observer:")][0]
    opinion = [d for d in decisions if d.body.get("opinion_of")][0]
    # the observation is attributed to the ROOM, not the agent that recorded it
    assert observation.body["attributed_to"] == ["brett", "alex"]
    assert observation.body["confidence"] == 0.7
    assert observation.body["provenance"]["transcript_fallible"] is True
    # the opinion is the agent's own, linked back to the observation
    assert opinion.body["opinion_of"] == observation.body["decision_id"]
    assert opinion.author == "witness"


def test_observation_and_opinion_do_not_collide(ledger, clock):
    """The core stress-test flaw: both are Decisions about the same subject, so
    without distinct keys the anti-fork guard would refuse the second."""
    obs = DecisionObserver(ledger, detect=lambda item: [_cand()],
                           confirm=lambda c, item: (True, 0.6, ""))
    ing = Ingestor(ledger)
    ing.ingest([_item(clock=clock)], obs.harvest)   # must NOT raise CollidingDecisionError
    assert len([e for e in ledger.active("decision")]) == 2


def test_reharvest_folds_not_forks(ledger, clock):
    """Re-reading the same meeting (a corrected re-dump) must land on the SAME
    obs/op identities, retiring the old pair — never a second forked pair."""
    obs = DecisionObserver(ledger, detect=lambda item: [_cand()],
                           confirm=lambda c, item: (True, 0.6, ""))
    ing = Ingestor(ledger)
    ing.ingest([_item("first dump", clock=clock, item_id="msg-1")], obs.harvest)
    ing.ingest([_item("corrected dump, same meeting", clock=clock, item_id="msg-1")], obs.harvest)
    # still exactly one live observation + one live opinion
    assert len([e for e in ledger.active("decision")]) == 2


def test_two_decisions_in_one_transcript(ledger, clock):
    obs = DecisionObserver(ledger, detect=lambda item: [
        _cand(anchor="line-12", subject="Adopt July framing"),
        _cand(anchor="line-40", subject="Defer the canvas question")],
        confirm=lambda c, item: (True, 0.6, ""))
    Ingestor(ledger).ingest([_item(clock=clock)], obs.harvest)
    assert len([e for e in ledger.active("decision")]) == 4   # two pairs


def test_rejected_candidate_makes_no_node_but_is_recorded(ledger, clock):
    obs = DecisionObserver(ledger, detect=lambda item: [_cand()],
                           confirm=lambda c, item: (False, 0.2, "transcript doesn't support it"))
    Ingestor(ledger).ingest([_item(clock=clock)], obs.harvest)
    assert [e for e in ledger.active("decision")] == []
    rej = [e for e in ledger.entries() if e.kind == "observation_check"
           and e.body.get("accepted") is False]
    assert len(rej) == 1 and rej[0].body["note"]


# ----- provenance never launders -----------------------------------------

def test_synthesize_read_takes_the_confidence_floor(ledger, clock):
    obs = DecisionObserver(ledger, detect=lambda item: [
        _cand(anchor="a", subject="High-confidence call"),
        _cand(anchor="b", subject="Shaky machine-heard call")],
        confirm=lambda c, item: (True, 0.9 if c.anchor == "a" else 0.3, ""))
    # the second rests on machine transcription
    Ingestor(ledger).ingest([_item(kind="media_transcript", machine=True, clock=clock)], obs.harvest)
    observations = [e for e in ledger.active("decision")
                    if e.author.startswith("observer:")]
    read = synthesize_read(observations, clock.t)
    assert read["confidence"] == 0.3            # FLOOR, not the 0.9
    assert read["machine_transcribed"] is True  # shakiness rides along


def test_velocity_is_a_proxy_not_a_feeling(clock):
    base = clock.t
    ts = [base + timedelta(minutes=i) for i in range(60)]     # 60 msgs in ~1h
    v = conversation_velocity(ts, ["brett"] * 30 + ["alex"] * 30, burst_threshold=30)
    assert v.messages == 60 and v.participants == 2 and v.burst is True
    assert "proxy" in v.caveat().lower()


# ----- Phase-B adversary fixes (round 7) ----------------------------------

def test_opinion_T_without_povs_leaves_no_half_written_pair(ledger, clock):
    """The adversary HIGH: an opinion T with no POVs must raise at construction,
    BEFORE the observation is appended — no half-written pair on the ledger."""
    import pytest
    from trellis.decisions import IncompleteTriangulationError
    bad = Candidate(anchor="l1", subject="A call", verdict=Verdict.Y,
                    rationale="the room agreed", participants=["brett"],
                    emp_lineage="EMP:ends[0]", opinion_verdict=Verdict.T,
                    opinion_rationale="needs triangulation")   # T but no opinion_povs
    obs = DecisionObserver(ledger, detect=lambda it: [bad],
                           confirm=lambda c, it: (True, 0.5, ""))
    with pytest.raises(IncompleteTriangulationError):
        Ingestor(ledger).ingest([_item(clock=clock)], obs.harvest)
    assert [e for e in ledger.active("decision")] == []   # nothing half-written


def test_opinion_T_with_full_payload_is_constructible(ledger, clock):
    from trellis.decisions import POV
    good = Candidate(anchor="l1", subject="A call", verdict=Verdict.Y,
                     rationale="room agreed", participants=["brett"],
                     emp_lineage="EMP:ends[0]", opinion_verdict=Verdict.T,
                     opinion_rationale="I think this genuinely needs three views",
                     opinion_povs=[POV("me", "a"), POV("brett", "b"), POV("alex", "c")],
                     opinion_owner="alex", opinion_missing="the funder's read",
                     opinion_revisit_at=clock.t)
    obs = DecisionObserver(ledger, detect=lambda it: [good],
                           confirm=lambda c, it: (True, 0.6, ""))
    Ingestor(ledger).ingest([_item(clock=clock)], obs.harvest)
    assert len([e for e in ledger.active("decision")]) == 2


def test_two_decisions_at_same_anchor_do_not_collide(ledger, clock):
    """The adversary MED: two DIFFERENT decisions at the same anchor+participants
    must not collide on one stable id."""
    obs = DecisionObserver(ledger, detect=lambda it: [
        _cand(anchor="line-5", subject="Adopt the framing"),
        _cand(anchor="line-5", subject="Defer the canvas question")],  # same anchor!
        confirm=lambda c, it: (True, 0.6, ""))
    Ingestor(ledger).ingest([_item(clock=clock)], obs.harvest)
    assert len([e for e in ledger.active("decision")]) == 4   # two full pairs, no collision
