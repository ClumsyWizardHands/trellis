"""The haiku verifier panel — deterministic tests via scripted providers.
Proves the quorum logic without spending a token, so the panel's judgment can
itself be trusted."""

import pytest

from trellis.panel import VerifierPanel, panel_as_subagent_specs, DEFAULT_LENSES
from trellis.verify import (CompletionClaim, Evidence, EvidenceKind, RuleVerifier,
                            VerdictStatus)
from trellis.providers.base import ProviderResponse
from trellis.providers.mock import MockProvider


class ScriptedByLens:
    """A provider that answers based on the lens named in the system prompt —
    lets us script per-lens disagreement deterministically."""
    def __init__(self, answers: dict[str, str]):
        self.id = "scripted"
        self.answers = answers
        self.calls = []

    def complete(self, system, messages, tools=None):
        self.calls.append(system)
        lens = "general"
        for k in DEFAULT_LENSES:
            if f"YOUR LENS ({k})" in system:
                lens = k
        return ProviderResponse(text=self.answers.get(lens, "INSUFFICIENT\nno basis"),
                                model="scripted")


def claim(maker="witness:a"):
    return CompletionClaim(maker=maker, task="t", summary="s",
                           evidence=[Evidence(EvidenceKind.OUTPUT, "some output")])


def test_all_lenses_verify_meets_quorum(ledger):
    prov = ScriptedByLens({l: "VERIFIED\nlooks right" for l in DEFAULT_LENSES})
    panel = VerifierPanel("panel:1", prov, ledger=ledger)
    pv = panel.verify(claim())
    assert pv.status == VerdictStatus.VERIFIED
    assert pv.verified_count == 4 and pv.refuted_count == 0
    assert pv.confirmed


def test_any_single_refutation_sinks_the_claim(ledger):
    prov = ScriptedByLens({"correctness": "VERIFIED\nok", "freshness": "VERIFIED\nok",
                           "attribution": "REFUTED\nmisattributed", "reproduce": "VERIFIED\nok"})
    panel = VerifierPanel("panel:1", prov, ledger=ledger)
    pv = panel.verify(claim())
    assert pv.status == VerdictStatus.REFUTED   # 3 verified, but one refute wins
    assert "any refutation sinks" in pv.rationale


def test_below_quorum_is_insufficient_not_verified(ledger):
    prov = ScriptedByLens({"correctness": "VERIFIED\nok", "freshness": "INSUFFICIENT\nunsure",
                           "attribution": "INSUFFICIENT\nunsure", "reproduce": "INSUFFICIENT\nunsure"})
    panel = VerifierPanel("panel:1", prov, ledger=ledger)
    pv = panel.verify(claim())
    assert pv.status == VerdictStatus.INSUFFICIENT   # 1 verified < quorum 3
    assert not pv.confirmed


def test_deterministic_floor_short_circuits_before_spending_models(ledger, tmp_path):
    prov = ScriptedByLens({l: "VERIFIED\nok" for l in DEFAULT_LENSES})
    floor = RuleVerifier("panel:1:floor", ledger)
    panel = VerifierPanel("panel:1", prov, ledger=ledger, rule_verifier=floor)
    bad = CompletionClaim(maker="witness:a", task="t", summary="s",
                          evidence=[Evidence(EvidenceKind.FILE, str(tmp_path / "ghost.md"))])
    pv = panel.verify(bad)
    assert pv.status == VerdictStatus.REFUTED
    assert prov.calls == []   # no model was consulted — the floor caught it free
    assert "floor refuted" in pv.rationale


def test_no_lens_can_self_certify_the_maker(ledger):
    prov = ScriptedByLens({l: "VERIFIED\nok" for l in DEFAULT_LENSES})
    # a maker whose id collides with a lens verifier id is still safe because
    # lens ids are namespaced under the panel; but verify independence anyway
    from trellis.verify import SelfCertificationError
    panel = VerifierPanel("witness:a", prov, ledger=ledger)  # panel shares maker name
    with pytest.raises(SelfCertificationError):
        panel.verify(claim(maker="witness:a:correctness"))  # exact collision refused


def test_lens_verdicts_compound_in_ledger(ledger):
    prov = ScriptedByLens({l: "VERIFIED\nok" for l in DEFAULT_LENSES})
    panel = VerifierPanel("panel:1", prov, ledger=ledger)
    panel.verify(claim())
    verifications = [e for e in ledger.entries() if e.kind == "verification"]
    panels = [e for e in ledger.entries() if e.kind == "panel_verdict"]
    assert len(verifications) == 4          # one per lens
    assert len(panels) == 1
    assert panels[0].body["status"] == "verified"


def test_quorum_is_configurable(ledger):
    prov = ScriptedByLens({"correctness": "VERIFIED\nok", "freshness": "VERIFIED\nok",
                           "attribution": "INSUFFICIENT\n?", "reproduce": "INSUFFICIENT\n?"})
    strict = VerifierPanel("p", prov, quorum=4, ledger=ledger)
    assert strict.verify(claim()).status == VerdictStatus.INSUFFICIENT
    prov2 = ScriptedByLens({"correctness": "VERIFIED\nok", "freshness": "VERIFIED\nok",
                            "attribution": "INSUFFICIENT\n?", "reproduce": "INSUFFICIENT\n?"})
    lenient = VerifierPanel("p", prov2, quorum=2, ledger=ledger)
    assert lenient.verify(claim()).status == VerdictStatus.VERIFIED


def test_subagent_specs_are_readonly_haiku_per_lens():
    specs = panel_as_subagent_specs()
    assert len(specs) == 4
    for s in specs:
        assert s["model"] == "claude-haiku-4-5"
        assert set(s["tools"]) <= {"Read", "Grep", "Glob"}   # cannot mutate evidence
        assert "REFUTE" in s["prompt"]
