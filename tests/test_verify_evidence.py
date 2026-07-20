"""Evidence-aware verification (Codex Critical 4).

Pins: a deterministic pass means the OUTCOME held, not that a file exists. An
existence-only claim is PRECONDITIONS_PASSED (not VERIFIED); an unopenable
external-only claim is INSUFFICIENT (the reproduced bug); an outcome predicate
(hash / contains / kind) that holds earns VERIFIED, and one that fails REFUTES."""

import hashlib

import pytest

from trellis.verify import (CompletionClaim, Evidence, EvidenceKind, RuleVerifier,
                            VerdictStatus)


def _claim(evidence, maker="witness:a"):
    return CompletionClaim(maker=maker, task="t", summary="s", evidence=evidence)


def test_existence_only_is_preconditions_not_verified(ledger, tmp_path):
    f = tmp_path / "read.md"; f.write_text("the read")
    v = RuleVerifier("checker:1", ledger).verify(_claim([Evidence(EvidenceKind.FILE, str(f))]))
    assert v.status == VerdictStatus.PRECONDITIONS_PASSED     # openable, but no outcome checked


def test_external_only_is_insufficient_not_verified(ledger):
    """The reproduced bug: a claim backed only by an unopenable external used to
    reach VERIFIED. It must be INSUFFICIENT — nothing was confirmable."""
    v = RuleVerifier("checker:1", ledger).verify(
        _claim([Evidence(EvidenceKind.EXTERNAL, "opaque://uncheckable")]))
    assert v.status == VerdictStatus.INSUFFICIENT


def test_file_contains_predicate_earns_verified(ledger, tmp_path):
    f = tmp_path / "read.md"; f.write_text("the funder confirmed on Friday")
    v = RuleVerifier("checker:1", ledger).verify(
        _claim([Evidence(EvidenceKind.FILE, str(f), expect_contains="funder confirmed")]))
    assert v.status == VerdictStatus.VERIFIED


def test_file_contains_predicate_that_fails_refutes(ledger, tmp_path):
    f = tmp_path / "read.md"; f.write_text("the funder did NOT confirm")
    v = RuleVerifier("checker:1", ledger).verify(
        _claim([Evidence(EvidenceKind.FILE, str(f), expect_contains="funder confirmed")]))
    assert v.status == VerdictStatus.REFUTED


def test_file_hash_predicate(ledger, tmp_path):
    f = tmp_path / "read.md"; content = "exact bytes"; f.write_text(content)
    h = hashlib.sha256(content.encode()).hexdigest()
    v = RuleVerifier("checker:1", ledger).verify(
        _claim([Evidence(EvidenceKind.FILE, str(f), expect_hash=h)]))
    assert v.status == VerdictStatus.VERIFIED
    bad = RuleVerifier("checker:1", ledger).verify(
        _claim([Evidence(EvidenceKind.FILE, str(f), expect_hash="0" * 64)]))
    assert bad.status == VerdictStatus.REFUTED


def test_ledger_expect_kind_is_an_outcome_check(ledger):
    e = ledger.append("decision", "witness:a", {"decision_id": "d1", "subject": "x"})
    ok = RuleVerifier("checker:1", ledger).verify(
        _claim([Evidence(EvidenceKind.LEDGER, e.id, expect_kind="decision")]))
    assert ok.status == VerdictStatus.VERIFIED
    wrong = RuleVerifier("checker:1", ledger).verify(
        _claim([Evidence(EvidenceKind.LEDGER, e.id, expect_kind="verification")]))
    assert wrong.status == VerdictStatus.REFUTED


def test_external_alongside_real_evidence_does_not_refute(ledger, tmp_path):
    """An unopenable external is unconfirmable, NOT a failure — a real file beside
    it should not be refuted by it."""
    f = tmp_path / "r.md"; f.write_text("x")
    v = RuleVerifier("checker:1", ledger).verify(_claim([
        Evidence(EvidenceKind.FILE, str(f)),
        Evidence(EvidenceKind.EXTERNAL, "opaque://x")]))
    assert v.status == VerdictStatus.PRECONDITIONS_PASSED    # openable file, no outcome, external noted


def test_missing_file_still_refutes(ledger, tmp_path):
    v = RuleVerifier("checker:1", ledger).verify(
        _claim([Evidence(EvidenceKind.FILE, str(tmp_path / "nope.md"))]))
    assert v.status == VerdictStatus.REFUTED
