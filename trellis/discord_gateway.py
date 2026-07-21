"""discord_gateway.py — the in-Discord approval gesture. (DECISIONS.md D38)

D38 flag RESOLVED (Alex, 2026-07-21): the agent does NOT auto-post. EVERY outbound
stays staged for the owner's yes (refusal #5 / W3 stand fully). The one change is
the APPROVAL SURFACE — "most of the interaction is going to be in Discord, so it
should go in Discord." The yes now happens as a reaction on the staged proposal,
mapped to the SAME authenticated, maker≠approver, lifecycle-gated Outbox
approve→fire path the web portal uses. This module maps a Discord reaction onto
that path; it never provides an alternate path that bypasses approval.

The safety model (do NOT weaken any of this):

  * OWNER-ONLY AUTHORIZATION. In Discord anyone in the server can react. So the
    reactor's Discord id IS the credential — the Discord-native equivalent of the
    portal's signed session. ONLY a reaction from the configured
    `approver_discord_id` (the owner) can approve or deny; a reaction from any
    other member is IGNORED (no approve, no fire, no side effect, no registry
    write). This check runs BEFORE anything else touches state.

  * IDENTITY STILL HARDENED. The owner's snowflake is resolved to a canonical id
    via the IdentityRegistry, then run through identity.require_identity — a
    homoglyph/exotic id is REFUSED, not reasoned about (round-4 #46 doctrine).

  * THROUGH THE OUTBOX, NEVER AROUND IT. approve→fire calls the hardened
    stage.Outbox: authenticated human, maker≠approver, lifecycle-state gate,
    fire-authorized-from-the-ledger, no double-fire. A denied action cannot be
    resurrected; a fired action cannot be re-fired. This module composes with
    those gates; it holds none of its own authority.

  * ISOLATION (D30). Every network send goes through isolation.guard_act first —
    trellis never posts to a surface outside its ACT allowlist. Sending to the
    wrong place is irreversible, so guard_act RAISES (checked twice:
    defensively in the gateway before the outbox lifecycle advances, and again
    inside the executor as belt-and-suspenders).

  * NO NETWORK IN CORE. The actual Discord API send is INJECTED (`sender`). In
    production it is stdlib urllib; in tests it is a mock that never hits the
    network (D11: model-agnostic, stdlib-only core). The live
    gateway/websocket connection (`DiscordGatewayConnection`) is a thin skeleton
    that awaits a real bot token — it does NOT connect on import or in tests.

Zero-dependency, fully offline, fully unit-tested (tests/test_x_gesture.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .identity import InvalidIdentityError, require_identity
from .isolation import Isolation, SurfaceNotAllowed
from .ledger import Ledger
from .stage import (ActionStatus, DoubleFireError, FireOutcomeUnknown, Outbox,
                    StagedAction, UnapprovedFireError, act_surface_id)


# ----- the reaction event + result ------------------------------------------


@dataclass(frozen=True)
class ReactionEvent:
    """A Discord reaction, normalized. `action_id` may be supplied directly, or a
    `message_ref` the gateway maps back to a staged action (populated by
    `post_proposal`). `reactor_discord_id` is the snowflake of whoever reacted —
    the credential. `emoji` is the reaction glyph."""
    reactor_discord_id: str
    emoji: str
    action_id: Optional[str] = None
    message_ref: Optional[str] = None
    reactor_display_name: str = ""


class ReactionOutcome(str, Enum):
    APPROVED_AND_FIRED = "approved_and_fired"
    DENIED = "denied"
    IGNORED = "ignored"        # not the owner, unhandled emoji, or unknown action
    REFUSED = "refused"        # owner, but a gate refused (exotic id, maker==approver, isolation)
    NOOP = "noop"              # owner + valid, but the lifecycle already decided it (no re-fire)
    FIRE_UNKNOWN = "fire_unknown"   # the send raised after the firing intent — a human reconciles


@dataclass(frozen=True)
class ReactionResult:
    status: ReactionOutcome
    action_id: Optional[str] = None
    approver: Optional[str] = None
    fired: bool = False
    reason: str = ""


# ----- the injected send executor -------------------------------------------


# The gesture path guards against the ONE canonical act-surface (stage.act_surface_id):
# a threaded reply is governed by its PARENT CHANNEL, so a legitimately allowlisted
# thread (channel⇒threads, D32) is not wrongly refused, and the surface guarded is
# exactly the surface sent to. (A prior local copy keyed on the dynamic thread id and
# diverged — a guard that checks a different surface than the send is the risk this
# consolidation removes.)
_act_surface_of = act_surface_id


def make_discord_send_executor(
        iso: Isolation,
        sender: Callable[[StagedAction, str], None],
        surface_of: Callable[[StagedAction], str] = _act_surface_of,
) -> Callable[[StagedAction], None]:
    """Build the executor handed to `Outbox.fire`. It calls `iso.allow.guard_act`
    BEFORE any network send (D30) — a non-allowlisted surface raises
    SurfaceNotAllowed and nothing leaves the machine — then delegates the actual
    API call to the INJECTED `sender` (stdlib urllib in production, a mock in
    tests). The executor never itself decides whether an action is approved; the
    Outbox has already authorized from the ledger before it is called."""
    def executor(action: StagedAction) -> None:
        surface = surface_of(action)
        iso.allow.guard_act(surface)          # refuse a wrong surface, loudly (irreversible)
        sender(action, surface)               # the injected send — mocked in tests
    return executor


# ----- the mapping logic (fully unit-tested) --------------------------------


class ApprovalGateway:
    """Maps a Discord reaction to the hardened Outbox approve→fire path.

    Construction mirrors the portal's dependencies: the `ledger` + `outbox` are
    the durable record; `iso` is the D30 isolation (identity + allowlist); the
    `registry` resolves a reactor snowflake to a canonical id; `executor` is the
    injected send path (see `make_discord_send_executor`); `approver_discord_id`
    is the OWNER's Discord snowflake — the only id whose reaction counts.

    Optional (safe defaults): `proposal_surface` + `proposal_sender` let
    `post_proposal` show the owner the full staged content on an allowlisted
    surface (a DM or designated channel) so there is something to react to.
    """

    def __init__(self, ledger: Ledger, iso: Isolation, registry, outbox: Outbox,
                 executor: Callable[[StagedAction], None],
                 approver_discord_id: str,
                 approve_emoji: str = "✅", deny_emoji: str = "❌",
                 proposal_surface: Optional[str] = None,
                 proposal_sender: Optional[Callable[[str, str], str]] = None):
        self.ledger = ledger
        self.iso = iso
        self.registry = registry
        self.outbox = outbox
        self.executor = executor
        self.approver_discord_id = (approver_discord_id or "").strip()
        self.approve_emoji = approve_emoji
        self.deny_emoji = deny_emoji
        self.proposal_surface = proposal_surface
        self.proposal_sender = proposal_sender
        # message_ref -> action_id, populated by post_proposal so a reaction that
        # carries only the message ref can be routed to its staged action.
        self._by_message_ref: dict[str, str] = {}

    # ----- posting a proposal so there is something to react to --------------

    def post_proposal(self, action: StagedAction) -> str:
        """Show the owner the FULL staged content on an allowlisted proposal
        surface (a DM or designated approval channel), and remember the resulting
        message ref so the owner's reaction on it maps back to this action.

        Posting a proposal is ITSELF an outbound — so it goes through the same
        `guard_act` allowlist gate as any send (D30). It is staged-safe: it only
        DISPLAYS a staged action awaiting a yes; it never fires anything."""
        if self.proposal_surface is None or self.proposal_sender is None:
            raise ValueError(
                "post_proposal requires a proposal_surface + proposal_sender "
                "(the owner DM/approval channel and its injected sender)")
        # the proposal is an outbound too — allowlist-gated like any send
        self.iso.allow.guard_act(self.proposal_surface)
        text = self._render_proposal(action)
        ref = self.proposal_sender(self.proposal_surface, text)
        if ref:
            self._by_message_ref[str(ref)] = action.id
        return ref

    @staticmethod
    def _render_proposal(action: StagedAction) -> str:
        """The full proposal body the owner reacts on — the WHOLE content, not a
        preview, so the yes is informed."""
        return (f"Proposed {action.kind} → {action.target}\n"
                f"(action {action.id})\n\n{action.content}\n\n"
                "React ✅ to approve & send, ❌ to deny.")

    # ----- the reaction gesture ----------------------------------------------

    def on_reaction(self, event: ReactionEvent) -> ReactionResult:
        """Route one reaction. Order matters: cheap/safe rejections first, so a
        non-owner or unhandled emoji causes NO state change and NO registry
        write — anyone can react in Discord, and only the owner's reaction may
        move the world."""
        # 0) only the two emojis we handle mean anything
        if event.emoji not in (self.approve_emoji, self.deny_emoji):
            return ReactionResult(ReactionOutcome.IGNORED, reason="unhandled emoji")

        # 1) resolve the message ref to an action id (if the event carried a ref)
        action_id = event.action_id or self._by_message_ref.get(
            (event.message_ref or ""))
        if not action_id:
            return ReactionResult(ReactionOutcome.IGNORED, reason="no such staged action")
        action = self.outbox.get(action_id)
        if action is None:
            return ReactionResult(ReactionOutcome.IGNORED, action_id=action_id,
                                  reason="no such staged action")

        # 2) OWNER-ONLY. The reactor's Discord id is the credential (the Discord-
        # native signed session). A reaction from anyone else is ignored — no
        # approve, no fire, no side effect, no registry write.
        if (event.reactor_discord_id or "").strip() != self.approver_discord_id \
                or not self.approver_discord_id:
            return ReactionResult(ReactionOutcome.IGNORED, action_id=action_id,
                                  reason="reactor is not the configured owner")

        # 3) resolve the owner's canonical id and REQUIRE a clean ASCII identity —
        # a homoglyph/exotic resolved id is refused, not reasoned about.
        try:
            canonical = self.registry.resolve(event.reactor_discord_id,
                                              event.reactor_display_name)
            human = require_identity(canonical, "approver")
        except InvalidIdentityError as e:
            return ReactionResult(ReactionOutcome.REFUSED, action_id=action_id,
                                  reason=f"exotic/homoglyph approver id refused: {e}")

        if event.emoji == self.deny_emoji:
            return self._deny(action_id, human)
        return self._approve_and_fire(action, human)

    # ----- the two branches, both THROUGH the Outbox -------------------------

    def _approve_and_fire(self, action: StagedAction, human: str) -> ReactionResult:
        aid = action.id
        # Defensive isolation check BEFORE the lifecycle advances: a wrong surface
        # is refused while the action is still STAGED (so it stays fireable once the
        # operator fixes the allowlist — never polluted into UNKNOWN). The executor
        # guards again at send time (belt-and-suspenders).
        try:
            self.iso.allow.guard_act(_act_surface_of(action))
        except SurfaceNotAllowed as e:
            return ReactionResult(ReactionOutcome.REFUSED, action_id=aid, approver=human,
                                  reason=f"act surface not allowlisted: {e}")
        # approve THROUGH the Outbox (authenticated human, maker≠approver,
        # lifecycle-state gate). A denied/fired action or a maker==approver is
        # refused HERE, not by this module.
        try:
            self.outbox.approve(aid, human=human)
        except UnapprovedFireError as e:
            # already-decided (denied/fired) → NOOP; maker==approver / bad id → REFUSED
            cur = self.outbox.get(aid)
            if cur is not None and cur.status != ActionStatus.STAGED:
                return ReactionResult(ReactionOutcome.NOOP, action_id=aid, approver=human,
                                      reason=f"already {cur.status.value}: {e}")
            return ReactionResult(ReactionOutcome.REFUSED, action_id=aid, approver=human,
                                  reason=str(e))
        # fire THROUGH the Outbox (authorizes from the ledger, no double-fire).
        try:
            self.outbox.fire(aid, self.executor)
        except DoubleFireError as e:
            return ReactionResult(ReactionOutcome.NOOP, action_id=aid, approver=human,
                                  reason=f"already firing/fired: {e}")
        except FireOutcomeUnknown as e:
            return ReactionResult(ReactionOutcome.FIRE_UNKNOWN, action_id=aid, approver=human,
                                  reason=f"send outcome unknown — reconcile: {e}")
        except (UnapprovedFireError, SurfaceNotAllowed) as e:
            return ReactionResult(ReactionOutcome.REFUSED, action_id=aid, approver=human,
                                  reason=str(e))
        return ReactionResult(ReactionOutcome.APPROVED_AND_FIRED, action_id=aid,
                              approver=human, fired=True)

    def _deny(self, action_id: str, human: str) -> ReactionResult:
        try:
            self.outbox.deny(action_id, human=human,
                             reason="denied in Discord (❌ reaction by the owner)")
        except UnapprovedFireError as e:
            cur = self.outbox.get(action_id)
            if cur is not None and cur.status not in (ActionStatus.STAGED,
                                                      ActionStatus.APPROVED):
                return ReactionResult(ReactionOutcome.NOOP, action_id=action_id,
                                      approver=human, reason=f"already {cur.status.value}")
            return ReactionResult(ReactionOutcome.REFUSED, action_id=action_id,
                                  approver=human, reason=str(e))
        return ReactionResult(ReactionOutcome.DENIED, action_id=action_id, approver=human)


# ----- the live gateway skeleton (awaits a real trellis-owned bot token) ----


class DiscordGatewayConnection:
    """A THIN skeleton for the live Discord gateway/websocket connection. It is
    deliberately NOT wired to a network client: the mapping logic above is what
    carries the safety guarantees and is fully unit-tested, while the live
    connection needs an operator's trellis-owned bot token (D30) and is stood up
    outside the test suite.

    Constructing this object does nothing observable; `run()` is the only method
    that would open a socket, and it refuses to run without an explicit token —
    so importing or instantiating this class never connects or sends."""

    def __init__(self, gateway: ApprovalGateway, bot_token: Optional[str] = None):
        self.gateway = gateway
        self._bot_token = bot_token

    def run(self) -> None:  # pragma: no cover - needs a real bot token + network
        """Open the live gateway and dispatch reactions to
        `self.gateway.on_reaction`. Unbuilt on purpose: it awaits a real
        trellis-owned bot token and the production urllib/websocket client. It
        never runs in tests or on import."""
        if not (self._bot_token or "").strip():
            raise RuntimeError(
                "DiscordGatewayConnection.run() needs a trellis-owned bot token "
                "(D30) — set it and wire the production websocket client; the "
                "approval MAPPING is already unit-tested via ApprovalGateway.")
        raise NotImplementedError(
            "live Discord websocket loop is an operator step — construct the "
            "ApprovalGateway from env (see `trellis discord`) and dispatch each "
            "MESSAGE_REACTION_ADD to gateway.on_reaction(...).")
