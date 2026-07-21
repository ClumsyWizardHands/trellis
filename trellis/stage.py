"""stage.py — stage, don't fire. (DECISIONS.md D10, D26)

"Nothing is ever sent, posted, or applied automatically… correcting, not
creating, is where strategic thinking happens." — DAILY-EMPIRE-PROTOCOL,
2026-07-15

The strongest cross-voice consensus in the whole failure dossier: never let
agent output hit a stakeholder unchecked (Clare's QA gates, Sarah's leak
grievance, Peter's "can't send 90% to a CEO"). And the 2026 security record —
79% prompt-injection success against always-on agents — makes staging the
cheap structural defense: an injected agent can stage garbage, but a human is
between the garbage and the world.

DURABILITY (D26, Codex Critical 3): the **ledger is the single source of truth**;
the in-memory dict is a rebuildable cache. Every transition — stage, approve,
deny, firing, fired, unknown — is a ledger event carrying the FULL payload, so a
fresh process (and the web UI, and the executor) all reconstruct the same state.
`fire()` is idempotent: it records a `firing` intent BEFORE calling the world and
refuses to re-fire an action already firing/fired, so a crash-then-retry can never
double-send. When the executor's outcome is ambiguous the action lands `unknown`
(not `approved`), and only a human `reconcile()` resolves it. Refusal #5 now holds
across a restart, not just within one process.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

try:
    import fcntl   # POSIX advisory locking (macOS/Linux — the deployment)
except ImportError:  # pragma: no cover
    fcntl = None

from .clock import TimeGround
from .identity import (InvalidIdentityError, require_identity, same_identity)
from .ledger import Ledger
from .surfaces import ConversationKey, Surface, ThreadRef


class ActionStatus(str, Enum):
    STAGED = "staged"
    APPROVED = "approved"
    DENIED = "denied"
    FIRING = "firing"        # intent recorded; the executor is being called (in-flight)
    FIRED = "fired"
    UNKNOWN = "unknown"      # executor outcome ambiguous — a human must reconcile
    EXPIRED = "expired"


class UnapprovedFireError(Exception):
    pass


class DoubleFireError(Exception):
    """An action already firing or fired cannot be fired again — no blind retry
    of a side effect that may already have reached the world (D26)."""


class FireOutcomeUnknown(Exception):
    """The executor raised after the firing intent was recorded — the side effect
    may or may not have reached the world. The action is durably `unknown`; a human
    reconciles it. Never silently retried."""


@dataclass
class StagedAction:
    kind: str                       # "discord_post" / "email_send" / "file_apply" / ...
    target: str                     # channel id, address, path
    content: str
    created_by: str                 # the agent that staged it
    destination: Optional[ConversationKey] = None
    status: ActionStatus = ActionStatus.STAGED
    approved_by: Optional[str] = None
    denial_reason: Optional[str] = None
    idempotency_key: str = field(default_factory=lambda: uuid.uuid4().hex)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def content_hash(self) -> str:
        return hashlib.sha256(
            f"{self.kind}\x1f{self.target}\x1f{self.content}".encode("utf-8")).hexdigest()[:16]


def _destination_to_body(dest: Optional[ConversationKey]) -> Optional[dict]:
    """Serialize the full structured destination for the ledger (D26, Codex#16):
    the routing metadata must survive a restart, not be dropped to None."""
    if dest is None:
        return None
    d = {"agent": dest.agent, "surface": dest.surface.value,
         "scope": dest.scope, "human": dest.human}
    if dest.thread is not None:
        d["thread"] = {"id": dest.thread.id,
                       "parent_channel": dest.thread.parent_channel,
                       "parent_message": dest.thread.parent_message}
    return d


def _destination_from_body(d: Optional[dict]) -> Optional[ConversationKey]:
    """Reconstruct a ConversationKey persisted by _destination_to_body. A body
    that no longer maps to a known Surface is dropped to None rather than guessed
    — an unroutable destination is not fabricated."""
    if not d:
        return None
    try:
        surface = Surface(d.get("surface"))
    except ValueError:
        return None
    thread = None
    td = d.get("thread")
    if td:
        thread = ThreadRef(id=td.get("id", ""),
                           parent_channel=td.get("parent_channel", ""),
                           parent_message=td.get("parent_message"))
    return ConversationKey(agent=d.get("agent", ""), surface=surface,
                           scope=d.get("scope", ""), human=d.get("human", ""),
                           thread=thread)


def act_surface_id(action: StagedAction) -> str:
    """The surface id an action's send is guarded against (D30/D38). A threaded
    post is governed by its PARENT CHANNEL (thread ids are dynamic and can't be
    pre-listed), else the concrete `target`.

    This is the ONE canonical act-surface resolver — stage (stage-time guard),
    executor (fire-time guard) and the Discord approval gateway all import THIS
    function, so the surface a send is *guarded against* is always exactly the
    surface it is *sent to*. Three divergent copies were a real risk: the gateway's
    used the dynamic thread id and wrongly refused a legitimately allowlisted
    threaded reply (breaking the D32 channel⇒threads rule on the act side). It
    lives here, the lowest module the others already import, to avoid a cycle."""
    dest = action.destination
    if dest is not None and dest.thread is not None and dest.thread.parent_channel:
        return dest.thread.parent_channel
    return action.target


_act_surface_id = act_surface_id   # internal alias (stage-time guard call site)


class Outbox:
    """The one gate between an agent and the world — durable and idempotent."""

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None,
                 iso: Optional[object] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground
        # OPTIONAL D30 isolation. When supplied, an action whose target surface is
        # not on trellis's ACT allowlist is refused at STAGE time (D38: guard at
        # stage AND fire), so a wrong-surface action can never even reach approval.
        # Absent (every existing caller) → staging is unguarded, unchanged.
        self.iso = iso
        self._actions: dict[str, StagedAction] = {}
        self._load()   # reconstruct from the ledger — survive a restart (D26)

    # ----- reconstruction (the ledger is the source of truth) ----------------

    @staticmethod
    def _event_status(body: dict) -> Optional[ActionStatus]:
        """The lifecycle status a single staged_action event settles the action
        into, or None if the event carries no status. `reconciled` and
        `fire_unknown` map by their event name (the ledger body's `status` for a
        reconcile is already correct, but naming keeps the fold explicit)."""
        ev = body.get("event", "staged")
        if ev == "reconciled":
            return ActionStatus.FIRED if body.get("reconciled_fired") else ActionStatus.APPROVED
        if ev == "fire_unknown":
            return ActionStatus.UNKNOWN
        raw = body.get("status")
        if raw is None:
            return None
        try:
            return ActionStatus(raw)
        except ValueError:
            return ActionStatus.STAGED

    @staticmethod
    def _event_approver(e) -> Optional[str]:
        """The human who approved, retained as the transition actor (Codex#16):
        an explicit `approved_by`/`by` if present, else the ledger author of the
        `approved` event (the web UI writes no `approved_by` field)."""
        return e.body.get("approved_by") or e.body.get("by") or e.author

    def _load(self) -> None:
        """Rebuild every action's payload + current status from the ledger's
        staged_action events. The payload (incl. the FULL structured destination)
        comes from the `staged` event; the status is FOLDED across every event per
        action_id in ledger order (the web UI also writes events, so there is no
        split-brain). The approving actor is retained from the `approved`
        transition — never dropped to None (Codex#16)."""
        payloads: dict[str, dict] = {}
        order: list[str] = []
        status: dict[str, ActionStatus] = {}
        approver: dict[str, Optional[str]] = {}
        reason: dict[str, Optional[str]] = {}
        for e in self.ledger.entries():
            if e.kind != "staged_action":
                continue
            aid = e.body.get("action_id")
            if not aid:
                continue
            ev = e.body.get("event", "staged")
            if ev in ("staged", None) and e.body.get("kind"):
                if aid not in payloads:
                    order.append(aid)
                payloads[aid] = e.body
            st = self._event_status(e.body)
            if st is not None:
                status[aid] = st
            if ev == "approved":
                approver[aid] = self._event_approver(e)
            if ev == "denied":
                reason[aid] = e.body.get("reason")
        for aid in order:
            pay = payloads[aid]
            a = StagedAction(
                kind=pay.get("kind", "?"), target=pay.get("target", ""),
                content=pay.get("content", pay.get("content_preview", "")),
                created_by=pay.get("author_created_by", pay.get("created_by", "?")),
                destination=_destination_from_body(pay.get("destination")),
                idempotency_key=pay.get("idempotency_key", ""), id=aid)
            a.status = status.get(aid, ActionStatus.STAGED)
            a.approved_by = approver.get(aid)
            a.denial_reason = reason.get(aid)
            self._actions[aid] = a

    # ----- agent side -------------------------------------------------------

    def stage(self, action: StagedAction) -> str:
        # D38: guard the act surface at STAGE time too (only when an Isolation is
        # supplied). A wrong-surface action is refused LOUDLY here — before it can
        # ever be approved and fired. This ADDS a gate; it does not touch the
        # approval/fire authorization below. guard_act raises SurfaceNotAllowed.
        if self.iso is not None:
            self.iso.allow.guard_act(_act_surface_id(action))
        self._actions[action.id] = action
        self.ledger.append(
            kind="staged_action", author=action.created_by,
            body={"action_id": action.id, "kind": action.kind,
                  "target": action.target, "status": action.status.value,
                  # FULL payload persisted (D26) — reconstructable, not a preview
                  "content": action.content,
                  "content_preview": action.content[:280],
                  "content_hash": action.content_hash(),
                  # FULL structured destination persisted (D26, Codex#16) — the
                  # routing metadata must survive a restart, not drop to None
                  "destination": _destination_to_body(action.destination),
                  "idempotency_key": action.idempotency_key,
                  "created_by": action.created_by},
            tags=("outbox", action.kind),
        )
        return action.id

    def pending(self) -> list[StagedAction]:
        """The human's correction surface: everything waiting for a decision."""
        return [a for a in self._actions.values() if a.status == ActionStatus.STAGED]

    def get(self, action_id: str) -> Optional[StagedAction]:
        return self._actions.get(action_id)

    # ----- human side -------------------------------------------------------

    def _require_approver(self, human: str, created_by: str) -> None:
        """The independence gate for the human seat. Two ways it can be defeated,
        both closed here:
          1. A blank / same-as-maker id (case/space disguise) — refused.
          2. A homoglyph of the maker's id (Cyrillic 'witnеss' for 'witness').
             same_identity does NOT fold confusables (that would merge distinct
             real names like мир/mir), so it would MISS the homoglyph. The fix is
             the same ASCII-identity allowlist verify._guard_independence uses:
             an approver id must reduce to a valid ASCII identifier, or it is
             REFUSED — an exotic id is never reasoned about."""
        try:
            require_identity(human, "approver")
        except InvalidIdentityError as e:
            raise UnapprovedFireError(
                f"approval refused: {e}. The human seat requires a plain ASCII "
                "identity — an exotic/homoglyph id is refused, not guessed "
                "(that was a self-approval bypass of refusal #5).")
        if same_identity(human, created_by):
            raise UnapprovedFireError(
                "the staging agent cannot approve or deny its own action — "
                "approval is the human seat (disguised self-approval was a live "
                "bypass found in review; identity comparison is normalized now)")

    def _require_status(self, a: StagedAction, allowed: tuple, verb: str) -> None:
        """Lifecycle-state gate (FableG8): a decided action is not re-decided. Only
        a STAGED action may be approved; a DENIED / FIRED action can never be
        resurrected to approved and fired. Without this, `deny → approve → fire`
        was a live resurrection (both the web guard and the library missed it)."""
        if a.status not in allowed:
            raise UnapprovedFireError(
                f"action {a.id} is {a.status.value}, not "
                f"{'/'.join(s.value for s in allowed)} — cannot {verb} (a decided "
                "action is not resurrected: no deny→approve, no re-approve after fire)")

    def approve(self, action_id: str, human: str) -> None:
        a = self._require(action_id)
        self._require_approver(human, a.created_by)
        self._require_status(a, (ActionStatus.STAGED,), "approve")
        # persist FIRST, then mutate the cache (Codex#2): a failed approval append
        # must never leave a fireable action with zero durable yes. On persistence
        # failure the cache is rolled back, and fire() re-derives approval from the
        # ledger regardless — the cache is never the authority.
        prev_status, prev_approved = a.status, a.approved_by
        a.status = ActionStatus.APPROVED
        a.approved_by = human
        try:
            self._log(a, human, "approved", approved_by=human)
        except BaseException:
            a.status, a.approved_by = prev_status, prev_approved
            raise

    def deny(self, action_id: str, human: str, reason: str) -> None:
        a = self._require(action_id)
        self._require_approver(human, a.created_by)
        # denial is a pre-world act: allowed while STAGED or (cancelling) APPROVED,
        # never after firing/fired/unknown (that outcome is a reconcile, not a deny).
        self._require_status(a, (ActionStatus.STAGED, ActionStatus.APPROVED), "deny")
        prev_status, prev_reason = a.status, a.denial_reason
        a.status = ActionStatus.DENIED
        a.denial_reason = reason
        try:
            self._log(a, human, "denied", reason=reason)
        except BaseException:
            a.status, a.denial_reason = prev_status, prev_reason
            raise

    # ----- the world side ----------------------------------------------------

    def _ledger_state(self, action_id: str) -> tuple:
        """Reconstruct the LATEST authoritative lifecycle state for one action by
        folding its staged_action events in ledger order — the source of truth for
        authorization (Codex#1/#2). fire() authorizes from THIS, never from the
        instance cache: a stale Outbox that still holds a cached APPROVED must not
        fire an action another process has since denied or already fired.

        A `reconcile(fired=False)` folds to APPROVED — CLEARING an in-flight block
        so exactly one clean retry is allowed; `reconcile(fired=True)` folds to
        FIRED and stays blocked. Returns (status, approver)."""
        status: Optional[ActionStatus] = None
        approver: Optional[str] = None
        for e in self.ledger.entries():
            if e.kind != "staged_action" or e.body.get("action_id") != action_id:
                continue
            st = self._event_status(e.body)
            if st is not None:
                status = st
            if e.body.get("event") == "approved":
                approver = self._event_approver(e)
        return status, approver

    def fire(self, action_id: str, executor: Callable[[StagedAction], None]) -> None:
        """Execute an APPROVED action via the provided executor, exactly once.
        Records a `firing` intent BEFORE calling the world and refuses to re-fire
        an action already firing/fired — so a crash-then-retry never double-sends.
        On an executor error the action lands `unknown` (the remote may have
        received it); a human reconciles. The executor is handed the idempotency
        key so a dedup-aware destination gets true exactly-once."""
        a = self._require(action_id)
        # The check-then-write-intent is the critical section: two firers reading
        # `_fire_block` before either writes `firing` could both proceed (a TOCTOU
        # double-fire under true simultaneity — the verifier's caveat 1). Serialize
        # it with an advisory file lock so two processes on the SAME machine (e.g.
        # the harness and a second firer) can't both pass. The executor runs OUTSIDE
        # the lock (never hold a lock across a network call). Cross-machine exactly-
        # once still needs the transactional ledger (Codex High 6); by design only
        # the harness fires, so this is defense-in-depth.
        with self._fire_lock():
            # Authorize from the LEDGER (the source of truth), NEVER the instance
            # cache (Codex#1/#2): re-derive the latest authoritative lifecycle state
            # under the lock. A stale cached APPROVED, a denial another process
            # recorded, and a failed approval append all resolve correctly here.
            status, approver = self._ledger_state(action_id)
            # idempotency FIRST: an action already firing/fired/unknown is refused
            # outright, so a crash-then-retry (or a fire on UNKNOWN awaiting
            # reconcile) can't double-send. reconcile(fired=False) folds back to
            # APPROVED, clearing this for one clean retry.
            if status in (ActionStatus.FIRING, ActionStatus.FIRED, ActionStatus.UNKNOWN):
                raise DoubleFireError(
                    f"action {action_id} is '{status.value}' in the ledger — refusing to "
                    "fire again (a side effect that may have reached the world is not "
                    "blindly retried; reconcile the outcome instead)")
            if status != ActionStatus.APPROVED:
                raise UnapprovedFireError(
                    f"action {action_id} is {status.value if status else 'unstaged'} in "
                    "the ledger, not approved — nothing fires without a human's durable yes")
            # sync the cache to the ledger truth before recording intent
            a.approved_by = approver or a.approved_by
            # durable INTENT before the side effect (so a crash here is recoverable)
            a.status = ActionStatus.FIRING
            self._log(a, a.approved_by or "?", "firing", idempotency_key=a.idempotency_key)
        # 2) call the world
        try:
            executor(a)
        except BaseException as ex:
            # ambiguous: the remote may or may not have received it. Durably UNKNOWN,
            # never silently retried — a human reconciles.
            a.status = ActionStatus.UNKNOWN
            self._log(a, a.approved_by or "?", "fire_unknown",
                      idempotency_key=a.idempotency_key, error=repr(ex)[:300])
            raise FireOutcomeUnknown(
                f"executor for {action_id} raised after the firing intent was "
                f"recorded — outcome UNKNOWN, a human must reconcile: {ex!r}") from ex
        # 3) success
        a.status = ActionStatus.FIRED
        self._log(a, a.approved_by or "?", "fired", idempotency_key=a.idempotency_key)

    def reconcile(self, action_id: str, human: str, fired: bool,
                  note: str = "") -> None:
        """A human resolves an ambiguous action: `fired=True` (it did reach the
        world → mark fired, do not resend) or `fired=False` (it did not → back to
        approved, safe to fire once more). Human-gated like every seat before the
        world.

        Accepts both `unknown` (the executor raised) AND `firing` (the process was
        hard-killed mid-send, so no exception ever ran and the action is stuck
        in-flight — safe, because `fire()` refuses it, but a human still needs a way
        to resolve it). Without the `firing` case a power-loss-mid-send action had
        no public path forward (the verifier's caveat 2)."""
        a = self._require(action_id)
        if a.status not in (ActionStatus.UNKNOWN, ActionStatus.FIRING):
            raise UnapprovedFireError(
                f"action {action_id} is {a.status.value}, not unknown/firing — "
                "nothing to reconcile")
        # SAME independence gate as approval (Codex#3): reconciliation is a human
        # seat. The staging agent cannot reconcile its OWN ambiguous send — that
        # was a live self-resolution that let a retry double-send. Authenticated
        # ASCII human, and maker != reconciler; fail-closed if we cannot verify.
        self._require_approver(human, a.created_by)
        a.status = ActionStatus.FIRED if fired else ActionStatus.APPROVED
        self._log(a, human, "reconciled", reconciled_fired=fired, note=note)

    # ----- internals ---------------------------------------------------------

    @contextlib.contextmanager
    def _fire_lock(self):
        """Advisory exclusive lock over a sidecar `<ledger>.firelock`, held only
        for the check-then-write-intent critical section. POSIX-only; degrades to
        a no-op where fcntl is absent (the sequential crash-retry guarantee still
        holds without it — the lock only closes the true-simultaneity race)."""
        path = getattr(self.ledger, "path", None)
        if fcntl is None or path is None:
            yield
            return
        lockpath = str(path) + ".firelock"
        f = open(lockpath, "w")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            finally:
                f.close()

    def _require(self, action_id: str) -> StagedAction:
        if action_id not in self._actions:
            raise KeyError(f"unknown staged action: {action_id}")
        return self._actions[action_id]

    def _log(self, a: StagedAction, actor: str, event: str, **extra) -> None:
        self.ledger.append(
            kind="staged_action", author=actor,
            body={"action_id": a.id, "kind": a.kind, "target": a.target,
                  "status": a.status.value, "event": event, **extra},
            tags=("outbox", a.kind, event),
        )
