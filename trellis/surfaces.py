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
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from .auth import Principal
from .ledger import Ledger

#: How long a declassification token stays usable. A declassification is a
#: deliberate human act to move ONE excerpt across the boundary; the token is
#: not a standing permission, so it expires. (Policy default — see decisions.)
DEFAULT_DECLASSIFY_TTL = timedelta(hours=1)


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
        never collide into one key.

        Two properties make the encoding one-to-one:
          * (Codex High 7) each field escapes `%` then `_`, so no field contains a
            `_` — the only `__` in the result are the fixed delimiters, and a `__`
            INSIDE a field can never masquerade as one.
          * (Codex High 6) optionality is encoded EXPLICITLY, never by
            substituting a legal value. `"-"` used to be BOTH the missing-value
            sentinel and legal field data, so `human=""` collided with
            `human="-"`, and `thread=None` collided with `ThreadRef(id="-")` —
            a cross-conversation memory-merge risk. Now the thread carries a
            present/absent FLAG and all three of its parts are their own tokens,
            and `human` is emitted verbatim (empty is its own distinct token), so
            those inputs map to distinct keys. The whole ThreadRef is in the key,
            so the same thread id under a different parent no longer conflates."""
        def esc(s: str) -> str:
            # percent-escape everything unsafe (incl. '/'), then '_' — so the
            # result is filesystem-safe AND contains no '_', making the '__'
            # delimiter unambiguous (one-to-one).
            from urllib.parse import quote
            return quote(s or "", safe="").replace("_", "%5F")
        if self.thread is not None:
            thread_tokens = ("1", esc(self.thread.id), esc(self.thread.parent_channel),
                             esc(self.thread.parent_message or ""))
        else:
            thread_tokens = ("0", "", "", "")
        fields = (esc(self.agent), esc(self.surface.value), esc(self.scope),
                  *thread_tokens, esc(self.human))
        return "__".join(fields)

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


def _require_human_authority(approver: Principal) -> str:
    """Return the AUTHENTICATED human's canonical id, or refuse (fail-closed).

    Codex Critical #4: `approved_by` used to be an unauthenticated string, so any
    agent could mint a DM→public token merely by naming itself
    (`approved_by="witness-agent"`). Declassification is a HUMAN-only authority.
    surfaces.py is stdlib-only and cannot itself authenticate, so it requires an
    object carrying a VERIFIED principal from the trusted boundary (auth.Principal
    with `authenticated=True`, which only an Authenticator that verified a secret
    can mint). A bare identity string — an agent naming itself — has no
    `.authenticated`, so it is STRUCTURALLY refused, not reasoned about."""
    if isinstance(approver, (str, bytes)):
        raise PrivacyBoundaryError(
            "declassification requires an AUTHENTICATED human principal, not a "
            "caller-supplied name — an agent cannot authorize declassification")
    if getattr(approver, "authenticated", False) is not True:
        raise PrivacyBoundaryError(
            "declassification requires an authenticated human principal "
            "(an unauthenticated or self-asserted identity is refused)")
    pid = getattr(approver, "id", None)
    if not isinstance(pid, str) or not pid.strip():
        raise PrivacyBoundaryError("authenticated principal carries no usable id")
    return pid.strip()


def declassify(ledger: Ledger, src: ConversationKey, dst: ConversationKey,
               approver: Principal, reason: str, *,
               ttl: timedelta = DEFAULT_DECLASSIFY_TTL) -> str:
    """A human explicitly moves something across the privacy boundary.
    The act is a ledger event — auditable forever. Agents cannot call this on
    their own authority; `approver` must be an authenticated human principal.

    The token is DECLASSIFYING-only, EXPIRING, and SINGLE-USE (FableL2):
      * DIRECTION — the only legitimate crossing is toward a strictly MORE PUBLIC
        surface. Any equal-or-more-private target is refused: `can_flow` already
        permits that path, so calling declassify for it is a category error and a
        would-be over-broad grant.
      * EXPIRY — the token carries `expires_at` from the injected ledger clock
        (never a naked now()); it is a one-shot act, not a standing permission.
      * SINGLE-USE — enforced at redemption in `flow_with_token`."""
    approver_id = _require_human_authority(approver)
    if not reason.strip():
        raise PrivacyBoundaryError("declassification requires a stated reason")
    if dst.privacy_rank() >= src.privacy_rank():
        raise PrivacyBoundaryError(
            f"declassification only crosses toward a strictly MORE PUBLIC surface; "
            f"{src.surface.value} → {dst.surface.value} does not declassify "
            "(that path, if legitimate, needs no token — see can_flow)")
    now = ledger.ground.now()
    entry = ledger.append(
        kind="declassification",
        author=approver_id,
        body={
            "from": src.storage_key(),
            "to": dst.storage_key(),
            "reason": reason,
            "token": uuid.uuid4().hex[:12],
            "expires_at": (now + ttl).isoformat(),
        },
        tags=("privacy", src.surface.value, dst.surface.value),
    )
    return entry.body["token"]


def flow_with_token(ledger: Ledger, src: ConversationKey, dst: ConversationKey,
                    token: str) -> bool:
    """Redeem a declassification token for THIS exact flow. Returns True at most
    once per token (single-use): a match that is unexpired and not already spent
    records a `declassification_use` event and returns True; every later call —
    reused token, expired token, or wrong src/dst — returns False. No silent
    reuse, no infinite lifetime (FableL2)."""
    src_key, dst_key = src.storage_key(), dst.storage_key()
    now = ledger.ground.now()
    spent = {e.body.get("token") for e in ledger.entries()
             if e.kind == "declassification_use"}
    for e in ledger.current("declassification"):
        b = e.body
        if not (b.get("token") == token
                and b.get("from") == src_key and b.get("to") == dst_key):
            continue
        if token in spent:
            return False                                # already redeemed once
        expires_at = b.get("expires_at")
        if expires_at is not None and now >= datetime.fromisoformat(expires_at):
            return False                                # expired — re-declassify
        ledger.append(
            kind="declassification_use",
            author=e.author,        # the human whose act this consumes
            body={"token": token, "from": src_key, "to": dst_key},
            tags=("privacy", src.surface.value, dst.surface.value),
        )
        return True
    return False
