"""executor.py — the Discord SEND path. (DECISIONS.md D38, D30, D26)

trellis's executor CAN post to the world — and that is exactly why it is boxed in
on every side. It never provides an alternate path to the wire: the ONLY way it
runs is as the callable `stage.Outbox.fire(action_id, executor=…)` invokes AFTER a
durable human yes (refusal #5 / W3 stand fully — every outbound stays staged for
the owner's approval; D38 only moved the *approval surface* into Discord, it did
not grant auto-post). So the maker!=approver, ledger-authorized, lifecycle-gated
approval gate is upstream of every byte this module sends.

Two more structural refusals live here:

  * ISOLATION (D30). Before ANY network send, `iso.allow.guard_act(surface_id)` is
    called. A surface not on trellis's ACT allowlist raises `SurfaceNotAllowed` and
    nothing is sent — sending to the wrong place is irreversible, so this side
    refuses LOUDLY, never silently drops. A threaded post is guarded against its
    PARENT CHANNEL (thread ids are dynamic and can't be pre-listed), mirroring the
    channel⇒threads admission on the read side (D32).

  * MODEL-AGNOSTIC, STDLIB-ONLY, TESTABLE (D11). The Discord API call is INJECTED
    as `send_fn`. In production that is a stdlib `urllib` POST
    (`urllib_discord_sender`); in tests it is a mock, so the executor NEVER hits
    the network by default. An un-armed executor (no `send_fn`, no configured
    transport) REFUSES (`ExecutorNotArmed`) rather than silently no-op'ing — a
    no-op that reported "delivered" would be a lie the ledger then trusts.

Ambiguity is surfaced, not swallowed (D26). If `send_fn` raises after a partial
send (a timeout with no ack), the exception PROPAGATES. `Outbox.fire` — which
recorded a `firing` intent before calling us — catches it and lands the action
`unknown`, and only a human `reconcile()` resolves it. The executor never converts
an ambiguous send into a false success.
"""

from __future__ import annotations

from typing import Callable, Optional

from typing import TYPE_CHECKING

from .isolation import Isolation
from .stage import ActionStatus, Outbox, StagedAction, act_surface_id
from .surfaces import Surface

if TYPE_CHECKING:
    from .ledger import Ledger

# the single source of truth for act-surface resolution lives in stage.py (the
# lowest module executor/gateway both import), so guard-surface == send-surface.
_act_surface_id = act_surface_id


class UnapprovedSendError(Exception):
    """The executor was asked to send an action the ledger does not show as
    APPROVED (or in-flight FIRING). Defense in depth: even called directly — not
    through Outbox.fire — an armed executor with a ledger refuses to put bytes on
    the wire without a durable human yes on the record (refusal #5)."""


class ExecutorNotArmed(Exception):
    """The executor was asked to send but has no transport (`send_fn` is None and
    no real transport is configured). It refuses rather than silently no-op'ing —
    the send path is 'can post', not 'pretends to post'."""


class DiscordExecutor:
    """The callable `Outbox.fire` invokes to actually post an APPROVED action.

    Composes with — never bypasses — the hardened Outbox: it is only ever reached
    through `fire()`, which authorizes from the ledger, requires the latest
    transition == APPROVED, and refuses a double-fire. This class adds the D30
    surface gate and the injected, network-free transport.
    """

    def __init__(self, iso: Isolation, send_fn: Optional[Callable[[StagedAction], object]] = None,
                 ledger: Optional["Ledger"] = None):
        self.iso = iso
        self.send_fn = send_fn
        # Defense in depth (D38): when a ledger is supplied, execute() re-derives
        # the action's authoritative status and refuses to send anything not
        # APPROVED/FIRING — so the send path does not rest SOLELY on the
        # compositional "only Outbox.fire ever calls execute()" assumption. A
        # production-armed executor MUST be given the ledger; a mock-only unit test
        # may omit it.
        self.ledger = ledger

    def execute(self, action: StagedAction) -> dict:
        """Post one APPROVED action. Returns a structured delivery result.

        Order matters and is load-bearing:
          1. resolve the target surface id;
          2. `guard_act` — refuse LOUDLY (SurfaceNotAllowed) before any send;
          3. refuse if un-armed — never a silent no-op;
          4. call the injected transport; let its errors PROPAGATE so an ambiguous
             send lands `unknown` in the Outbox (D26), never a false success.

        Designed to be handed to `Outbox.fire(..., executor=self.execute)`: fire
        ignores the return value (the send already happened) but any exception it
        catches becomes a durable `unknown` for a human reconcile. It is equally
        safe to call directly, where the return dict and the raised errors are the
        caller's to read.
        """
        surface_id = _act_surface_id(action)
        # (2) D30: the outer gate. A non-allowlisted surface is refused before the
        # wire is ever touched — irreversible sends are never risked.
        self.iso.allow.guard_act(surface_id)
        # (2b) defense in depth: when we hold the ledger, refuse to send an action
        # that does not carry a durable approval (APPROVED, or FIRING mid-fire) —
        # even if some future caller reaches execute() outside Outbox.fire.
        if self.ledger is not None:
            current = Outbox(self.ledger).get(action.id)
            status = current.status if current is not None else None
            if status not in (ActionStatus.APPROVED, ActionStatus.FIRING):
                raise UnapprovedSendError(
                    f"refusing to send {action.id!r}: the ledger shows "
                    f"{status.value if status else 'no such action'}, not an approved "
                    "human yes — the executor never sends without a durable approval")
        # (3) refuse an un-armed executor rather than report a phantom success.
        if self.send_fn is None:
            raise ExecutorNotArmed(
                f"executor has no transport for {surface_id!r}: pass a send_fn (a mock "
                "in tests, urllib_discord_sender in production). Refusing rather than "
                "silently no-op'ing a send the ledger would then record as delivered.")
        # (4) call the world. Do NOT wrap in try/except that swallows: an ambiguous
        # send (timeout after partial write) must propagate so fire() lands it
        # 'unknown' (D26) — surfacing it, never a false 'delivered'.
        response = self.send_fn(action)
        return {"status": "delivered", "surface_id": surface_id,
                "idempotency_key": action.idempotency_key, "response": response}


def _is_dm_action(action: StagedAction) -> bool:
    """True when this action's destination is a private DM (Surface.DM). A DM is
    addressed by the OWNER's user id (the stable, allowlistable surface); the
    dynamic DM channel id is resolved at send time via `open_dm`, mirroring the
    channel⇒threads rule on the act side (D30/D32)."""
    dest = action.destination
    return dest is not None and dest.surface == Surface.DM


def urllib_discord_sender(iso: Isolation, api_base: str = "https://discord.com/api/v10",
                          urlopen: Optional[Callable] = None,
                          client: Optional[object] = None) -> Callable[[StagedAction], dict]:
    """Build a production `send_fn` that POSTs an approved action's content to its
    target surface via the stdlib-only `DiscordClient` (D11 — no third-party HTTP
    client). The trellis bot credential is fetched on demand from its env var by the
    client (D30 — never stored, never logged, never in an exception string) and the
    send carries the action's idempotency key as the Discord `nonce`, so a remote
    that dedups turns trellis's fire-at-most-once into true exactly-once (D26).

    Surface resolution mirrors the guard (`act_surface_id`) so the surface SENT to is
    exactly the surface GUARDED:
      * a channel/thread action posts to `act_surface_id(action)` (the parent channel
        for a threaded reply, D32);
      * a Surface.DM action's surface is the owner's user id — allowlisted as such —
        which is resolved to a concrete DM channel via `open_dm(user_id)` FIRST, then
        posted to. The user id is what `guard_act` already admitted upstream.

    `urlopen` is injectable purely so this transport stays testable without the
    network; production leaves it None and the client uses `urllib.request.urlopen`.
    `client` is injectable for tests (a mock DiscordClient); production leaves it None
    and one is constructed from `iso.identity`. The executor's DEFAULT transport is
    still None — this must be wired in explicitly, so nothing posts to Discord until a
    human arms it. The bot token never appears in the return value or any raised error.
    """
    from .discord_api import DiscordClient  # stdlib-only client; imported lazily (no net on import)

    dc = client if client is not None else DiscordClient(
        identity_or_token_env=iso.identity, urlopen=urlopen, api_base=api_base)

    def send(action: StagedAction) -> dict:
        surface = _act_surface_id(action)          # the guarded surface == the sent surface
        if _is_dm_action(action):
            # a DM is addressed by the owner's user id (allowlisted); resolve it to a
            # concrete DM channel id first, then post there.
            channel_id = dc.open_dm(surface)
        else:
            channel_id = surface
        # the idempotency key rides as the nonce (fire-at-most-once → exactly-once)
        return dc.post_message(channel_id, action.content, nonce=action.idempotency_key)

    return send
