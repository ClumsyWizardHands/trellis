"""go-live hardening D — the verification-truth defects (Codex#7/FableG5b,
Codex#13/FableL3b, FableG5a). VERIFIED must mean an OUTCOME predicate held
(DECISIONS.md D25), not that a maker's own loop bookkeeping exists; a panel
must not manufacture quorum from duplicate/empty lenses or an out-of-range
quorum; and a PanelVerdict must satisfy the Verdict protocol without a maker
verifying itself."""

import pytest

from trellis.loops import LoopSpec, LoopRegistry, LoopRun
from trellis.panel import VerifierPanel, DEFAULT_LENSES
from trellis.providers.base import ProviderResponse
from trellis.verify import (Check, CompletionClaim, Evidence, EvidenceKind,
                            RuleVerifier, SelfCertificationError, Verdict,
                            VerdictStatus, record_verdict)


class _AllVerify:
    """A provider that always answers VERIFIED — enough to exercise the panel's
    aggregation without a network."""
    id = "scripted"

    def complete(self, system, messages, tools=None):
        return ProviderResponse(text="VERIFIED\nlooks right", model="scripted")


def _ended_loop(ledger, ground, actor="witness:a"):
    """Run a real loop to conclusion so a genuine maker-authored loop_run_end
    exists in the ledger (author=actor)."""
    spec = LoopSpec(name="witness", purpose="hold the team's context",
                    surface_key="k", stop_condition="the read is current")
    reg = LoopRegistry(ledger, ground)
    with LoopRun(spec, reg, actor=actor) as run:
        run.tick()
        run.ok("I assert success")
    return run.run_id


# ---- Codex#7 / FableG5b: maker-authored loop label must not launder VERIFIED ----

def test_makers_own_loop_label_does_not_launder_existence_into_verified(ledger, ground, tmp_path):
    run_id = _ended_loop(ledger, ground)
    # an unrelated artifact: an empty file that merely EXISTS, no outcome predicate
    f = tmp_path / "migration.sql"
    f.write_text("")
    claim = CompletionClaim(
        maker="witness:a", task="ran the production migration", summary="done",
        evidence=[Evidence(EvidenceKind.FILE, str(f))],
        loop_run_id=run_id)
    verdict = RuleVerifier("independent", ledger, ground).verify(claim)
    # the file exists and the loop concluded ok — but NOTHING tied to the claimed
    # artifact was actually checked, so this is preconditions, not truth (D25).
    assert verdict.status == VerdictStatus.PRECONDITIONS_PASSED
    assert verdict.status != VerdictStatus.VERIFIED


def test_a_real_artifact_predicate_still_earns_verified(ledger, ground, tmp_path):
    run_id = _ended_loop(ledger, ground)
    f = tmp_path / "migration.sql"
    f.write_text("CREATE TABLE trust (id INT);")
    claim = CompletionClaim(
        maker="witness:a", task="ran the migration", summary="done",
        evidence=[Evidence(EvidenceKind.FILE, str(f),
                           expect_contains="CREATE TABLE trust")],
        loop_run_id=run_id)
    verdict = RuleVerifier("independent", ledger, ground).verify(claim)
    assert verdict.status == VerdictStatus.VERIFIED


# ---- Codex#13 / FableL3b: no manufactured quorum ----

def test_duplicate_lenses_are_rejected():
    prov = _AllVerify()
    with pytest.raises(ValueError):
        VerifierPanel("panel:1", prov, lenses=("correctness", "correctness"), quorum=2)


def test_empty_panel_is_rejected():
    prov = _AllVerify()
    with pytest.raises(ValueError):
        VerifierPanel("panel:1", prov, lenses=())


def test_out_of_range_quorum_is_rejected():
    prov = _AllVerify()
    with pytest.raises(ValueError):
        VerifierPanel("panel:1", prov, lenses=DEFAULT_LENSES, quorum=-1)
    with pytest.raises(ValueError):
        VerifierPanel("panel:1", prov, lenses=DEFAULT_LENSES, quorum=0)
    with pytest.raises(ValueError):
        VerifierPanel("panel:1", prov, lenses=DEFAULT_LENSES, quorum=len(DEFAULT_LENSES) + 1)


def test_blank_lens_name_is_rejected():
    prov = _AllVerify()
    with pytest.raises(ValueError):
        VerifierPanel("panel:1", prov, lenses=("correctness", "  "))


# ---- FableG5a: PanelVerdict satisfies the Verdict protocol; maker != panel ----

def test_panel_verdict_records_without_attributeerror(ledger):
    prov = _AllVerify()
    panel = VerifierPanel("panel:1", prov, ledger=ledger)
    claim = CompletionClaim(maker="witness:a", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "some output")])
    pv = panel.verify(claim, record=False)
    # record_verdict reads verdict.verifier/status/checks/note — a PanelVerdict
    # wired into a documented seat must not crash here (FableG5a).
    record_verdict(ledger, claim, pv)
    recorded = [e for e in ledger.entries()
                if e.kind == "verification" and e.author == "panel:1"]
    assert recorded, "PanelVerdict did not record as a Verdict"
    assert recorded[0].body["status"] == pv.status.value


def test_panel_verdict_exposes_verdict_protocol_fields(ledger):
    prov = _AllVerify()
    panel = VerifierPanel("panel:1", prov, ledger=ledger)
    claim = CompletionClaim(maker="witness:a", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "some output")])
    pv = panel.verify(claim, record=False)
    assert pv.verifier == "panel:1"
    assert isinstance(pv.note, str) and pv.note
    assert all(isinstance(c, Check) for c in pv.checks)


def test_panel_named_as_the_maker_refuses_self_certification(ledger):
    prov = _AllVerify()
    panel = VerifierPanel("witness:a", prov, ledger=ledger)   # panel id == maker
    claim = CompletionClaim(maker="witness:a", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "some output")])
    with pytest.raises(SelfCertificationError):
        panel.verify(claim)
