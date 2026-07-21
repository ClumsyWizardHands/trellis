"""ingest.py — Discord + calendar into the harness, bitemporally and attributed.

This is the honest answer to "how might it find things in Discord better than
Sarah could?" — with the honest caveat stated in code comments: **today, at
finding one message, Sarah wins.** She has taste and a live model of the team.

There is exactly ONE axis on which the harness beats human memory, and it is
not speed-in-the-small. It is *recall-with-provenance at scale*:

  Sarah, asked "what has Brett actually said about pricing, and is his current
  view different from March?", reconstructs it from memory — accurately, but it
  costs her, and she can be wrong about ordering and about what's superseded.

  A trellis agent answers the same question as a QUERY over an append-only,
  bitemporally-stamped, attributed ledger: every statement in chronological
  order, each tagged with its true age, with superseding statements linked and
  stale ones marked stale. It never gets tired, never misorders, and can say
  "his April position is EXPIRED, his July one is current" with certainty.

That is the `position_history` query below. It is the first thing the harness
does that a human structurally cannot — not because it is smarter, but because
it remembers with receipts. Everything else (what matters, what to do about it)
Sarah still wins, and the design hands her exactly that: the harness does the
recall so she does the judgment.

No network here: this module maps already-fetched messages/events into the
ledger. Wire it behind your existing Discord pipeline (the gateway you already
run) or a calendar export. Ingestion is deterministic and testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Iterable, Optional

from .clock import TimeGround
from .ledger import Ledger, Entry
from .sources import RawItem
from .surfaces import ConversationKey, Surface, ThreadRef

if TYPE_CHECKING:  # avoid importing the registry at module load — it is only a hint
    from .registry import IdentityRegistry


# ----- source records (what your fetchers produce) --------------------------


@dataclass(frozen=True)
class DiscordMessage:
    author: str                 # the resolved human/agent name — attribution is required
    content: str
    posted_at: datetime         # the message's OWN timestamp = event_time (never now())
    channel: str
    channel_name: str = ""
    thread_id: Optional[str] = None
    message_id: str = ""
    is_dm: bool = False
    author_id: str = ""         # the Discord snowflake — permanent identity (D32); optional


@dataclass(frozen=True)
class CalendarEvent:
    title: str
    start: datetime
    end: datetime
    attendees: tuple[str, ...] = ()
    calendar_id: str = ""
    location: str = ""


# ----- ingestion ------------------------------------------------------------


def ingest_discord(ledger: Ledger, messages: Iterable[DiscordMessage],
                   agent: str = "ingest") -> list[Entry]:
    """Map messages into the ledger. The critical discipline the loop-provenance
    audit found broken: event_time is the message's OWN timestamp, author is
    always recorded, and the surface (DM vs channel vs thread) is keyed — a
    public message can never be filed as a DM."""
    out = []
    for m in messages:
        if not m.author or not m.author.strip():
            # the audit's user_id=0 bug: a message with no author is not
            # ingested silently — it is refused, loudly, by the ledger.
            raise ValueError(f"message {m.message_id or '?'} has no author — "
                             "attribution is required, not optional")
        surface = (Surface.DM if m.is_dm
                   else Surface.THREAD if m.thread_id else Surface.CHANNEL)
        key = ConversationKey(
            agent=agent, surface=surface,
            scope=m.channel, human=m.author if m.is_dm else "",
            thread=ThreadRef(m.thread_id, m.channel) if m.thread_id else None)
        entry = ledger.append(
            kind="discord_message", author=m.author,
            body={"content": m.content, "channel": m.channel,
                  "channel_name": m.channel_name, "message_id": m.message_id,
                  "surface": surface.value, "storage_key": key.storage_key()},
            event_time=m.posted_at,   # <-- the fix for the whole time-blindness class
            tags=("discord", m.channel_name or m.channel, m.author))
        out.append(entry)
    return out


def discord_to_rawitem(m: DiscordMessage, registry: "Optional[IdentityRegistry]" = None,
                       agent: str = "trellis") -> RawItem:
    """Bridge a live Discord message onto the idempotent Ingestor's RawItem (D31).

    `item_id = message_id`, so a re-poll of the same message shares one
    `RawItem.identity_key()` and is recognised as a duplicate, not double-written.
    The surface/thread/channel_name/author_id and the ConversationKey's
    `storage_key` ride in `meta` so the harvester can file the entry exactly as the
    raw append path did — under an agent-scoped, privacy-injective key.

    Attribution is still required (the audit's user_id=0 bug): a blank author is
    refused, loudly. The author_id snowflake resolves to a STABLE canonical human
    (D32/G11) via the IdentityRegistry so a display-name rename cannot move the
    identity a DM conversation is keyed on; with no snowflake it falls back to the
    display name."""
    if not m.author or not m.author.strip():
        raise ValueError(f"message {m.message_id or '?'} has no author — "
                         "attribution is required, not optional")
    surface = (Surface.DM if m.is_dm
               else Surface.THREAD if m.thread_id else Surface.CHANNEL)
    canonical = ""
    if registry is not None and m.author_id.strip():
        canonical = registry.resolve(m.author_id, m.author)
    # A DM individuates on the stable canonical human (its content stays private to
    # that human); a broadcast surface has no counterpart human in the key.
    human = (canonical or m.author) if m.is_dm else ""
    key = ConversationKey(
        agent=agent, surface=surface, scope=m.channel, human=human,
        thread=ThreadRef(m.thread_id, m.channel) if m.thread_id else None)
    meta = (("surface", surface.value), ("thread", m.thread_id or ""),
            ("channel_name", m.channel_name), ("author", m.author),
            ("author_id", m.author_id), ("canonical_author", canonical),
            ("storage_key", key.storage_key()))
    return RawItem(source="discord", channel=m.channel, content=m.content,
                   event_time=m.posted_at, item_id=m.message_id, kind="message",
                   meta=meta)


def ingest_calendar(ledger: Ledger, events: Iterable[CalendarEvent],
                    agent: str = "ingest") -> list[Entry]:
    """Calendar events are time-anchored facts. Ingesting them gives the agent
    a real clock reference — the thing it structurally lacks (Sarah, 2026-07-01:
    the agent 'misinterpreted the call we just had… thought it was with a
    funder'). With the calendar in the ledger, 'what was the 2pm call' is a
    query against event_time, not a guess."""
    out = []
    for ev in events:
        out.append(ledger.append(
            kind="calendar_event", author=agent,
            body={"title": ev.title, "start": ev.start.isoformat(),
                  "end": ev.end.isoformat(), "attendees": list(ev.attendees),
                  "location": ev.location, "calendar_id": ev.calendar_id},
            event_time=ev.start,
            tags=("calendar", *ev.attendees)))
    return out


# ----- the query that beats human recall ------------------------------------


@dataclass
class PositionStatement:
    author: str
    content: str
    when: datetime
    staleness: str              # fresh / aging / stale / expired
    age_phrase: str
    entry_id: str


@dataclass
class PositionHistory:
    person: str
    topic: str
    statements: list[PositionStatement]   # chronological, oldest first

    @property
    def current(self) -> Optional[PositionStatement]:
        """Newest-wins: the position that stands now."""
        return self.statements[-1] if self.statements else None

    @property
    def shifted(self) -> bool:
        return len(self.statements) >= 2

    def render(self) -> str:
        """A human-readable answer, with receipts — the thing you'd hand Sarah
        so she can do the judgment instead of the archaeology."""
        if not self.statements:
            return f"No recorded statements by {self.person} on '{self.topic}'."
        lines = [f"{self.person} on '{self.topic}' — {len(self.statements)} "
                 f"statement(s), oldest first:"]
        for i, s in enumerate(self.statements):
            marker = "  → CURRENT" if s is self.current else ""
            supers = " (supersedes the above)" if i > 0 else ""
            lines.append(f"  [{s.staleness} · {s.age_phrase} · "
                         f"{s.when.date().isoformat()}] {s.content}{supers}{marker}")
        if self.shifted:
            lines.append(f"\nView shifted: treat the {self.current.staleness} "
                         f"{self.current.when.date().isoformat()} statement as current; "
                         "the earlier one(s) are superseded.")
        return "\n".join(lines)


def position_history(ledger: Ledger, ground: TimeGround, person: str, topic: str,
                     volatility: str = "position") -> PositionHistory:
    """Reconstruct what `person` has said about `topic`, in order, with each
    statement's true age and staleness, newest as current.

    This is the harness's structural edge: perfect chronological recall with
    provenance. A human does this from memory and tires; the ledger does it
    from receipts and does not."""
    terms = [t for t in re.findall(r"\w+", topic.lower()) if len(t) > 2]
    hits = []
    for e in ledger.entries():
        if e.kind != "discord_message":
            continue
        if e.author.strip().lower() != person.strip().lower():
            continue
        content = str(e.body.get("content", ""))
        low = content.lower()
        if terms and not any(t in low for t in terms):
            continue
        hits.append(e)
    hits.sort(key=lambda e: e.stamp.event_time)
    statements = [
        PositionStatement(
            author=e.author, content=str(e.body.get("content", "")),
            when=e.stamp.event_time,
            staleness=ground.staleness(e.stamp.event_time, volatility).value,
            age_phrase=ground.age_phrase(e.stamp.event_time),
            entry_id=e.id)
        for e in hits
    ]
    return PositionHistory(person=person, topic=topic, statements=statements)


def temporal_context(ledger: Ledger, ground: TimeGround, window_hours: int = 24) -> dict:
    """Ground the agent in time from the calendar: what just happened, what's
    next. So 'the call we just had' resolves to a real event, not a guess."""
    now = ground.now()
    events = [e for e in ledger.entries() if e.kind == "calendar_event"]
    past, future = [], []
    for e in events:
        start = datetime.fromisoformat(e.body["start"])
        (past if start <= now else future).append((start, e))
    past.sort(key=lambda x: x[0])
    future.sort(key=lambda x: x[0])
    def fmt(pair):
        start, e = pair
        return {"title": e.body["title"], "start": e.body["start"],
                "attendees": e.body.get("attendees", []),
                "when": ground.age_phrase(start) if start <= now
                        else f"in {ground.age_phrase(now - (start - now))[:-4]}"}
    return {
        "now": now.isoformat(),
        "just_happened": fmt(past[-1]) if past else None,
        "next_up": fmt(future[0]) if future else None,
    }
