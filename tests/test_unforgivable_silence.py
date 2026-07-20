"""Unforgivables #1, #2, #10 — silent failure, overconfident self-grading,
unverifiable completion. Loops always end in a typed outcome; makers never
verify themselves; claims carry openable evidence."""

import pytest

from trellis.loops import (BlockKind, LoopBudgetExceeded, LoopRegistry, LoopRun,
                           LoopSpec, LoopState, Outcome)
from trellis.verify import (Check, CompletionClaim, Evidence, EvidenceKind,
                            ModelVerifier, RuleVerifier, SelfCertificationError,
                            VerdictStatus, record_verdict, trust_record)
from trellis.providers.mock import MockProvider


def spec(name="test.loop"):
    return LoopSpec(name=name, purpose="test", surface_key="k", max_turns=3,
                    stop_condition="done when done")


def _last_end(ledger):
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    return ends[-1]


# ----- silence is impossible ---------------------------------------------------

def test_unbounded_loops_are_unrepresentable():
    with pytest.raises(ValueError, match="max_turns"):
        LoopSpec(name="x", purpose="p", surface_key="k", max_turns=0,
                 stop_condition="s")
    with pytest.raises(ValueError, match="stop condition"):
        LoopSpec(name="x", purpose="p", surface_key="k", max_turns=3,
                 stop_condition="  ")


def test_run_that_says_nothing_is_a_protocol_violation(ledger):
    """Clare, 2026-06-11: 'Claude failed silently and has been spinning for
    four hours.' A run that exits without reporting gets reported ON."""
    reg = LoopRegistry(ledger)
    with LoopRun(spec(), reg, actor="witness:a") as run:
        run.tick()
        # ...does work, reports nothing, wanders off...
    e = _last_end(ledger)
    assert e.body["outcome"] == Outcome.PROTOCOL_VIOLATION.value
    assert "failed silently" in e.body["reason"]


def test_crash_mid_run_still_writes_outcome_with_traceback(ledger):
    reg = LoopRegistry(ledger)
    with pytest.raises(RuntimeError):
        with LoopRun(spec(), reg, actor="witness:a") as run:
            run.tick()
            raise RuntimeError("session death")
    e = _last_end(ledger)
    assert e.body["outcome"] == Outcome.PROTOCOL_VIOLATION.value
    assert "session death" in e.body["exception"]
    assert "traceback" in e.body


def test_budget_exhaustion_is_a_typed_outcome_not_a_hang(ledger):
    reg = LoopRegistry(ledger)
    with LoopRun(spec(), reg, actor="w") as run:
        while run.tick():
            pass  # tries to run forever; budget says no
    assert _last_end(ledger).body["outcome"] == Outcome.BUDGET_EXCEEDED.value


def test_nothing_new_is_loud_and_two_make_dormant(ledger):
    reg = LoopRegistry(ledger)
    s = spec("quiet.loop")
    reg.register(s, "alex")
    for _ in range(2):
        with LoopRun(s, reg, actor="w") as run:
            run.tick()
            run.nothing_new(checked=["#general", "#chiefs"])
    assert reg.state("quiet.loop") == LoopState.DORMANT


def test_two_blocks_route_to_triage_not_thrash(ledger):
    reg = LoopRegistry(ledger)
    s = spec("blocked.loop")
    reg.register(s, "alex")
    for _ in range(2):
        with LoopRun(s, reg, actor="w") as run:
            run.tick()
            run.blocked(BlockKind.NEEDS_INPUT, on="pricing canon from Brett")
    assert reg.state("blocked.loop") == LoopState.TRIAGE


def test_never_ran_is_a_finding(ledger):
    reg = LoopRegistry(ledger)
    reg.register(spec("ghost.loop"), "alex")
    report = reg.health_report()
    assert report[0]["last_outcome"] == "NEVER RAN"


# ----- self-certification is impossible -----------------------------------------

def test_maker_cannot_verify_own_claim(ledger):
    claim = CompletionClaim(maker="witness:a", task="t", summary="done",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "log text")])
    v = RuleVerifier("witness:a", ledger)   # same identity
    with pytest.raises(SelfCertificationError, match="self-audit is not an audit"):
        v.verify(claim)


def test_claims_require_evidence():
    with pytest.raises(ValueError, match="evidence"):
        CompletionClaim(maker="m", task="t", summary="it works it works", evidence=[])


def test_rule_verifier_refutes_missing_files(ledger, tmp_path):
    real = tmp_path / "real.md"; real.write_text("x")
    claim = CompletionClaim(
        maker="witness:a", task="write the read", summary="wrote two files",
        evidence=[Evidence(EvidenceKind.FILE, str(real)),
                  Evidence(EvidenceKind.FILE, str(tmp_path / "ghost.md"))])
    verdict = RuleVerifier("checker:1", ledger).verify(claim)
    assert verdict.status == VerdictStatus.REFUTED
    failed = [c for c in verdict.checks if not c.passed]
    assert "ghost.md" in failed[0].name


def test_rule_verifier_checks_loop_run_reality(ledger):
    """Unforgivable #10: no deterministic proof a sub-agent did the thing.
    Claims referencing runs that never concluded are refuted."""
    claim = CompletionClaim(maker="w", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "text")],
                            loop_run_id="nonexistent-run")
    verdict = RuleVerifier("checker:1", ledger).verify(claim)
    assert verdict.status == VerdictStatus.REFUTED
    assert any("never concluded" in c.detail for c in verdict.checks)


def test_model_verifier_unparseable_means_insufficient_never_verified(ledger):
    mock = MockProvider(id="haiku-seat")
    mock.enqueue_text("well, it seems plausible that the work was done nicely")
    claim = CompletionClaim(maker="w", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "text")])
    verdict = ModelVerifier("checker:model", mock).verify(claim)
    assert verdict.status == VerdictStatus.INSUFFICIENT   # no benefit of the doubt


def test_trust_compounds_in_the_ledger(ledger, tmp_path):
    """Trust compounds per maker — and counts HONESTLY (Codex Critical 4):
    existence-only evidence is PRECONDITIONS_PASSED, not VERIFIED; only an OUTCOME
    predicate that holds earns a verified verdict that raises the trust ratio."""
    f = tmp_path / "ev.md"; f.write_text("the funder confirmed on Friday")
    checker = RuleVerifier("checker:1", ledger)
    # 3 existence-only claims → preconditions passed, NOT verified (no outcome checked)
    for _ in range(3):
        c = CompletionClaim(maker="witness:a", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.FILE, str(f))])
        record_verdict(ledger, c, checker.verify(c))
    # a missing file → refuted
    bad = CompletionClaim(maker="witness:a", task="t", summary="s",
                          evidence=[Evidence(EvidenceKind.FILE, str(tmp_path / "no.md"))])
    record_verdict(ledger, bad, checker.verify(bad))
    # an OUTCOME predicate that holds → a real verified
    good = CompletionClaim(maker="witness:a", task="t", summary="s",
                           evidence=[Evidence(EvidenceKind.FILE, str(f),
                                              expect_contains="funder confirmed")])
    record_verdict(ledger, good, checker.verify(good))
    tr = trust_record(ledger, "witness:a")
    assert tr["total"] == 5
    assert tr["preconditions_passed"] == 3   # existence alone no longer inflates trust
    assert tr["verified"] == 1               # only the real outcome check
    assert tr["refuted"] == 1
    assert tr["verified_ratio"] == 0.2       # 1 of 5, not 4 of 5
