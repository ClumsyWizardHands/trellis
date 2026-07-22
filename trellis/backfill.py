"""backfill.py — catch up on Discord HISTORY, then hand off to the tick poll.

The onboarding ritual's first appetite is the record that already exists: every
read-allowlisted channel's history, oldest→newest, ridden through the same
idempotent spine the live poll uses (D31), scoped by the same D30 allowlist. This
module is the thin pagination loop the live client was missing:

  * OLDEST-FIRST — the first page of an uncursored channel starts at snowflake
    "0" (the true beginning of history), and each page's `after=` cursor walks
    forward, so the ledger ingests the past in the order it happened.
  * ONE CURSOR CONTRACT — progress is persisted as the SAME ledger event the
    live poll reads (`runner.POLL_CURSOR_KIND`), so the handoff is structural:
    the moment backfill catches up, the next `DiscordPoll.poll()` resumes from
    exactly the message backfill last saw. No second cursor to drift.
  * BOUNDED AND RESUMABLE — each run fetches at most `max_messages_per_run`
    messages, so a tick stays a tick; a restart folds the cursor back off the
    ledger and continues. A rate limit (`DiscordRateLimited`) stops THAT surface
    for the run and surfaces `retry_after` — the runner decides when to try
    again; nothing busy-loops.
  * HONEST STATE — per-surface progress lands as `discord_backfill` entries
    (in_progress / caught_up, with counts), so "did we actually read the
    history?" is a ledger query, not a hope.

Isolation is not re-implemented here: every admitted message goes through
`ingest_scoped_discord_idempotent` (D30 allowlist + D32 thread admission +
idempotent markers), and a non-allowlisted surface is never even fetched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .clock import TimeGround
from .discord_api import DiscordAPIError, DiscordRateLimited
from .isolation import Isolation, ingest_scoped_discord_idempotent
from .ledger import Ledger
from .runner import POLL_CURSOR_KIND, PollSurface

#: per-surface backfill state on the ledger — the honest progress record.
BACKFILL_STATE_KIND = "discord_backfill"

#: the ledgered record of a guild-wide surface discovery (D40).
DISCOVERY_KIND = "surface_discovery"

#: Discord channel types that carry readable text history: 0 = guild text,
#: 5 = announcement. Voice/forum/category/stage are skipped (counted, not eaten).
GUILD_TEXT_TYPES = frozenset({0, 5})

#: the cursor that means "start from the very beginning of the channel" —
#: Discord snowflakes are positive, so `after=0` pages from the oldest message.
BEGINNING = "0"


@dataclass
class SurfaceBackfillReport:
    channel_id: str
    fetched: int = 0
    admitted: int = 0
    dropped: int = 0
    pages: int = 0
    caught_up: bool = False
    error: Optional[str] = None
    retry_after: Optional[float] = None


@dataclass
class BackfillReport:
    surfaces: List[SurfaceBackfillReport] = field(default_factory=list)
    budget_exhausted: bool = False

    @property
    def all_caught_up(self) -> bool:
        return bool(self.surfaces) and all(s.caught_up for s in self.surfaces)

    def to_body(self) -> dict:
        return {
            "surfaces": [{
                "channel": s.channel_id, "fetched": s.fetched,
                "admitted": s.admitted, "dropped": s.dropped, "pages": s.pages,
                "caught_up": s.caught_up, "error": s.error,
                "retry_after": s.retry_after,
            } for s in self.surfaces],
            "budget_exhausted": self.budget_exhausted,
            "all_caught_up": self.all_caught_up,
        }


@dataclass
class DiscoveryResult:
    """What a guild sweep found: the surfaces trellis can actually see (its
    derived read scope), the channels it was refused (recorded, not silent),
    and the channel types it does not read."""
    guild: str
    surfaces: List[PollSurface] = field(default_factory=list)
    no_access: List[dict] = field(default_factory=list)
    skipped_types: List[dict] = field(default_factory=list)

    @property
    def read_ids(self) -> frozenset:
        return frozenset(s.channel_id for s in self.surfaces)


def discover_guild_read_surfaces(client, ledger: Ledger, guild_id: str,
                                 author: str = "trellis-discover",
                                 now: Optional[datetime] = None,
                                 probe: bool = True) -> DiscoveryResult:
    """Derive the READ scope from Discord itself (D40, Alex 2026-07-22):
    trellis reads everything its OWN bot identity can see in the server —
    every public channel plus every private one it was invited into. The grant
    lives where the surfaces live: adding/removing the bot from a channel in
    Discord IS the allowlist edit; no hand-typed id list to drift.

    Each text channel is PROBED with a one-message fetch, because the channel
    list includes private channels the bot cannot open — a refusal (403) files
    the channel under `no_access`, honestly recorded, never silently retried
    every tick. The whole discovery lands on the ledger as one
    `surface_discovery` entry, so "what does trellis think it may read, and
    why?" is a query. D30's machinery is unchanged: the discovered ids become
    the Isolation allowlist; nothing downstream trusts this list blindly."""
    channels = client.list_guild_channels(guild_id)
    res = DiscoveryResult(guild=guild_id)
    for c in sorted(channels, key=lambda c: c.get("id", "")):
        if c.get("type") not in GUILD_TEXT_TYPES:
            res.skipped_types.append({"id": c.get("id"), "name": c.get("name"),
                                      "type": c.get("type")})
            continue
        if probe:
            try:
                client.fetch_messages(c["id"], limit=1,
                                      channel_name=c.get("name", ""))
            except DiscordRateLimited:
                pass    # unknown, not refused — include; the poll sorts it out
            except DiscordAPIError as e:
                res.no_access.append({"id": c.get("id"), "name": c.get("name"),
                                      "why": str(e)})
                continue
        res.surfaces.append(PollSurface(channel_id=c["id"],
                                        channel_name=c.get("name", "")))
    ledger.append(
        kind=DISCOVERY_KIND, author=author,
        body={"guild": guild_id,
              "readable": [{"id": s.channel_id, "name": s.channel_name}
                           for s in res.surfaces],
              "no_access": res.no_access,
              "skipped_types": res.skipped_types},
        event_time=now, tags=("discord", "discovery", guild_id))
    return res


class DiscordBackfill:
    """Walk each read-allowlisted surface's history forward until caught up.

    Safe to call every tick: once a surface is caught up (an empty page), the
    live poll's cursor already points at its newest message and this class only
    re-checks the recorded state — it does not re-fetch history."""

    def __init__(self, client, iso: Isolation, registry, ledger: Ledger,
                 ground: Optional[TimeGround] = None,
                 surfaces: Optional[List[PollSurface]] = None,
                 author: str = "trellis-backfill", page_limit: int = 100,
                 max_messages_per_run: int = 1000, ignore_bot_self: bool = True):
        self.client = client
        self.iso = iso
        self.registry = registry
        self.ledger = ledger
        self.ground = ground or ledger.ground
        if surfaces is None:
            surfaces = [PollSurface(cid) for cid in sorted(iso.allow.read)]
        self.surfaces = list(surfaces)
        self.author = author
        self.page_limit = page_limit
        self.max_messages_per_run = max_messages_per_run
        self.ignore_bot_self = ignore_bot_self

    # ----- ledger folds ------------------------------------------------------

    def _readable(self, surf: PollSurface) -> bool:
        """Same admission the live poll uses (D30 + the D32 parent-channel
        fallback for threads) — a surface outside the allowlist is never fetched."""
        allow = self.iso.allow
        if surf.is_thread:
            return allow.may_read(surf.channel_id) or bool(
                surf.parent_channel and allow.may_read(surf.parent_channel))
        return allow.may_read(surf.channel_id)

    def _cursors(self) -> dict:
        """Latest persisted cursor per channel — the SAME fold DiscordPoll uses,
        because it is the same event kind. One cursor contract, no drift."""
        cur: dict = {}
        for e in self.ledger.entries():
            if e.kind != POLL_CURSOR_KIND:
                continue
            ch = e.body.get("channel", "")
            c = e.body.get("cursor", "")
            if ch and c:
                cur[ch] = c
        return cur

    def caught_up_surfaces(self) -> set:
        """Channel ids whose LATEST backfill state says caught_up — folded from
        the ledger so a restart knows what is already done."""
        state: dict = {}
        for e in self.ledger.entries():
            if e.kind != BACKFILL_STATE_KIND:
                continue
            ch = e.body.get("channel", "")
            if ch:
                state[ch] = bool(e.body.get("caught_up"))
        return {ch for ch, done in state.items() if done}

    def _bot_id(self) -> str:
        if not self.ignore_bot_self:
            return ""
        try:
            return self.client.current_user_id() or ""
        except DiscordAPIError:
            return ""

    # ----- the run -----------------------------------------------------------

    def run(self, now: Optional[datetime] = None) -> BackfillReport:
        """One bounded backfill pass over every not-yet-caught-up surface.
        Records per-surface state + an overall summary on the ledger. A re-run
        after catch-up is a cheap no-op (state fold, no fetches)."""
        report = BackfillReport()
        done = self.caught_up_surfaces()
        cursors = self._cursors()
        bot_id = self._bot_id()
        budget = self.max_messages_per_run

        for surf in self.surfaces:
            if not self._readable(surf):
                continue
            cid = surf.channel_id
            sr = SurfaceBackfillReport(channel_id=cid)
            if cid in done:
                sr.caught_up = True
                report.surfaces.append(sr)
                continue
            if budget <= 0:
                report.budget_exhausted = True
                report.surfaces.append(sr)
                continue
            cursor = cursors.get(cid) or BEGINNING
            budget = self._walk_surface(surf, cursor, budget, bot_id, sr, now)
            report.surfaces.append(sr)
            # per-surface state is a ledger fact — resumable, queryable, honest.
            self.ledger.append(
                kind=BACKFILL_STATE_KIND, author=self.author,
                body={"channel": cid, "caught_up": sr.caught_up,
                      "fetched": sr.fetched, "admitted": sr.admitted,
                      "dropped": sr.dropped, "error": sr.error,
                      "retry_after": sr.retry_after},
                event_time=now, tags=("discord", "backfill", cid))

        self.ledger.append(
            kind=BACKFILL_STATE_KIND, author=self.author,
            body={"summary": True, **report.to_body()},
            event_time=now, tags=("discord", "backfill", "summary"))
        return report

    def _walk_surface(self, surf: PollSurface, cursor: str, budget: int,
                      bot_id: str, sr: SurfaceBackfillReport,
                      now: Optional[datetime]) -> int:
        """Page one surface forward until an empty page (caught up), the run
        budget runs out, or the API pushes back. Returns the remaining budget."""
        cid = surf.channel_id
        while budget > 0:
            try:
                batch = self.client.fetch_messages(
                    cid, after=cursor, limit=min(self.page_limit, budget),
                    channel_name=surf.channel_name, is_thread=surf.is_thread,
                    parent_channel=surf.parent_channel, is_dm=surf.is_dm)
            except DiscordRateLimited as e:
                sr.error = str(e)
                sr.retry_after = e.retry_after
                return budget            # stop THIS surface; the runner retries later
            except DiscordAPIError as e:
                sr.error = str(e)
                return budget
            sr.pages += 1
            if not batch.messages:
                sr.caught_up = True      # history exhausted — the live poll takes over
                return budget
            msgs = [m for m in batch.messages
                    if not (bot_id and m.author_id == bot_id)]
            res = ingest_scoped_discord_idempotent(
                self.ledger, msgs, self.iso, self.registry)
            sr.fetched += len(batch.messages)
            sr.admitted += res.admitted
            sr.dropped += res.dropped
            budget -= len(batch.messages)
            if batch.cursor and batch.cursor != cursor:
                cursor = batch.cursor
                # the SAME cursor event the live poll folds — the handoff.
                self.ledger.append(
                    kind=POLL_CURSOR_KIND, author=self.author,
                    body={"channel": cid, "cursor": cursor},
                    event_time=now, tags=("discord", "cursor", cid))
            else:
                # a non-advancing cursor on a non-empty page would loop forever —
                # record it and stop rather than spin (no silent busy-loop).
                sr.error = "cursor did not advance on a non-empty page"
                return budget
        return budget
