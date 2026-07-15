"""Regressions from the independent fresh-eyes review (2026-07-15).

Doctrine applied to the builder: a self-audit is not an audit. An independent
verifier attacked the repo and found five live defects. Each is pinned here so
it can never quietly return. (DECISIONS.md D4, practiced on ourselves.)"""

from datetime import datetime, timedelta, timezone

import pytest

from trellis.decisions import Decision, IncompleteTriangulationError, POV, Verdict
from trellis.identity import same_identity
from trellis.passes import Pass, PassExchange, PassStatus, TurdDropError
from trellis.providers.mock import MockProvider
from trellis.stage import Outbox, StagedAction, UnapprovedFireError
from trellis.surfaces import ConversationKey, Surface, can_flow
from trellis.verify import (CompletionClaim, Evidence, EvidenceKind,
                            ModelVerifier, VerdictStatus)


def test_disguised_self_approval_is_refused(ledger):
    """REVIEW HIGH #1: 'WITNESS:A' and 'witness:a.' approved witness:a's own
    staged action. Identity comparison is normalized now."""
    box = Outbox(ledger)
    for disguise in ("WITNESS:A", "witness:a.", "  witness:a  ", "Witness:A!"):
        aid = box.stage(StagedAction("post", "#x", "content", created_by="witness:a"))
        with pytest.raises(UnapprovedFireError, match="human seat"):
            box.approve(aid, human=disguise)


def test_same_identity_normalization():
    assert same_identity("WITNESS:A", "witness:a")
    assert same_identity("witness:a.", " witness:a ")
    assert not same_identity("witness:a", "witness:b")
    assert not same_identity("", "")     # empty never matches anything


def test_naive_revisit_at_is_refused_at_mint(ground):
    """REVIEW HIGH #2: a naive revisit_at was accepted and later crashed
    hidden_nos() for the whole board."""
    povs = [POV("a", "1"), POV("b", "2"), POV("c", "3")]
    with pytest.raises(IncompleteTriangulationError, match="timezone-aware"):
        Decision("s", Verdict.T, "r", "w", "EMP:x", povs=povs, owner="alex",
                 missing="m", revisit_at=datetime(2026, 8, 1))  # naive!


def test_blank_model_verifier_reply_is_insufficient_not_a_crash():
    """REVIEW MEDIUM #3: '   ' and '\\n\\n' replies crashed the verifier."""
    claim = CompletionClaim(maker="m", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "x")])
    for blank in ("   ", "\n\n", ""):
        mock = MockProvider(id="seat")
        mock.enqueue_text(blank)
        verdict = ModelVerifier("checker", mock).verify(claim)
        assert verdict.status == VerdictStatus.INSUFFICIENT


def test_cli_and_dm_of_different_humans_never_cross():
    """REVIEW MEDIUM #4: CLI(alex) -> DM(brett) flowed because both rank 3."""
    cli_alex = ConversationKey("a", Surface.CLI, "cli", "alex")
    dm_brett = ConversationKey("a", Surface.DM, "d1", "brett")
    assert can_flow(cli_alex, dm_brett) is False
    assert can_flow(dm_brett, cli_alex) is False
    # same human's own surfaces still flow
    dm_alex = ConversationKey("a", Surface.DM, "d2", "alex")
    assert can_flow(cli_alex, dm_alex) is True


def test_turd_drop_cannot_enter_through_a_file(tmp_path, ground):
    """REVIEW LOW-MED #5: Pass.from_dict skipped validation — a malformed pass
    written by another tool slipped in from the synced exchange dir."""
    ex = PassExchange(tmp_path / "ex", ground)
    (tmp_path / "ex" / "pass-deadbeef.json").write_text(
        '{"id": "deadbeef", "sender": "x", "receiver": "atlas", '
        '"ask": "thoughts?", "context": "", "status": "sent", '
        '"comments": [], "history": []}')
    with pytest.raises(TurdDropError):
        ex.all()


def test_only_the_receiver_moves_a_pass_forward(ground):
    """REVIEW LOW #6: a sender walked its own pass to COMPLETED while
    impersonating the receiver. Lifecycle is enforced, not just recorded."""
    p = Pass("sender-a", "receiver-b",
             "verify the fixes landed and comment with evidence please",
             context="everything needed is in the ledger entries tagged verify")
    p.transition(PassStatus.SENT, "sender-a", ground)
    with pytest.raises(ValueError, match="only the receiver"):
        p.transition(PassStatus.RECEIVED, "sender-a", ground)   # impersonation
    p.transition(PassStatus.RECEIVED, "receiver-b", ground)
    p.transition(PassStatus.ACCEPTED, "RECEIVER-B", ground)     # same actor, disguised case: fine
    with pytest.raises(ValueError, match="only the receiver"):
        p.transition(PassStatus.COMPLETED, "sender-a", ground)
