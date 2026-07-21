"""Unforgivables #7, #8, #9 — turd-drops, boundary leaks, fake coordination.
Passes are typed files; privacy lives in the conversation key; nothing fires
unapproved."""

from datetime import timedelta

import pytest

from trellis.auth import Principal
from trellis.passes import (Pass, PassExchange, PassStatus, TurdDropError)
from trellis.stage import (ActionStatus, Outbox, StagedAction, UnapprovedFireError)
from trellis.surfaces import (ConversationKey, PrivacyBoundaryError, Surface,
                              ThreadRef, can_flow, declassify, flow_with_token,
                              guard_flow)


GOOD_CONTEXT = ("EAF power mapper v9 is at commit 41ab; Sarah flagged the QA "
                "button; the demo is Thursday. Everything you need is in "
                "projects/eaf-power-mapper-v9/README.")


def _key(surface, human="alex", scope="c1", agent="witness:a"):
    return ConversationKey(agent=agent, surface=surface, scope=scope, human=human)


# ----- passes ---------------------------------------------------------------

def test_turd_drop_is_a_type_error():
    """Peter, 2026-05-12: 'handed it off to you with no clear ask on it
    basically.' Now unrepresentable."""
    with pytest.raises(TurdDropError, match="clear ask"):
        Pass(sender="peter", receiver="atlas", ask="thoughts?", context=GOOD_CONTEXT)
    with pytest.raises(TurdDropError, match="context"):
        Pass(sender="peter", receiver="atlas",
             ask="review the mapper QA flow and stage a fix list by Friday",
             context="  ")


def test_pass_lifecycle_and_tracking(tmp_path, ground, clock):
    ex = PassExchange(tmp_path / "exchange", ground)
    p = Pass(sender="witness:a", receiver="moro",
             ask="verify the three attribution fixes landed and comment with evidence",
             context=GOOD_CONTEXT,
             deadline=ground.now() + timedelta(days=2))
    p.transition(PassStatus.SENT, "witness:a", ground)
    ex.save(p)

    assert [q.id for q in ex.inbox("moro")] == [p.id]
    assert [q.id for q in ex.outstanding("witness:a")] == [p.id]

    p.transition(PassStatus.RECEIVED, "moro", ground)   # the bouncing basketball
    p.comment("moro", "picked up; checking ledger entries now", ground)
    ex.save(p)

    clock.advance(days=3)
    assert [q.id for q in ex.overdue()] == [p.id]       # drops get noticed

    p2 = ex.load(p.id)
    assert p2.status == PassStatus.RECEIVED
    assert p2.history[0]["from"] == "staged"


def test_illegal_transitions_refused(ground):
    p = Pass("a", "b", "do the thing with the stuff by friday please",
             context=GOOD_CONTEXT)
    with pytest.raises(ValueError, match="illegal pass transition"):
        p.transition(PassStatus.COMPLETED, "a", ground)  # staged -> completed skips reception


def test_receiver_prompt_carries_the_thread(tmp_path, ground):
    ex = PassExchange(tmp_path / "ex", ground)
    p = Pass("a", "b", "summarize the decision lineage for Elise by Monday",
             context=GOOD_CONTEXT)
    p.comment("a", "start from the July 10 weekly close", ground)
    prompt = ex.receiver_prompt(p)
    assert "The ask" in prompt and "Thread so far" in prompt
    assert "July 10 weekly close" in prompt   # comments-as-protocol


# ----- privacy in the key -----------------------------------------------------

def test_dm_never_flows_to_channel_without_declassification():
    """Sarah, 2026-05-01: 'agents are still leaking private chief discussions
    into other channels.' The leak is now a raised exception."""
    dm = _key(Surface.DM, human="sarah")
    ch = _key(Surface.CHANNEL, human="")
    assert can_flow(dm, ch) is False
    with pytest.raises(PrivacyBoundaryError, match="declassification"):
        guard_flow(dm, ch)
    # and channel -> DM (toward more private) is fine
    assert can_flow(ch, dm) is True


def test_dms_of_different_humans_never_cross():
    assert can_flow(_key(Surface.DM, human="sarah"), _key(Surface.DM, human="brett")) is False


def test_declassification_requires_authenticated_human_and_reason(ledger):
    dm, ch = _key(Surface.DM, human="sarah"), _key(Surface.CHANNEL, human="")
    sarah = Principal(id="sarah", authenticated=True)
    # An agent naming itself — a bare string — is STRUCTURALLY refused (Codex #4):
    # declassification is a human-only authority, not a caller-supplied name.
    with pytest.raises(PrivacyBoundaryError, match="AUTHENTICATED human principal"):
        declassify(ledger, dm, ch, "witness-agent", reason="ok to share")
    # An unauthenticated principal (self-asserted, no verified secret) is refused too.
    with pytest.raises(PrivacyBoundaryError, match="authenticated"):
        declassify(ledger, dm, ch, Principal(id="sarah"), reason="ok to share")
    # A reason is still mandatory, even for an authenticated human.
    with pytest.raises(PrivacyBoundaryError, match="reason"):
        declassify(ledger, dm, ch, sarah, reason="  ")
    token = declassify(ledger, dm, ch, sarah,
                       reason="sarah asked for this excerpt to be posted")
    # DM → CHANNEL is a real declassification (toward more public); the token
    # redeems exactly once (SINGLE-USE), and never for a different flow.
    assert flow_with_token(ledger, dm, _key(Surface.CHANNEL, scope="other"), token) is False
    assert flow_with_token(ledger, dm, ch, token) is True
    assert flow_with_token(ledger, dm, ch, token) is False   # spent — one-shot, not standing


def test_thread_is_modeled_with_parent(ledger):
    t = ThreadRef(id="th9", parent_channel="c1", parent_message="m42")
    k = ConversationKey("witness:a", Surface.THREAD, "c1", "brett", thread=t)
    assert "th9" in k.storage_key()
    k2 = ConversationKey("witness:a", Surface.THREAD, "c1", "brett")
    assert k.storage_key() != k2.storage_key()   # distinct threads never conflate


# ----- stage, don't fire -------------------------------------------------------

def test_nothing_fires_unapproved(ledger):
    box = Outbox(ledger)
    fired = []
    aid = box.stage(StagedAction(kind="discord_post", target="#general",
                                 content="digest...", created_by="witness:a"))
    with pytest.raises(UnapprovedFireError, match="human"):
        box.fire(aid, executor=lambda a: fired.append(a))
    assert fired == []


def test_agent_cannot_approve_its_own_action(ledger):
    box = Outbox(ledger)
    aid = box.stage(StagedAction("discord_post", "#general", "x", created_by="witness:a"))
    with pytest.raises(UnapprovedFireError, match="human seat"):
        box.approve(aid, human="witness:a")


def test_approved_action_fires_and_everything_is_ledgered(ledger):
    box = Outbox(ledger)
    fired = []
    aid = box.stage(StagedAction("discord_post", "#general", "the digest",
                                 created_by="witness:a"))
    box.approve(aid, human="alex")
    box.fire(aid, executor=lambda a: fired.append(a.content))
    assert fired == ["the digest"]
    events = [e.body.get("event") or e.body.get("status")
              for e in ledger.entries() if e.kind == "staged_action"]
    # a `firing` INTENT is recorded before the side effect (D26 durability), so a
    # crash between intent and outcome is recoverable and can't double-fire
    assert events == ["staged", "approved", "firing", "fired"]


def test_denial_is_recorded_with_reason(ledger):
    box = Outbox(ledger)
    aid = box.stage(StagedAction("email_send", "ceo@cf.org", "90% draft",
                                 created_by="witness:a"))
    box.deny(aid, human="peter", reason="can't send 90% to a CEO")
    denials = [e for e in ledger.entries()
               if e.kind == "staged_action" and e.body.get("event") == "denied"]
    assert denials[0].body["reason"] == "can't send 90% to a CEO"
