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
from .identity import (InvalidIdentityError, is_effectively_blank,
                       require_identity, same_identity)
from .ledger import Ledger
from .surfaces import ConversationKey


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


class Outbox:
    """The one gate between an agent and the world — durable and idempotent."""

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground
        self._actions: dict[str, StagedAction] = {}
        self._load()   # reconstruct from the ledger — survive a restart (D26)

    # ----- reconstruction (the ledger is the source of truth) ----------------

    def _load(self) -> None:
        """Rebuild every action's payload + current status from the ledger's
        staged_action events. The payload comes from the `staged` event; the
        status from the latest event per action_id (which the web UI also writes,
        so there is no split-brain)."""
        payloads: dict[str, dict] = {}
        latest: dict[str, tuple] = {}   # action_id -> (write_time, status, body)
        for e in self.ledger.entries():
            if e.kind != "staged_action":
                continue
            aid = e.body.get("action_id")
            if not aid:
                continue
            ev = e.body.get("event", "staged")
            if ev in ("staged", None) and e.body.get("kind"):
                payloads[aid] = e.body
            prev = latest.get(aid)
            if prev is None or e.stamp.write_time >= prev[0]:
                latest[aid] = (e.stamp.write_time, e.body.get("status", "staged"), e.body)
        for aid, pay in payloads.items():
            wt, status, latest_body = latest.get(aid, (None, "staged", pay))
            a = StagedAction(
                kind=pay.get("kind", "?"), target=pay.get("target", ""),
                content=pay.get("content", pay.get("content_preview", "")),
                created_by=pay.get("author_created_by", pay.get("created_by", "?")),
                idempotency_key=pay.get("idempotency_key", ""), id=aid)
            try:
                a.status = ActionStatus(status)
            except ValueError:
                a.status = ActionStatus.STAGED
            a.approved_by = latest_body.get("approved_by") or latest_body.get("by")
            a.denial_reason = latest_body.get("reason")
            self._actions[aid] = a

    # ----- agent side -------------------------------------------------------

    def stage(self, action: StagedAction) -> str:
        self._actions[action.id] = action
        self.ledger.append(
            kind="staged_action", author=action.created_by,
            body={"action_id": action.id, "kind": action.kind,
                  "target": action.target, "status": action.status.value,
                  # FULL payload persisted (D26) — reconstructable, not a preview
                  "content": action.content,
                  "content_preview": action.content[:280],
                  "content_hash": action.content_hash(),
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

    def approve(self, action_id: str, human: str) -> None:
        a = self._require(action_id)
        self._require_approver(human, a.created_by)
        a.status = ActionStatus.APPROVED
        a.approved_by = human
        self._log(a, human, "approved", approved_by=human)

    def deny(self, action_id: str, human: str, reason: str) -> None:
        a = self._require(action_id)
        self._require_approver(human, a.created_by)
        a.status = ActionStatus.DENIED
        a.denial_reason = reason
        self._log(a, human, "denied", reason=reason)

    # ----- the world side ----------------------------------------------------

    def _fire_block(self, action_id: str) -> Optional[str]:
        """The idempotency check — from the LEDGER, not just memory. Returns the
        blocking state ('firing' in-flight, or 'fired' done) if this action must
        NOT be fired, else None. A crash after the firing intent leaves 'firing'
        on record → blocked (no blind retry of a side effect that may have reached
        the world). A human `reconcile(fired=False)` — 'it did NOT go out' — CLEARS
        the block, so exactly one clean retry is allowed; `reconcile(fired=True)`
        settles it as fired (stays blocked)."""
        state: Optional[str] = None
        for e in self.ledger.entries():
            if e.kind != "staged_action" or e.body.get("action_id") != action_id:
                continue
            ev = e.body.get("event")
            if ev in ("firing", "fired"):
                state = ev
            elif ev == "reconciled":
                state = "fired" if e.body.get("reconciled_fired") else None
        return state

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
            # idempotency FIRST: an action already firing/fired is refused outright,
            # so a crash-then-retry (or a fire on UNKNOWN awaiting reconcile) can't
            # double-send. reconcile(fired=False) clears this for one clean retry.
            prior = self._fire_block(action_id)
            if prior is not None:
                raise DoubleFireError(
                    f"action {action_id} already recorded a '{prior}' — refusing to fire "
                    "again (a side effect that may have reached the world is not blindly "
                    "retried; reconcile the outcome instead)")
            if a.status != ActionStatus.APPROVED:
                raise UnapprovedFireError(
                    f"action {action_id} is {a.status.value}, not approved — "
                    "nothing fires without a human's yes")
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
        if is_effectively_blank(human):
            raise UnapprovedFireError("reconciliation names the human who checked the world")
        require_identity(human, "reconciler")
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
