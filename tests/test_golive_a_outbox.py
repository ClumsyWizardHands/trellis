"""Go-live hardening (lane A): the durable Outbox authorization defects.

Every fire() authorization is re-derived from the LEDGER under the fire lock —
never from a stale in-memory cache — so a denial, a failed approval append, or a
decided-then-resurrected action can never reach the world. reconcile() carries the
same authenticated-human + maker!=reconciler gate as approval. Durable
reconstruction keeps the full structured destination and the approving actor.

Findings pinned:
  Codex#1  — a stale Outbox fires after another process recorded a denial
  Codex#2  — a failed approval append leaves the action fireable with no durable yes
  Codex#3  — the staging agent reconciles its own ambiguous send (maker==reconciler)
  Codex#16 — reconstruction drops destination and approved_by
  FableG8  — deny -> approve resurrection (no lifecycle-state gate)
"""

import pytest

from trellis.ledger import Ledger
from trellis.stage import (ActionStatus, DoubleFireError, FireOutcomeUnknown,
                           Outbox, StagedAction, UnapprovedFireError)
from trellis.surfaces import ConversationKey, Surface, ThreadRef


def _box(path, ground):
    return Outbox(Ledger(path, ground), ground)


# --- Codex#1 : a stale cache must never fire past a durable denial ------------

def test_stale_outbox_cannot_fire_after_another_process_denied(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    seed = Outbox(Ledger(path, ground), ground)
    aid = seed.stage(StagedAction("discord_post", "#c", "m", created_by="witness"))
    # two independent process views over the SAME ledger, both built while STAGED
    a = _box(path, ground)
    b = _box(path, ground)
    a.approve(aid, human="alice")
    b.deny(aid, human="bob", reason="do not send")
    # `a` still holds a cached APPROVED — but the ledger's latest transition is a
    # denial. fire() must re-derive from the ledger and REFUSE.
    fired = []
    with pytest.raises(UnapprovedFireError):
        a.fire(aid, executor=lambda x: fired.append(x.id))
    assert fired == []


# --- Codex#2 : a failed approval append must not leave a fireable action ------

def test_failed_approval_append_is_not_fireable(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("discord_post", "#c", "m", created_by="witness"))

    real_append = box.ledger.append

    def boom(*args, **kwargs):
        if kwargs.get("body", {}).get("event") == "approved":
            raise OSError("disk full")
        return real_append(*args, **kwargs)

    box.ledger.append = boom
    with pytest.raises(OSError):
        box.approve(aid, human="alice")
    box.ledger.append = real_append
    # zero durable approval events exist → the action is NOT fireable, and the
    # cache was rolled back rather than left APPROVED.
    assert box.get(aid).status == ActionStatus.STAGED
    fired = []
    with pytest.raises(UnapprovedFireError):
        box.fire(aid, executor=lambda x: fired.append(x.id))
    assert fired == []


# --- Codex#3 : the maker cannot reconcile its own ambiguous send --------------

def test_maker_cannot_reconcile_own_unknown(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("discord_post", "#c", "m", created_by="witness"))
    box.approve(aid, human="alice")
    sent = []

    def flaky(a):
        sent.append("x")
        raise TimeoutError("remote slow")

    with pytest.raises(FireOutcomeUnknown):
        box.fire(aid, executor=flaky)
    assert box.get(aid).status == ActionStatus.UNKNOWN
    # the staging agent ("witness") is NOT an independent human seat — refused,
    # so a retry can never double-send.
    with pytest.raises(UnapprovedFireError):
        box.reconcile(aid, human="witness", fired=False)
    assert box.get(aid).status == ActionStatus.UNKNOWN
    # a homoglyph of the maker is refused too (ASCII-identity gate)
    with pytest.raises(UnapprovedFireError):
        box.reconcile(aid, human="witnеss", fired=False)  # Cyrillic e
    # an independent human resolves it
    box.reconcile(aid, human="alice", fired=False)
    assert box.get(aid).status == ActionStatus.APPROVED


# --- Codex#16 : reconstruction keeps destination and the approving actor ------

def test_reconstruction_keeps_destination_and_approver(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    dest = ConversationKey(
        agent="witness", surface=Surface.DM, scope="dm-42", human="alex",
        thread=ThreadRef(id="t1", parent_channel="#c", parent_message="m9"))
    aid = box.stage(StagedAction("discord_post", "dm-42", "hi", created_by="witness",
                                 destination=dest))
    box.approve(aid, human="alex")
    # a fresh process reconstructs from the ledger alone
    box2 = _box(path, ground)
    a = box2.get(aid)
    assert a.destination == dest                 # full structured destination survives
    assert a.approved_by == "alex"               # the approving actor is retained


def test_web_style_approval_reconstructs_the_approver_from_the_author(tmp_path, ground):
    """A web `approved` event carries no `approved_by` field — the approver is the
    ledger author. Reconstruction must not drop it to None (Codex#16)."""
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("email_send", "x@y", "draft", created_by="witness"))
    Ledger(path, ground).append(
        kind="staged_action", author="alex",
        body={"action_id": aid, "event": "approved", "status": "approved", "via": "web-ui"},
        tags=("outbox", "approved"))
    box2 = _box(path, ground)
    a = box2.get(aid)
    assert a.status == ActionStatus.APPROVED
    assert a.approved_by == "alex"


# --- FableG8 : a denied action can never be resurrected to approved -----------

def test_denied_cannot_be_reapproved_or_fired(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("discord_post", "#c", "m", created_by="witness"))
    box.deny(aid, human="alice", reason="no")
    # the resurrection: re-approve a denied action → refused (lifecycle-state gate)
    with pytest.raises(UnapprovedFireError):
        box.approve(aid, human="alice")
    assert box.get(aid).status == ActionStatus.DENIED
    fired = []
    with pytest.raises(UnapprovedFireError):
        box.fire(aid, executor=lambda x: fired.append(x.id))
    assert fired == []


def test_fired_cannot_be_reapproved(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("discord_post", "#c", "m", created_by="witness"))
    box.approve(aid, human="alice")
    box.fire(aid, executor=lambda x: None)
    assert box.get(aid).status == ActionStatus.FIRED
    with pytest.raises(UnapprovedFireError):
        box.approve(aid, human="alice")           # a fired action is not re-approved
