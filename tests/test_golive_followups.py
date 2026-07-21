"""Follow-up hardening: holes the Phase-1 verifiers found that no single
file-owner could close from inside its own boundary.

  * the SYSTEMIC homoglyph-independence hole (identity.is_independent) — a maker
    forging a verification/ratification under a Cyrillic homoglyph of its own id
    used to read as a distinct, independent party across selfimprove / reflect /
    the web ratify seat (verify.py was already safe via require_identity);
  * the deny -> approve resurrection through the web approval seat;
  * the LEDGER-predicate laundering V3 (a predicate against the maker's own
    loop bookkeeping must not earn VERIFIED).
"""

from datetime import timedelta

import pytest

from trellis.clock import TimeGround
from trellis.identity import InvalidIdentityError, is_independent, require_identity
from trellis.ledger import Ledger
from trellis.verify import CompletionClaim, Evidence, EvidenceKind, RuleVerifier, VerdictStatus


HOMO_MAKER = "witnеss"   # Cyrillic 'е' — a homoglyph of the ascii "witness"


def test_is_independent_rejects_homoglyph_of_the_maker():
    # the ascii maker and a Cyrillic-homoglyph author are NOT independent parties
    assert is_independent("witness", HOMO_MAKER) is False
    # nor is the maker independent of itself, or of a case/space disguise
    assert is_independent("witness", "witness") is False
    assert is_independent("witness", " WITNESS ") is False
    # a genuinely distinct, valid ascii id IS independent
    assert is_independent("witness", "haiku") is True
    # a blank / unusable author is never independent (fail-closed)
    assert is_independent("witness", "") is False
    assert is_independent("witness", "  ") is False


def test_homoglyph_verifier_cannot_pass_the_selfimprove_independence_gate():
    from trellis.selfimprove import _has_independent_verified_verdict
    g = TimeGround()
    led = _mem_ledger(g)
    # the maker forges a "verification" for its own claim under a homoglyph id
    led.append(kind="verification", author=HOMO_MAKER,
               body={"claim_id": "c1", "status": "verified"})
    # the forged verdict must NOT count as independent for maker "witness"
    assert _has_independent_verified_verdict(led, "c1", "witness") is False
    # a real independent verifier does count
    led.append(kind="verification", author="haiku",
               body={"claim_id": "c1", "status": "verified"})
    assert _has_independent_verified_verdict(led, "c1", "witness") is True


def test_ledger_predicate_against_own_loop_bookkeeping_is_not_an_outcome():
    g = TimeGround()
    led = _mem_ledger(g)
    run = led.append(kind="loop_run_end", author="witness",
                     body={"run_id": "r1", "outcome": "ok"})
    # a claim for UNRELATED work, "proven" only by expect_kind against the
    # maker's own loop_run_end, must NOT reach VERIFIED (FableG5b V3 / D25).
    claim = CompletionClaim(
        maker="witness", task="migrate the database",
        summary="migrated the whole database",
        evidence=[Evidence(kind=EvidenceKind.LEDGER, ref=run.id, expect_kind="loop_run_end")],
        loop_run_id=None)
    v = RuleVerifier("haiku", led).verify(claim)
    assert v.status is not VerdictStatus.VERIFIED


def _mem_ledger(ground):
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    return Ledger(path, ground=ground)
