"""Follow-up hardening on the D38 send path found by the security adversary:
(1) an armed executor holding the ledger refuses to send an UNAPPROVED action even
    when called directly (not through Outbox.fire) — defense in depth on refusal #5;
(2) the act-surface resolver is ONE canonical function across stage/executor/gateway,
    so a legitimately allowlisted threaded reply (channel⇒threads, D32) is not
    wrongly refused, and the surface guarded is exactly the surface sent."""

import pytest

from trellis.clock import TimeGround
from trellis.ledger import Ledger
from trellis.isolation import Isolation, SurfaceAllowlist, AgentIdentity
from trellis.stage import Outbox, StagedAction, act_surface_id
from trellis.executor import DiscordExecutor, UnapprovedSendError
from trellis.surfaces import ConversationKey, Surface, ThreadRef


def _iso(act):
    return Isolation(identity=AgentIdentity(), allow=SurfaceAllowlist(read=frozenset(), act=frozenset(act)))


def _mk_ledger(tmp_path):
    return Ledger(str(tmp_path / "l.jsonl"), TimeGround())


def test_armed_executor_refuses_an_unapproved_action_called_directly(tmp_path):
    led = _mk_ledger(tmp_path)
    box = Outbox(led)
    aid = box.stage(StagedAction(kind="discord_post", target="#trellis",
                                 content="hi", created_by="witness:a"))
    sent = []
    ex = DiscordExecutor(_iso(["#trellis"]), send_fn=lambda a: sent.append(a), ledger=led)
    # staged, NOT approved — a direct execute() must refuse (defense in depth)
    with pytest.raises(UnapprovedSendError):
        ex.execute(box.get(aid))
    assert sent == []
    # once a human approves, the same direct execute() may send
    box.approve(aid, human="alex")
    ex.execute(box.get(aid))
    assert len(sent) == 1


def test_one_canonical_act_surface_resolver_uses_parent_channel():
    t = ThreadRef(id="th-dynamic-999", parent_channel="#trellis", parent_message="m1")
    dest = ConversationKey("trellis", Surface.THREAD, "#trellis", "", thread=t)
    action = StagedAction(kind="discord_post", target="#trellis", content="x",
                          created_by="witness:a", destination=dest)
    # the thread's PARENT CHANNEL governs the act guard, never the dynamic thread id
    assert act_surface_id(action) == "#trellis"
    # a threaded reply under an allowlisted channel is NOT refused (D32 on the act side)
    ex = DiscordExecutor(_iso(["#trellis"]), send_fn=lambda a: "ok")
    assert ex.execute(action)["status"] == "delivered"
