"""isolation.py — trellis touches only its OWN surfaces. (many-agent estate)

Alex runs many agents on one machine, several sharing a server-wide messaging
bridge that can see every channel. The refusal here is STRUCTURAL, in the spirit
of surfaces.py ("privacy lives in the key"): trellis authenticates as its OWN
identity and may only read from / act on an EXPLICIT allowlist of surface ids. A
surface not on the list is not trellis's — it is refused, not filtered by
convention. A bug cannot make trellis read another agent's channel or post under
another agent's name, because it was never granted them.

Two separate allowlists, on purpose:
  * READ  — what trellis may ingest. A shared bridge WILL hand over other agents'
            channels; `filter_readable` silently keeps only trellis's own, so a
            noisy source can't crash ingestion but also can't leak in.
  * ACT   — where trellis may send. Acting on the wrong surface is irreversible,
            so this side never silently drops: `guard_act` RAISES. Refuse loudly.

READ and ACT are deliberately not the same set — trellis may watch a channel it
must never post into, and vice versa.

Credentials are referenced by ENV VAR NAME only. The secret value is fetched on
demand, never stored on a config object, never logged, never written to the
ledger. trellis never falls back to another agent's credentials — a missing one
fails loud.

This module is the OUTER gate (may trellis touch this surface at all?); it
composes with surfaces.py's INNER flow rules (how information moves between
surfaces once admitted). Zero-dependency, fully offline, fully testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, TypeVar

from .ledger import Entry, Ledger
from .ingest import DiscordMessage, ingest_discord

T = TypeVar("T")


class SurfaceNotAllowed(Exception):
    """trellis was asked to touch a surface outside its allowlist."""


class CredentialMissing(Exception):
    """A required credential env var is unset — trellis refuses to run rather
    than fall back to another identity's secret."""


@dataclass(frozen=True)
class AgentIdentity:
    """Who trellis is on the wire.

    `name` stamps every ingested item (the ConversationKey.agent field) and every
    action's author, so the ledger records which agent touched what. `token_env`
    NAMES the environment variable holding the credential; the value is fetched on
    demand via `credential()` and never held on the object.
    """
    name: str = "trellis"
    token_env: str = "TRELLIS_DISCORD_TOKEN"

    def credential(self) -> str:
        tok = os.environ.get(self.token_env, "")
        if not tok.strip():
            raise CredentialMissing(
                f"identity {self.name!r}: credential env ${self.token_env} is unset — "
                "trellis will not fall back to another agent's credentials")
        return tok


@dataclass(frozen=True)
class SurfaceAllowlist:
    """The explicit surface ids trellis may touch. Ids are opaque strings (Discord
    channel/thread ids, Drive folder ids). Empty set = touch NOTHING — the safe
    default, so an unconfigured trellis is inert, not omnivorous."""
    read: frozenset[str] = frozenset()
    act: frozenset[str] = frozenset()

    def may_read(self, surface_id: str) -> bool:
        return surface_id in self.read

    def may_act(self, surface_id: str) -> bool:
        return surface_id in self.act

    def guard_act(self, surface_id: str) -> None:
        """Refuse, loudly, to act on a non-allowlisted surface. Never silently
        drops — sending to the wrong place is irreversible."""
        if surface_id not in self.act:
            raise SurfaceNotAllowed(
                f"act refused: {surface_id!r} is not in trellis's act allowlist "
                f"({len(self.act)} allowed) — trellis will not send there")

    def guard_read(self, surface_id: str) -> None:
        """Assert a single id is readable — use as a belt-and-suspenders check
        where the caller believes it already scoped the request."""
        if surface_id not in self.read:
            raise SurfaceNotAllowed(
                f"read refused: {surface_id!r} is not in trellis's read allowlist "
                f"({len(self.read)} allowed) — it belongs to another agent or was "
                "never granted")

    def filter_readable(self, items: Iterable[T],
                        surface_of: Callable[[T], str]) -> Iterator[T]:
        """Keep only items on a READ-allowlisted surface; drop the rest silently.
        This is how a shared, server-wide bridge is consumed safely: whatever
        other agents' traffic it hands over simply never passes this gate."""
        for it in items:
            if surface_of(it) in self.read:
                yield it

    @staticmethod
    def from_env(read_env: str = "TRELLIS_READ_SURFACES",
                 act_env: str = "TRELLIS_ACT_SURFACES") -> "SurfaceAllowlist":
        """Build from comma-separated env vars, so no surface id is hardcoded.
        Unset/empty → empty set → touch nothing."""
        def parse(name: str) -> frozenset[str]:
            return frozenset(x.strip() for x in os.environ.get(name, "").split(",")
                             if x.strip())
        return SurfaceAllowlist(read=parse(read_env), act=parse(act_env))


@dataclass(frozen=True)
class Isolation:
    """trellis's identity + its allowlist, together. The single object a connector
    consults before it reads or sends."""
    identity: AgentIdentity = field(default_factory=AgentIdentity)
    allow: SurfaceAllowlist = field(default_factory=SurfaceAllowlist)

    @staticmethod
    def from_env() -> "Isolation":
        return Isolation(identity=AgentIdentity(), allow=SurfaceAllowlist.from_env())


def _discord_surface(m: DiscordMessage) -> str:
    """The id a Discord message is filed under for allowlisting — the thread if
    threaded, else the channel."""
    return m.thread_id or m.channel


def ingest_scoped_discord(ledger: Ledger, messages: Iterable[DiscordMessage],
                          iso: Isolation,
                          surface_of: Callable[[DiscordMessage], str] = _discord_surface
                          ) -> list[Entry]:
    """Ingest ONLY the messages on trellis's read-allowlisted surfaces, stamped as
    trellis. A batch mixing trellis's channel with another agent's channel lands
    only trellis's in the ledger — the others never reach it. This is the
    'separate all other agents from trellis' guarantee, enforced at ingest."""
    kept = list(iso.allow.filter_readable(messages, surface_of))
    return ingest_discord(ledger, kept, agent=iso.identity.name)
