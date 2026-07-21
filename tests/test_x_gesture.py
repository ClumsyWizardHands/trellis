"""test_x_gesture.py — the in-Discord approval gesture (D38).

"The yes now happens in Discord" (D38 flag RESOLVED). A reaction/command on a
staged proposal maps to the SAME authenticated, maker≠approver, lifecycle-gated
Outbox.approve→fire path the web portal uses — never around it.

The safety model these tests pin (do NOT weaken):
  * ONLY a reaction from the configured owner (approver_discord_id) may approve or
    deny. In Discord anyone can react, so the reactor's Discord id IS the
    credential — a reaction from any other member is IGNORED (no approve, no fire).
    This is the Discord-native equivalent of the portal's signed session.
  * the resolved canonical id still runs through identity.require_identity — a
    homoglyph/exotic id is refused, not reasoned about.
  * approve→fire goes THROUGH the hardened Outbox (authenticated human,
    maker≠approver, lifecycle-state gate, fire-from-ledger, no double-fire).
  * the send path calls isolation.guard_act before any network send — trellis
    never posts to a surface outside its ACT allowlist.
  * NOTHING hits the network in a test: the executor's sender is injected + mocked.
"""

from __future__ import annotations

import pytest

from trellis.discord_gateway import (ApprovalGateway, ReactionEvent,
                                     ReactionOutcome, make_discord_send_executor)
from trellis.identity import InvalidIdentityError
from trellis.isolation import (AgentIdentity, Isolation, SurfaceAllowlist,
                               SurfaceNotAllowed)
from trellis.ledger import Ledger
from trellis.registry import IdentityRegistry
from trellis.stage import ActionStatus, Outbox, StagedAction

OWNER_SNOWFLAKE = "111111111111111111"        # Alex's Discord user id (the owner)
OTHER_SNOWFLAKE = "999999999999999999"        # some other server member
CHANNEL = "chan-abc"                          # a channel on trellis's ACT allowlist
AGENT = "trellis-witness"                     # the maker (staged the action)


def _iso(act=(CHANNEL,), read=(CHANNEL,)):
    return Isolation(identity=AgentIdentity(name="trellis"),
                     allow=SurfaceAllowlist(read=frozenset(read), act=frozenset(act)))


def _stage(outbox, target=CHANNEL, content="Read updated: adopt July framing.",
           created_by=AGENT):
    aid = outbox.stage(StagedAction(kind="discord_post", target=target,
                                    content=content, created_by=created_by))
    return aid


def _gateway(ledger, outbox, iso, sends, registry=None, owner=OWNER_SNOWFLAKE):
    registry = registry or IdentityRegistry(ledger)
    executor = make_discord_send_executor(iso, sender=lambda a, s: sends.append((s, a.content)))
    return ApprovalGateway(ledger=ledger, iso=iso, registry=registry, outbox=outbox,
                           executor=executor, approver_discord_id=owner)


# ---------------------------------------------------------------------------
# 1. the owner's yes approves AND fires — through the Outbox
# ---------------------------------------------------------------------------

def test_owner_reaction_approves_and_fires_through_outbox(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends)
    aid = _stage(outbox)

    out = gw.on_reaction(ReactionEvent(action_id=aid,
                                       reactor_discord_id=OWNER_SNOWFLAKE,
                                       emoji="✅", reactor_display_name="Alex"))

    assert out.status == ReactionOutcome.APPROVED_AND_FIRED
    assert out.fired is True
    assert outbox.get(aid).status == ActionStatus.FIRED
    # the send physically happened exactly once, to the allowlisted surface
    assert sends == [(CHANNEL, "Read updated: adopt July framing.")]
    # the human recorded on the approval is the owner's canonical id, not the agent
    assert outbox.get(aid).approved_by
    assert outbox.get(aid).approved_by != AGENT


# ---------------------------------------------------------------------------
# 2. a reaction from a DIFFERENT discord id is IGNORED — no approve, no fire
# ---------------------------------------------------------------------------

def test_non_owner_reaction_is_ignored_no_approval_no_fire(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends)
    aid = _stage(outbox)

    out = gw.on_reaction(ReactionEvent(action_id=aid,
                                       reactor_discord_id=OTHER_SNOWFLAKE,
                                       emoji="✅", reactor_display_name="Mallory"))

    assert out.status == ReactionOutcome.IGNORED
    assert out.fired is False
    # nothing sent, nothing approved, still STAGED
    assert sends == []
    assert outbox.get(aid).status == ActionStatus.STAGED
    assert outbox.get(aid).approved_by is None
    # and no identity_registration was written for the random reactor
    assert IdentityRegistry(ledger).canonical_for(OTHER_SNOWFLAKE) is None


def test_non_owner_cannot_fire_even_after_owner_would_have(tmp_path, ground):
    # a non-owner ✅ never fires, even on an otherwise-fireable action
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends)
    aid = _stage(outbox)
    gw.on_reaction(ReactionEvent(action_id=aid, reactor_discord_id=OTHER_SNOWFLAKE,
                                 emoji="✅"))
    assert outbox.get(aid).status == ActionStatus.STAGED
    assert sends == []


# ---------------------------------------------------------------------------
# 3. a homoglyph/exotic resolved id is REFUSED
# ---------------------------------------------------------------------------

class _ExoticRegistry:
    """A stand-in registry that resolves the owner snowflake to an EXOTIC id
    (a Cyrillic-laden 'аlex'). The gateway must refuse it via require_identity —
    never reason about a homoglyph as if it were a real ASCII human."""
    def resolve(self, discord_user_id, display_name=""):
        return "аlex"   # Cyrillic 'а' + 'lex' — not a valid ASCII identity


def test_exotic_resolved_id_is_refused(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends, registry=_ExoticRegistry())
    aid = _stage(outbox)

    out = gw.on_reaction(ReactionEvent(action_id=aid,
                                       reactor_discord_id=OWNER_SNOWFLAKE, emoji="✅"))

    assert out.status == ReactionOutcome.REFUSED
    assert out.fired is False
    assert sends == []
    assert outbox.get(aid).status == ActionStatus.STAGED


# ---------------------------------------------------------------------------
# 4. the deny emoji denies — and a denied action cannot be resurrected
# ---------------------------------------------------------------------------

def test_owner_deny_denies(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends)
    aid = _stage(outbox)

    out = gw.on_reaction(ReactionEvent(action_id=aid,
                                       reactor_discord_id=OWNER_SNOWFLAKE, emoji="❌"))

    assert out.status == ReactionOutcome.DENIED
    assert outbox.get(aid).status == ActionStatus.DENIED
    assert sends == []


def test_denied_action_cannot_be_resurrected_by_a_later_yes(tmp_path, ground):
    # composes with the Outbox lifecycle gate: deny → ✅ never fires
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends)
    aid = _stage(outbox)
    gw.on_reaction(ReactionEvent(action_id=aid, reactor_discord_id=OWNER_SNOWFLAKE, emoji="❌"))

    out = gw.on_reaction(ReactionEvent(action_id=aid, reactor_discord_id=OWNER_SNOWFLAKE,
                                       emoji="✅"))

    assert out.status == ReactionOutcome.NOOP    # refused by lifecycle gate, not fired
    assert out.fired is False
    assert outbox.get(aid).status == ActionStatus.DENIED
    assert sends == []


# ---------------------------------------------------------------------------
# 5. double-reaction does not double-fire
# ---------------------------------------------------------------------------

def test_double_reaction_does_not_double_fire(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends)
    aid = _stage(outbox)

    first = gw.on_reaction(ReactionEvent(action_id=aid, reactor_discord_id=OWNER_SNOWFLAKE,
                                         emoji="✅"))
    second = gw.on_reaction(ReactionEvent(action_id=aid, reactor_discord_id=OWNER_SNOWFLAKE,
                                          emoji="✅"))

    assert first.status == ReactionOutcome.APPROVED_AND_FIRED
    assert second.status == ReactionOutcome.NOOP   # already fired — no re-fire
    assert second.fired is False
    assert len(sends) == 1                         # sent exactly once
    assert outbox.get(aid).status == ActionStatus.FIRED


# ---------------------------------------------------------------------------
# 6. maker≠approver: the agent's own reaction can never approve its own action
# ---------------------------------------------------------------------------

def test_maker_cannot_self_approve_via_reaction(tmp_path, ground):
    # An action staged by the human's own canonical id would let the owner's
    # reaction collide with the maker. The Outbox independence gate refuses it.
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    registry = IdentityRegistry(ledger)
    # pre-register the owner so we know its canonical id, and stage AS that id
    owner_canonical = registry.resolve(OWNER_SNOWFLAKE, "Alex")
    gw = _gateway(ledger, outbox, iso, sends, registry=registry)
    aid = _stage(outbox, created_by=owner_canonical)

    out = gw.on_reaction(ReactionEvent(action_id=aid, reactor_discord_id=OWNER_SNOWFLAKE,
                                       emoji="✅"))

    assert out.status == ReactionOutcome.REFUSED   # maker == approver, refused
    assert out.fired is False
    assert sends == []
    assert outbox.get(aid).status == ActionStatus.STAGED


# ---------------------------------------------------------------------------
# 7. isolation: a send to a non-allowlisted surface is refused, never sent
# ---------------------------------------------------------------------------

def test_send_to_non_allowlisted_surface_is_refused(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso(act=("some-other-channel",))    # CHANNEL is NOT on the act allowlist
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends)
    aid = _stage(outbox, target=CHANNEL)

    out = gw.on_reaction(ReactionEvent(action_id=aid, reactor_discord_id=OWNER_SNOWFLAKE,
                                       emoji="✅"))

    assert out.status == ReactionOutcome.REFUSED
    assert sends == []                              # nothing left the machine
    # refused BEFORE the outbox lifecycle advanced — still fireable once the
    # operator fixes the allowlist (no pollution into UNKNOWN)
    assert outbox.get(aid).status == ActionStatus.STAGED


def test_executor_guards_act_independently(tmp_path, ground):
    # defense-in-depth: even called directly, the executor refuses a bad surface
    iso = _iso(act=("only-this",))
    sends: list = []
    ex = make_discord_send_executor(iso, sender=lambda a, s: sends.append(s))
    action = StagedAction(kind="discord_post", target="not-allowed", content="x",
                          created_by=AGENT)
    with pytest.raises(SurfaceNotAllowed):
        ex(action)
    assert sends == []


# ---------------------------------------------------------------------------
# 8. unhandled emoji and unknown action are ignored (not crashed)
# ---------------------------------------------------------------------------

def test_unhandled_emoji_is_ignored(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends)
    aid = _stage(outbox)
    out = gw.on_reaction(ReactionEvent(action_id=aid, reactor_discord_id=OWNER_SNOWFLAKE,
                                       emoji="🎉"))
    assert out.status == ReactionOutcome.IGNORED
    assert outbox.get(aid).status == ActionStatus.STAGED
    assert sends == []


def test_reaction_on_unknown_action_is_ignored(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso()
    sends: list = []
    gw = _gateway(ledger, outbox, iso, sends)
    out = gw.on_reaction(ReactionEvent(action_id="nope", reactor_discord_id=OWNER_SNOWFLAKE,
                                       emoji="✅"))
    assert out.status == ReactionOutcome.IGNORED
    assert sends == []


# ---------------------------------------------------------------------------
# 9. post_proposal posts the FULL staged content through guard_act, and maps
#    the returned message ref back to the action for the reaction gesture
# ---------------------------------------------------------------------------

def test_post_proposal_guards_act_and_maps_message_ref(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso(act=(CHANNEL, "owner-dm"))
    sends: list = []
    posted: list = []
    registry = IdentityRegistry(ledger)
    executor = make_discord_send_executor(iso, sender=lambda a, s: sends.append((s, a.content)))
    gw = ApprovalGateway(ledger=ledger, iso=iso, registry=registry, outbox=outbox,
                         executor=executor, approver_discord_id=OWNER_SNOWFLAKE,
                         proposal_surface="owner-dm",
                         proposal_sender=lambda s, text: posted.append((s, text)) or "msg-77")
    aid = _stage(outbox, content="FULL PROPOSAL BODY — approve to send")

    ref = gw.post_proposal(outbox.get(aid))

    assert ref == "msg-77"
    assert posted and posted[0][0] == "owner-dm"
    assert "FULL PROPOSAL BODY" in posted[0][1]     # the FULL content, not a preview
    # the reaction can now arrive by message_ref (not only by action_id)
    out = gw.on_reaction(ReactionEvent(message_ref="msg-77",
                                       reactor_discord_id=OWNER_SNOWFLAKE, emoji="✅"))
    assert out.status == ReactionOutcome.APPROVED_AND_FIRED
    assert sends == [(CHANNEL, "FULL PROPOSAL BODY — approve to send")]


def test_post_proposal_refuses_non_allowlisted_proposal_surface(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    outbox = Outbox(ledger, ground)
    iso = _iso(act=(CHANNEL,))       # 'owner-dm' NOT allowlisted
    posted: list = []
    registry = IdentityRegistry(ledger)
    executor = make_discord_send_executor(iso, sender=lambda a, s: None)
    gw = ApprovalGateway(ledger=ledger, iso=iso, registry=registry, outbox=outbox,
                         executor=executor, approver_discord_id=OWNER_SNOWFLAKE,
                         proposal_surface="owner-dm",
                         proposal_sender=lambda s, text: posted.append(text) or "m")
    aid = _stage(outbox)
    with pytest.raises(SurfaceNotAllowed):
        gw.post_proposal(outbox.get(aid))
    assert posted == []
