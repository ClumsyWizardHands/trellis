"""Operate layer — broad, cheap, independent verification (DECISIONS D34/D35).

The verifier is a SECOND, cheaper seat in the same family (Opus makes, Haiku
verifies) — the factory refuses LOUD if the verifier seat equals the maker
(D4 parity). Verification is BROAD, not high-stakes-only: every memory write —
decision-tree writes, reflections, load-bearing claims — is convened past the
deterministic floor + an independent model verifier, refute-by-default, and the
verdict is recorded so trust accrues (an unverified memory error compounds
2%→4%→16% — that quiet compounding is how agents fail over time).

D35 contested-state: a REFUTED verdict appends a `contested` event naming the
subject it refutes (append, NEVER delete) and flags it for human escalation; a
persistent INSUFFICIENT is a recorded capability gap, not a pass. Trust is one
canonical number (verify.trust_record) that every surface delegates to.

Mock verifier providers only — never a real network call.
"""

import pytest

from trellis.providers.base import ProviderResponse
from trellis.providers import provider_from_env, MockProvider, ProviderUnavailable
from trellis.providers.factory import verifier_provider_from_env, VerifierSeatError
from trellis.verify import (CompletionClaim, Evidence, EvidenceKind, ModelVerifier,
                            RuleVerifier, SelfCertificationError, VerdictStatus,
                            convene_verification, contested_items, resolve_contested,
                            trust_record)
from trellis.reflect import ReflectionRitual


GOODLEARNED = ("witness learned that Peter's asks are about findability not "
               "features, a synthesized read that exists in no single transcript")


class Answer:
    """A verifier provider that returns a fixed verdict text and counts calls —
    so a test can prove the floor short-circuits before the model spends."""

    def __init__(self, text: str, ident: str = "verify-model"):
        self.id = ident
        self.text = text
        self.calls = 0

    def complete(self, system, messages, tools=None):
        self.calls += 1
        return ProviderResponse(text=self.text, model="verify-model")


def _decision(ledger):
    return ledger.append("decision", "witness",
                         {"decision_id": "d1", "subject": "eaf posture",
                          "question_key": "eaf posture", "verdict": "Y"})


def _claim(dec_id, maker="witness:opus", task="decision tree write d1"):
    return CompletionClaim(
        maker=maker, task=task, summary="recorded Y on eaf posture",
        evidence=[Evidence(EvidenceKind.LEDGER, dec_id, expect_kind="decision")])


# ---- the second verifier seat (D34): distinct from the maker, refuse loud ----

def _clear(mp):
    for k in ("TRELLIS_PROVIDER", "TRELLIS_VERIFIER_PROVIDER", "TRELLIS_VERIFIER_MODEL",
              "TRELLIS_LOCAL_BASE_URL", "TRELLIS_LOCAL_MODEL", "OPENAI_API_KEY",
              "TRELLIS_OPENAI_MODEL", "TRELLIS_CLAUDE_MODEL"):
        mp.delenv(k, raising=False)


def test_verifier_seat_is_distinct_from_the_maker(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "mock")
    maker = provider_from_env()
    monkeypatch.setenv("TRELLIS_VERIFIER_PROVIDER", "mock")
    monkeypatch.setenv("TRELLIS_VERIFIER_MODEL", "haiku")
    verifier = verifier_provider_from_env(maker)
    assert verifier.id != maker.id            # a genuinely separate seat


def test_verifier_defaults_to_the_makers_family(monkeypatch):
    """Same family, cheaper seat: with no TRELLIS_VERIFIER_PROVIDER the verifier
    rides the maker's backend, distinguished only by the cheaper model."""
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "mock")
    maker = provider_from_env()
    monkeypatch.setenv("TRELLIS_VERIFIER_MODEL", "haiku")   # no VERIFIER_PROVIDER
    verifier = verifier_provider_from_env(maker)
    assert verifier.id != maker.id


def test_maker_cannot_be_its_own_verifier_seat(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "mock")
    maker = provider_from_env()
    monkeypatch.setenv("TRELLIS_VERIFIER_PROVIDER", "mock")   # and NO distinct model
    with pytest.raises(VerifierSeatError):
        verifier_provider_from_env(maker)                    # verifier seat == maker → LOUD


def test_verifier_unset_fails_loud(monkeypatch):
    _clear(monkeypatch)
    with pytest.raises(ProviderUnavailable):
        verifier_provider_from_env()


# ---- convene: a decision-tree write gets a recorded verdict ----

def test_decision_tree_write_gets_a_recorded_verdict(ledger):
    dec = _decision(ledger)
    verifier = ModelVerifier("verifier:haiku", Answer("VERIFIED\nchecks out"))
    verdict = convene_verification(ledger, _claim(dec.id), verifier,
                                   subject_id=dec.id, subject_kind="decision")
    assert verdict.status == VerdictStatus.VERIFIED
    verifs = [e for e in ledger.entries() if e.kind == "verification"]
    assert verifs, "convene must record the verdict so trust accrues"


def test_convene_runs_the_floor_before_spending_the_model(ledger, tmp_path):
    prov = Answer("VERIFIED\nwould pass")            # the model WOULD verify…
    verifier = ModelVerifier("verifier:haiku", prov)
    ghost = str(tmp_path / "nope.md")                # …but the floor refutes first
    claim = CompletionClaim(maker="witness:opus", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.FILE, ghost)])
    verdict = convene_verification(ledger, claim, verifier)
    assert verdict.status == VerdictStatus.REFUTED
    assert prov.calls == 0                           # floor caught it free


# ---- D35: REFUTED → contested + escalation, and NEVER a deletion ----

def test_refuted_verdict_contests_escalates_and_does_not_delete(ledger):
    dec = _decision(ledger)
    verifier = ModelVerifier("verifier:haiku",
                             Answer("REFUTED\nthe evidence does not establish Y"))
    verdict = convene_verification(ledger, _claim(dec.id), verifier,
                                   subject_id=dec.id, subject_kind="decision")
    assert verdict.status == VerdictStatus.REFUTED
    # a contested event names the decision it refutes, flagged for escalation
    items = contested_items(ledger)
    assert any(i["subject_id"] == dec.id and i["escalated"] for i in items)
    # append, never delete (D2): the decision is still active/current
    assert any(e.id == dec.id for e in ledger.active("decision"))


def test_contested_items_can_be_resolved_by_a_human(ledger):
    dec = _decision(ledger)
    verifier = ModelVerifier("verifier:haiku", Answer("REFUTED\nnope"))
    convene_verification(ledger, _claim(dec.id), verifier,
                         subject_id=dec.id, subject_kind="decision")
    item = contested_items(ledger)[0]
    resolve_contested(ledger, item["contested_id"], human="alex")
    assert contested_items(ledger) == []                 # cleared from the open queue
    assert len(contested_items(ledger, include_resolved=True)) == 1


# ---- D35: a persistent INSUFFICIENT is a capability gap, not a pass ----

def test_insufficient_is_a_capability_gap_not_a_verified_pass(ledger):
    dec = _decision(ledger)
    verifier = ModelVerifier("verifier:haiku", Answer("INSUFFICIENT\ncannot tell"))
    verdict = convene_verification(ledger, _claim(dec.id), verifier,
                                   subject_id=dec.id, subject_kind="decision")
    assert verdict.status == VerdictStatus.INSUFFICIENT
    assert verdict.status != VerdictStatus.VERIFIED       # never a silent pass
    gaps = [e for e in ledger.entries() if e.kind == "capability_gap"]
    assert gaps and gaps[0].body["subject_id"] == dec.id


def test_persistent_insufficient_is_flagged(ledger):
    dec = _decision(ledger)
    for _ in range(2):
        verifier = ModelVerifier("verifier:haiku", Answer("INSUFFICIENT\nstill cannot"))
        convene_verification(ledger, _claim(dec.id), verifier,
                             subject_id=dec.id, subject_kind="decision")
    gaps = [e for e in ledger.entries() if e.kind == "capability_gap"]
    assert gaps[-1].body["persistent"] is True


# ---- one canonical trust number, fed by the new verdicts ----

def test_trust_record_reflects_the_new_verdicts(ledger):
    dec = _decision(ledger)
    before = trust_record(ledger, "witness:opus")["total"]
    verifier = ModelVerifier("verifier:haiku", Answer("VERIFIED\nok"))
    convene_verification(ledger, _claim(dec.id), verifier,
                         subject_id=dec.id, subject_kind="decision")
    after = trust_record(ledger, "witness:opus")
    assert after["total"] > before
    assert after["verified"] >= 1


# ---- self-audit is not an audit, at the convene layer too (D4) ----

def test_convene_refuses_a_maker_verifying_itself(ledger):
    dec = _decision(ledger)
    verifier = ModelVerifier("witness:opus", Answer("VERIFIED\nof course"))   # == maker
    with pytest.raises(SelfCertificationError):
        convene_verification(ledger, _claim(dec.id), verifier)


# ---- D34: the reflection WRITE is independently verified too ----

def test_reflection_write_can_be_independently_verified(ledger):
    ledger.append("decision", "witness", {"decision_id": "d0", "subject": "x",
                                          "question_key": "x", "verdict": "Y"})
    verifier = ModelVerifier("verifier:haiku", Answer("VERIFIED\ngrounded"))
    r = ReflectionRitual(ledger, author="witness", write_verifier=verifier)
    r.run("s1", "kept the read current and put opinions on record", GOODLEARNED)
    verifs = [e for e in ledger.entries() if e.kind == "verification"]
    assert any(v.body.get("task", "").startswith("reflection write") for v in verifs)
