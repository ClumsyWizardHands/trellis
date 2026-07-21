"""surfaces.py — threads are substrate; privacy lives in the key. (DECISIONS.md D7)

Failure record this answers (loop-provenance audit, 2026-06-10):
  * sessions keyed on user_id alone — DMs and all channels conflated
  * a public-channel synthesis filed as a DM (warm filenames hardcoded '-dm-')
  * threads not modeled: a thread was just another channel_id, no parent link
  * "our agents are still leaking private chief discussions into other
    channels… stop that from happening again, immediately." — Sarah, 2026-05-01

The fix is structural: a conversation is keyed on FOUR parts —
(agent, surface, thread, human) — and information flow between keys is checked
by the key itself. A DM-keyed item cannot flow to a channel-keyed context
without an explicit, logged declassification by a human.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .ledger import Ledger


class Surface(str, Enum):
    DM = "dm"            # private, one human
    CHANNEL = "channel"  # shared, many eyes
    THREAD = "thread"    # shared, scoped under a channel message
    FILE = "file"        # a document surface (shared drive, vault)
    CLI = "cli"          # operator's terminal — private to the operator


#: privacy rank: information may flow toward MORE private, never toward less,
#: without declassification. (dm is most private; channel least.)
_PRIVACY_RANK = {
    Surface.DM: 3,
    Surface.CLI: 3,
    Surface.FILE: 2,
    Surface.THREAD: 1,
    Surface.CHANNEL: 0,
}


class PrivacyBoundaryError(Exception):
    """Raised when content tries to cross toward a less-private surface
    without a logged declassification."""


@dataclass(frozen=True)
class ThreadRef:
    """A thread with its parent modeled — the audit's missing link."""
    id: str
    parent_channel: str
    parent_message: Optional[str] = None


@dataclass(frozen=True)
class ConversationKey:
    agent: str
    surface: Surface
    scope: str                       # channel id, thread id, file path, "cli"
    human: str                       # the counterpart human ("" for broadcast surfaces)
    thread: Optional[ThreadRef] = None

    def storage_key(self) -> str:
        """Filesystem/session-safe key, INJECTIVELY encoded. Distinct tuples can
        never collide into one key — the user_id-only conflation is
        unrepresentable, and (Codex High 7) a `__` INSIDE a field can no longer
        masquerade as the delimiter. Each field escapes `%` then `_`, so the only
        `__` in the result is a real delimiter — the encoding is reversible and
        one-to-one. Example that used to collide, now distinct:
          scope='s',   thread='a__b'  → …__s__a%5F%5Fb__…
          scope='s__a', thread='b'    → …__s%5F%5Fa__b__…"""
        def esc(s: str) -> str:
            # percent-escape everything unsafe (incl. '/'), then '_' — so the
            # result is filesystem-safe AND contains no '_', making the '__'
            # delimiter unambiguous (one-to-one).
            from urllib.parse import quote
            return quote(s or "", safe="").replace("_", "%5F")
        t = self.thread.id if self.thread else "-"
        return "__".join(esc(f) for f in
                         (self.agent, self.surface.value, self.scope, t, self.human or "-"))

    def privacy_rank(self) -> int:
        return _PRIVACY_RANK[self.surface]


def can_flow(src: ConversationKey, dst: ConversationKey) -> bool:
    """May content recorded under `src` be used in a context keyed `dst`?

    Toward equal-or-more private: yes. Toward less private: no — that path
    requires declassify(). Same-surface different-human DMs never flow."""
    # Private surfaces (DM, CLI) belong to ONE human. Content never crosses
    # between different humans' private surfaces — DM→DM, DM→CLI, CLI→DM alike.
    # (The CLI↔DM cross-human path was a live leak found in review.)
    _PRIVATE = {Surface.DM, Surface.CLI}
    if (src.surface in _PRIVATE and dst.surface in _PRIVATE
            and src.human != dst.human):
        return False
    return dst.privacy_rank() >= src.privacy_rank()


def guard_flow(src: ConversationKey, dst: ConversationKey) -> None:
    if not can_flow(src, dst):
        raise PrivacyBoundaryError(
            f"content from {src.surface.value}:{src.scope} (human={src.human or '-'}) "
            f"may not flow to {dst.surface.value}:{dst.scope} without an explicit "
            "declassification by a human (see declassify)")


def declassify(ledger: Ledger, src: ConversationKey, dst: ConversationKey,
               approved_by: str, reason: str) -> str:
    """A human explicitly moves something across the privacy boundary.
    The act is a ledger event — auditable forever. Agents cannot call this
    on their own authority; `approved_by` must name a human."""
    if not approved_by.strip():
        raise PrivacyBoundaryError("declassification requires a named human approver")
    if not reason.strip():
        raise PrivacyBoundaryError("declassification requires a stated reason")
    entry = ledger.append(
        kind="declassification",
        author=approved_by,
        body={
            "from": src.storage_key(),
            "to": dst.storage_key(),
            "reason": reason,
            "token": uuid.uuid4().hex[:12],
        },
        tags=("privacy", src.surface.value, dst.surface.value),
    )
    return entry.body["token"]


def flow_with_token(ledger: Ledger, src: ConversationKey, dst: ConversationKey,
                    token: str) -> bool:
    """Check a declassification token covers this flow."""
    for e in ledger.current("declassification"):
        if (e.body.get("token") == token
                and e.body.get("from") == src.storage_key()
                and e.body.get("to") == dst.storage_key()):
            return True
    return False
