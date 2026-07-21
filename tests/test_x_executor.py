"""D38 executor: the Discord send path + the in-Discord approval gesture.

The ratified safety model (DECISIONS.md D38, D30, D26, refusal #5) must hold end
to end here:

  * The executor CAN post, but has NO path to the world that bypasses
    `Outbox.fire`'s ledger-authorized, human-approved, maker!=approver gate. It
    only ever runs as the callable `fire()` invokes AFTER a durable human yes.
  * ISOLATION (D30): every send calls `iso.allow.guard_act(surface_id)` BEFORE any
    network call. A non-allowlisted surface raises `SurfaceNotAllowed` and NOTHING
    is sent — sending to the wrong place is irreversible.
  * The Discord API send is INJECTED (`send_fn`). Tests pass a MOCK; the executor
    NEVER hits the network by default. An un-armed executor (no transport) refuses
    rather than silently no-op'ing.
  * An ambiguous send (a timeout after a partial send) is SURFACED, never swallowed
    into a false success — so `fire()` lands the action `unknown` for a human
    reconcile (D26).
  * Staging (stage.py) also guards the act surface when an Isolation is supplied —
    a wrong-surface action is refused before it can ever be approved (guard at
    STAGE and at FIRE, D38).
"""

import pytest

from trellis.executor import DiscordExecutor, ExecutorNotArmed, _act_surface_id
from trellis.isolation import Isolation, SurfaceAllowlist, SurfaceNotAllowed
from trellis.ledger import Ledger
from trellis.stage import (ActionStatus, FireOutcomeUnknown, Outbox,
                           StagedAction)
from trellis.surfaces import ConversationKey, Surface, ThreadRef


def _iso(act=("#trellis",), read=()):
    return Isolation(allow=SurfaceAllowlist(read=frozenset(read), act=frozenset(act)))


def _box(path, ground, iso=None):
    return Outbox(Ledger(path, ground), ground, iso=iso)


# --- guard_act blocks a send to a non-allowlisted surface --------------------

def test_guard_act_blocks_non_allowlisted_surface_no_send(ground):
    """The executor refuses LOUDLY (SurfaceNotAllowed) before any send_fn call
    when the target surface is not on the ACT allowlist."""
    calls = []
    ex = DiscordExecutor(_iso(act=("#trellis",)), send_fn=lambda a: calls.append(a))
    action = StagedAction("discord_post", "#other-agent", "hi", created_by="trellis")
    with pytest.raises(SurfaceNotAllowed):
        ex.execute(action)
    assert calls == []            # nothing was sent — guard fired before the transport


# --- an approved action on an allowlisted surface sends exactly once ---------

def test_approved_allowlisted_action_sends_exactly_once(tmp_path, ground):
    """Through the full ratified path: stage -> human approve -> fire. The send
    happens exactly once, the action lands FIRED, and the mock transport was the
    only thing that touched 'the world'."""
    path = tmp_path / "l.jsonl"
    iso = _iso(act=("#trellis",))
    box = _box(path, ground, iso=iso)
    sent = []
    ex = DiscordExecutor(iso, send_fn=lambda a: sent.append(a.id) or {"id": "m-99"})
    aid = box.stage(StagedAction("discord_post", "#trellis", "hello", created_by="trellis"))
    box.approve(aid, human="alex")
    box.fire(aid, executor=ex.execute)
    assert box.get(aid).status == ActionStatus.FIRED
    assert sent == [aid]          # exactly once


def test_execute_returns_structured_delivery_result(ground):
    """Direct use returns a structured result carrying the delivered id and the
    idempotency key — not a bare bool."""
    ex = DiscordExecutor(_iso(act=("#trellis",)), send_fn=lambda a: {"id": "m-7"})
    action = StagedAction("discord_post", "#trellis", "hi", created_by="trellis")
    res = ex.execute(action)
    assert res["status"] == "delivered"
    assert res["surface_id"] == "#trellis"
    assert res["idempotency_key"] == action.idempotency_key
    assert res["response"] == {"id": "m-7"}


# --- an ambiguous / timeout send is surfaced, never a false success ----------

def test_ambiguous_send_lands_unknown_not_false_success(tmp_path, ground):
    """A network timeout AFTER a partial send must propagate, so fire() lands the
    action UNKNOWN for a human reconcile (D26) — never swallowed into 'delivered'."""
    path = tmp_path / "l.jsonl"
    iso = _iso(act=("#trellis",))
    box = _box(path, ground, iso=iso)
    touched = []

    def flaky(a):
        touched.append(a.id)                 # the partial send reached the wire
        raise TimeoutError("remote ack never arrived")

    ex = DiscordExecutor(iso, send_fn=flaky)
    aid = box.stage(StagedAction("discord_post", "#trellis", "hi", created_by="trellis"))
    box.approve(aid, human="alex")
    with pytest.raises(FireOutcomeUnknown):
        box.fire(aid, executor=ex.execute)
    assert box.get(aid).status == ActionStatus.UNKNOWN
    assert touched == [aid]                   # it did touch the wire — hence unknown, not denied


def test_execute_does_not_swallow_send_error(ground):
    """Called directly, execute re-raises the transport error rather than
    returning a success dict."""
    def boom(a):
        raise TimeoutError("slow")
    ex = DiscordExecutor(_iso(act=("#trellis",)), send_fn=boom)
    action = StagedAction("discord_post", "#trellis", "hi", created_by="trellis")
    with pytest.raises(TimeoutError):
        ex.execute(action)


# --- an un-armed executor refuses rather than silently no-op'ing -------------

def test_unarmed_executor_refuses_no_silent_noop(ground):
    """send_fn is None and no real transport is configured: refuse (raise), do NOT
    return a false success — a no-op that reports 'delivered' would be a lie."""
    ex = DiscordExecutor(_iso(act=("#trellis",)), send_fn=None)
    action = StagedAction("discord_post", "#trellis", "hi", created_by="trellis")
    with pytest.raises(ExecutorNotArmed):
        ex.execute(action)


def test_unarmed_guard_still_runs_first(ground):
    """Even un-armed, the surface guard is evaluated first — a wrong surface is a
    SurfaceNotAllowed, never leaks past to the not-armed refusal."""
    ex = DiscordExecutor(_iso(act=("#trellis",)), send_fn=None)
    action = StagedAction("discord_post", "#other", "hi", created_by="trellis")
    with pytest.raises(SurfaceNotAllowed):
        ex.execute(action)


# --- a threaded send is governed by its parent channel's allowlist -----------

def test_threaded_send_resolves_to_parent_channel(ground):
    """A thread post is guarded against its PARENT CHANNEL (thread ids are dynamic
    and can't be pre-listed) — allowlist the channel, the thread post is allowed."""
    dest = ConversationKey(
        agent="trellis", surface=Surface.THREAD, scope="t-1", human="",
        thread=ThreadRef(id="t-1", parent_channel="#trellis", parent_message="m0"))
    action = StagedAction("discord_post", "t-1", "hi", created_by="trellis",
                          destination=dest)
    assert _act_surface_id(action) == "#trellis"
    sent = []
    ex = DiscordExecutor(_iso(act=("#trellis",)), send_fn=lambda a: sent.append(a.id))
    ex.execute(action)
    assert sent == [action.id]


# --- staging to a non-allowlisted ACT surface is refused (guard at STAGE) -----

def test_stage_refuses_non_allowlisted_surface_when_iso_supplied(tmp_path, ground):
    """When an Isolation is supplied to the Outbox, a wrong-surface action can't
    even be STAGED — refused before it could ever be approved (D38: guard at stage
    AND fire). Nothing is appended for it."""
    path = tmp_path / "l.jsonl"
    box = _box(path, ground, iso=_iso(act=("#trellis",)))
    with pytest.raises(SurfaceNotAllowed):
        box.stage(StagedAction("discord_post", "#other", "hi", created_by="trellis"))
    # nothing landed for that surface
    assert box.pending() == []
    assert not any(e.body.get("target") == "#other" for e in box.ledger.entries())


def test_stage_allows_allowlisted_surface_when_iso_supplied(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = _box(path, ground, iso=_iso(act=("#trellis",)))
    aid = box.stage(StagedAction("discord_post", "#trellis", "hi", created_by="trellis"))
    assert box.get(aid).status == ActionStatus.STAGED


def test_stage_without_iso_is_unguarded_backcompat(tmp_path, ground):
    """No Isolation supplied (existing callers): staging is unguarded — the 508
    tests and every current caller keep working unchanged."""
    path = tmp_path / "l.jsonl"
    box = _box(path, ground, iso=None)
    aid = box.stage(StagedAction("discord_post", "#anything", "hi", created_by="trellis"))
    assert box.get(aid).status == ActionStatus.STAGED
