"""stage.py — stage, don't fire. (DECISIONS.md D10)

"Nothing is ever sent, posted, or applied automatically… correcting, not
creating, is where strategic thinking happens." — DAILY-EMPIRE-PROTOCOL,
2026-07-15

The strongest cross-voice consensus in the whole failure dossier: never let
agent output hit a stakeholder unchecked (Clare's QA gates, Sarah's leak
grievance, Peter's "can't send 90% to a CEO"). And the 2026 security record —
79% prompt-injection success against always-on agents — makes staging the
cheap structural defense: an injected agent can stage garbage, but a human is
between the garbage and the world.

Every transition is a ledger event. Firing an unapproved action raises.
Approval names a human. There is no bypass flag — if you want auto-fire,
you have to fork the file, and the diff will say what you did.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from .clock import TimeGround
from .identity import same_identity
from .ledger import Ledger
from .surfaces import ConversationKey


class ActionStatus(str, Enum):
    STAGED = "staged"
    APPROVED = "approved"
    DENIED = "denied"
    FIRED = "fired"
    EXPIRED = "expired"


class UnapprovedFireError(Exception):
    pass


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
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class Outbox:
    """The one gate between an agent and the world."""

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground
        self._actions: dict[str, StagedAction] = {}

    # ----- agent side -------------------------------------------------------

    def stage(self, action: StagedAction) -> str:
        self._actions[action.id] = action
        self.ledger.append(
            kind="staged_action", author=action.created_by,
            body={"action_id": action.id, "kind": action.kind,
                  "target": action.target, "status": action.status.value,
                  "content_preview": action.content[:280]},
            tags=("outbox", action.kind),
        )
        return action.id

    def pending(self) -> list[StagedAction]:
        """The human's correction surface: everything waiting for a decision."""
        return [a for a in self._actions.values() if a.status == ActionStatus.STAGED]

    # ----- human side -------------------------------------------------------

    def approve(self, action_id: str, human: str) -> None:
        a = self._require(action_id)
        if not human.strip():
            raise UnapprovedFireError("approval requires a named human")
        if same_identity(human, a.created_by):
            raise UnapprovedFireError(
                "the staging agent cannot approve its own action — approval is "
                "the human seat (disguised self-approval was a live bypass "
                "found in review; identity comparison is normalized now)")
        a.status = ActionStatus.APPROVED
        a.approved_by = human
        self._log(a, human, "approved")

    def deny(self, action_id: str, human: str, reason: str) -> None:
        a = self._require(action_id)
        a.status = ActionStatus.DENIED
        a.denial_reason = reason
        self._log(a, human, "denied", reason=reason)

    # ----- the world side ----------------------------------------------------

    def fire(self, action_id: str, executor: Callable[[StagedAction], None]) -> None:
        """Execute an APPROVED action via the provided executor. The executor
        does the actual side effect (post, send, write); the outbox only ever
        hands it approved actions."""
        a = self._require(action_id)
        if a.status != ActionStatus.APPROVED:
            raise UnapprovedFireError(
                f"action {action_id} is {a.status.value}, not approved — "
                "nothing fires without a human's yes")
        executor(a)
        a.status = ActionStatus.FIRED
        self._log(a, a.approved_by or "?", "fired")

    # ----- internals ---------------------------------------------------------

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
