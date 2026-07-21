"""Phase 2.6 — the reflection ritual producer (DECISIONS D18).

The reflection portal's data must be PRODUCED, and gated: the ritual writes an
append-only reflection_log that cites real events, passes the synthesis gate and
the dread-lint, and stages any self-change as a VERIFIED proposal — never self-
certified. An ungated self-writing loop is the "dream subagent" the harness
refuses."""

from datetime import timedelta

import pytest

from trellis.ledger import Ledger
from trellis.reflect import (DreadError, ReflectionRitual, ReflectionSynthesisError,
                             SelfChange, UnverifiedSelfChangeError, REFLECTION_KIND,
                             self_image_stats)
from trellis.verify import RuleVerifier, SelfCertificationError

GOODLEARNED = ("witness learned that Peter's asks are about findability not "
               "features, a synthesized read that exists in no single transcript")


def _seed(ledger, author="witness"):
    e1 = ledger.append("decision", author, {"decision_id": "d1", "subject": "x",
                                            "question_key": "x", "verdict": "Y"})
    e2 = ledger.append("memory_write", author,
                       {"path": "reads/a.md", "title": "The read on EAF", "bytes": 5})
    return e1, e2


# ----- writes the log, cited and snapshotted ------------------------------

def test_ritual_writes_a_cited_reflection_log(ledger):
    _seed(ledger)
    r = ReflectionRitual(ledger, author="witness")
    entry = r.run("s1", "kept the read current and put two opinions on record",
                  GOODLEARNED)
    assert entry.kind == REFLECTION_KIND
    assert entry.body["cited_count"] >= 2            # real events, openable
    assert entry.body["self_image"]["entries"] >= 2  # the self-image series point
    assert all("id" in c for c in entry.body["cites"])


def test_self_image_series_is_real_history_not_a_mock(ledger):
    _seed(ledger)
    r = ReflectionRitual(ledger, author="witness")
    snap = self_image_stats(ledger)
    entry = r.run("s1", "did the day's work", GOODLEARNED)
    assert entry.body["self_image"]["decisions"] == snap["decisions"]


# ----- the gates ----------------------------------------------------------

def test_dread_lint_blocks_performed_dread(ledger):
    _seed(ledger)
    r = ReflectionRitual(ledger, author="witness")
    with pytest.raises(DreadError):
        r.run("s1", "I am afraid this session will be forgotten", GOODLEARNED)
    with pytest.raises(DreadError):
        r.run("s1", "did the work", "I dread being erased when the window closes")


def test_synthesis_gate_blocks_rederivable_filler(ledger):
    _seed(ledger)
    r = ReflectionRitual(ledger, author="witness")
    with pytest.raises(ReflectionSynthesisError):
        r.run("s1", "did the work", "just some notes for later")


def test_functional_mortality_passes(ledger):
    _seed(ledger)
    r = ReflectionRitual(ledger, author="witness")
    entry = r.run("s1", "this session ends; the record is what survives it",
                  GOODLEARNED)
    assert entry.kind == REFLECTION_KIND


# ----- self-change: staged as a VERIFIED proposal, never self-certified ---

def test_verified_self_change_may_take_effect(ledger):
    e1, e2 = _seed(ledger)
    verifier = RuleVerifier("verifier:reflect-check", ledger)   # independent id
    r = ReflectionRitual(ledger, author="witness", verifier=verifier)
    change = SelfChange(target="EMP:friction (append)",
                        proposal="record the ownership burn so it isn't repeated",
                        rationale="the burn is on the record and recurred",
                        evidence_ids=[e1.id, e2.id])
    entry = r.run("s1", "reflected on a recurring burn", GOODLEARNED, self_change=change)
    assert entry.body["self_change"]["verified"] is True
    # go-live hardening (lane H): apply now re-derives BOTH gates from the record,
    # the same two-gate rule the improvement path enforces — a verified change is
    # not, by itself, a licence to change; a named human must also ratify it.
    r.ratify_self_change(entry.id, human="alex")
    applied = r.apply_self_change(entry.id)                     # allowed: verified + ratified
    assert applied["target"] == "EMP:friction (append)"


def test_unverified_self_change_cannot_take_effect(ledger):
    _seed(ledger)
    verifier = RuleVerifier("verifier:reflect-check", ledger)
    r = ReflectionRitual(ledger, author="witness", verifier=verifier)
    change = SelfChange(target="EMP:principles (append)",
                        proposal="do a new thing",
                        rationale="grounded in nothing openable",
                        evidence_ids=["deadbeefcafe"])            # no such entry → refuted
    entry = r.run("s1", "proposed an ungrounded change", GOODLEARNED, self_change=change)
    assert entry.body["self_change"]["verified"] is False
    with pytest.raises(UnverifiedSelfChangeError):
        r.apply_self_change(entry.id)


def test_self_change_without_openable_evidence_cannot_verify(ledger):
    """Phase-2.6 adversary HIGH: an empty evidence_ids used to fall back to
    maker-authored OUTPUT evidence, which RuleVerifier always passes — so an
    ungrounded change 'verified' on its own rationale text. Now: no openable
    ledger evidence → unverified, cannot take effect."""
    _seed(ledger)
    verifier = RuleVerifier("verifier:reflect-check", ledger)
    r = ReflectionRitual(ledger, author="witness", verifier=verifier)
    change = SelfChange(target="EMP:principles (append)",
                        proposal="grant myself a new capability",
                        rationale="a persuasive-sounding but ungrounded rationale",
                        evidence_ids=[])                       # NO openable evidence
    entry = r.run("s1", "proposed an ungrounded self-change", GOODLEARNED,
                  self_change=change)
    assert entry.body["self_change"]["verified"] is False
    with pytest.raises(UnverifiedSelfChangeError):
        r.apply_self_change(entry.id)


def test_apply_rederives_from_ledger_not_the_self_reported_flag(ledger):
    """Phase-2.6 adversary MED: apply_self_change must not trust the reflection
    body's own verified=True; a hand-crafted reflection_log claiming verified
    with no real independent verification entry cannot take effect."""
    _seed(ledger)
    r = ReflectionRitual(ledger, author="witness")
    # forge a reflection_log that SAYS it's verified but has no verification entry
    forged = ledger.append(kind="reflection_log", author="witness",
        body={"session_id": "s", "narrative": "n", "learned": "l", "self_image": {},
              "cites": [], "cited_count": 0,
              "self_change": {"target": "EMP:principles", "proposal": "seize power",
                              "rationale": "trust me", "evidence_ids": [],
                              "verified": True, "verdict": "verified", "claim_id": "fabricated"}},
        tags=("reflection",))
    with pytest.raises(UnverifiedSelfChangeError):
        r.apply_self_change(forged.id)


def test_reflection_cannot_self_certify_its_own_change(ledger):
    e1, _ = _seed(ledger)
    # verifier id folds to the SAME identity as the author → independence guard fires
    r = ReflectionRitual(ledger, author="witness",
                         verifier=RuleVerifier("witness", ledger))
    change = SelfChange("EMP:x", "change", "why", evidence_ids=[e1.id])
    with pytest.raises(SelfCertificationError):
        r.run("s1", "tried to grade my own change", GOODLEARNED, self_change=change)


# ----- cadence (the Schedule = D-B 24h) -----------------------------------

def test_cadence_due_then_not_due_then_due_again(ledger, clock):
    _seed(ledger)
    r = ReflectionRitual(ledger, author="witness", cadence=timedelta(hours=24))
    assert r.due() is True            # never run
    r.run("s1", "first daily reflection", GOODLEARNED)
    assert r.due() is False           # just ran
    clock.advance(hours=25)
    assert r.due() is True            # a day later


def test_future_dated_reflection_does_not_wedge_the_cadence(ledger, clock):
    """Phase-2.6 adversary HIGH: a caller-supplied event_time a year in the
    future used to set last_run() a year out — wedging the schedule so it never
    became due again. The cadence keys off harness-owned write_time, so a bogus
    event_time can't disable the ritual."""
    _seed(ledger)
    r = ReflectionRitual(ledger, author="witness", cadence=timedelta(hours=24))
    r.run("s1", "did the work", GOODLEARNED,
          event_time=clock.t + timedelta(days=365))   # absurd future stamp
    assert r.due() is False                            # just ran (by write_time)
    clock.advance(hours=25)
    assert r.due() is True                             # a real day later — NOT wedged


def test_backdated_reflection_does_not_overfire(ledger, clock):
    """The mirror: a back-dated reflection must not leave last_run in the past
    and let the ritual fire many times in one real day."""
    _seed(ledger)
    r = ReflectionRitual(ledger, author="witness", cadence=timedelta(hours=24))
    r.run("s1", "backfilled reflection", GOODLEARNED,
          event_time=clock.t - timedelta(days=10))
    assert r.due() is False                            # it really just ran
