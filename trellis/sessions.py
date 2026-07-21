"""sessions.py — the session model + the session log. (DECISIONS.md D32, D36)

D32 ratified that DMs are IN, scoped and session-tracked: "a saving process of
Username, ID, and tracking of those conversations… if this is not in the UI
(session tracking) it needs to be." D36 makes it the transparency surface —
everything is recorded within sessions, and the session log is how that record
is made legible.

A session is a deterministic FOLD of `discord_message` ledger entries, keyed on
(agent, surface, person, thread), at Alex's ratified granularity:

  * DM      — individuated per interlocutor. Two DMs from the same person fold
              into ONE session; two different DM partners are two sessions. The
              person is keyed on the STABLE canonical identity (the registry's
              snowflake→canonical id), so a display-name rename keeps the same
              session and only the label follows.
  * THREAD  — one session per thread, regardless of who posts in it.
  * CHANNEL — a channel's non-threaded messages are ONE rolling per-channel
              session (they accumulate count and last-activity over time).

No model, no now() of its own — every timestamp is the message's event_time from
the ledger. Rebuildable from the file like every other projection (D2/D5).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import unquote

from .ledger import Ledger
from .registry import IdentityRegistry


@dataclass(frozen=True)
class Session:
    """One conversation, folded from the ledger. `person_id`/`label` are the
    stable identity + current display name of a DM's interlocutor; for a channel
    or thread the human-facing `label` is the channel name."""
    session_id: str            # stable, deterministic, URL-safe
    agent: str                 # the trellis agent that observed it
    surface: str               # "dm" | "channel" | "thread"
    person_id: str             # canonical id of the DM interlocutor ("" otherwise)
    label: str                 # DM: current display name; channel/thread: channel name
    scope: str                 # channel id
    channel_name: str
    thread: Optional[str]      # thread id, or None
    message_count: int
    first_at: datetime
    last_at: datetime


# ---- parsing what the bridge recorded --------------------------------------

def _parse_storage_key(storage_key: str) -> dict:
    """Reverse surfaces.ConversationKey.storage_key() — an injective encoding of
    (agent, surface, scope, thread?, human). Every field was percent-escaped so
    it contains no '_', making the '__' delimiter unambiguous; unquote reverses
    it. Tolerant: returns {} if the shape is not the expected 8 tokens."""
    parts = storage_key.split("__")
    if len(parts) != 8:
        return {}
    return {
        "agent": unquote(parts[0]),
        "surface": unquote(parts[1]),
        "scope": unquote(parts[2]),
        "thread_id": unquote(parts[4]) if parts[3] == "1" else "",
        "human": unquote(parts[7]),
    }


@dataclass(frozen=True)
class _Key:
    """The session's identity + the human-facing fields derived from one entry."""
    session_id: str
    agent: str
    surface: str
    person_id: str
    label: str
    scope: str
    channel_name: str
    thread: Optional[str]


def _key_for(entry, registry: Optional[IdentityRegistry]) -> Optional[_Key]:
    """Derive the session key + display fields for one ledger entry, or None if
    it is not a foldable discord message."""
    if entry.kind != "discord_message":
        return None
    b = entry.body
    sk = _parse_storage_key(str(b.get("storage_key", "")))
    surface = str(b.get("surface") or sk.get("surface") or "channel")
    agent = sk.get("agent") or "ingest"
    scope = str(b.get("channel") or sk.get("scope") or "")
    channel_name = str(b.get("channel_name") or scope)
    thread_id = str(b.get("thread_id") or sk.get("thread_id") or "") or None

    person_id, label = "", channel_name
    if surface == "dm":
        # Key on the STABLE canonical identity so a rename can't fork the session
        # (D32). Prefer the snowflake→canonical map; fall back to the display
        # name only when no stable id was recorded (degraded, pre-bridge data).
        author_id = str(b.get("author_id") or "")
        if registry is not None and author_id:
            cid = registry.canonical_for(author_id)
            if cid:
                person_id = cid
                label = registry.label(cid) or entry.author
            else:
                person_id, label = author_id, entry.author
        else:
            person_id = str(b.get("author_id") or sk.get("human") or entry.author)
            label = entry.author
        disc = person_id
    elif surface == "thread":
        disc = thread_id or scope
    else:
        surface = "channel"
        disc = scope

    thread = thread_id if surface == "thread" else None
    # session_id is a deterministic function of the key only (never a timestamp),
    # so it is stable across rebuilds and folds every message of the conversation
    # onto the same id.
    raw = "\x00".join((agent, surface, disc))
    session_id = f"{surface}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"
    return _Key(session_id=session_id, agent=agent, surface=surface,
                person_id=person_id, label=label, scope=scope,
                channel_name=channel_name, thread=thread)


# ---- the fold --------------------------------------------------------------

def derive_sessions(ledger: Ledger, registry: IdentityRegistry) -> list[Session]:
    """Fold every discord_message into its session. Deterministic and pure — the
    same ledger yields the same sessions, ordered by most-recent activity."""
    acc: dict[str, dict] = {}
    for e in ledger.entries():
        k = _key_for(e, registry)
        if k is None:
            continue
        at = e.stamp.event_time
        s = acc.get(k.session_id)
        if s is None:
            acc[k.session_id] = {
                "key": k, "count": 1, "first": at, "last": at,
                "label": k.label,
            }
        else:
            s["count"] += 1
            if at < s["first"]:
                s["first"] = at
            if at >= s["last"]:
                s["last"] = at
                s["label"] = k.label     # newest message carries the current label
    out = []
    for s in acc.values():
        k = s["key"]
        out.append(Session(
            session_id=k.session_id, agent=k.agent, surface=k.surface,
            person_id=k.person_id, label=s["label"], scope=k.scope,
            channel_name=k.channel_name, thread=k.thread,
            message_count=s["count"], first_at=s["first"], last_at=s["last"]))
    out.sort(key=lambda s: s.last_at, reverse=True)
    return out


def session_transcript(ledger: Ledger, session_id: str) -> list[dict]:
    """The messages in one session, oldest first — the DM/channel legibility D32
    calls for ("this is who, this is what was said"). Rebuilds the identity
    registry from the same ledger so DM session ids resolve identically."""
    registry = IdentityRegistry(ledger)
    rows = []
    for e in ledger.entries():
        k = _key_for(e, registry)
        if k is None or k.session_id != session_id:
            continue
        rows.append({
            "author": e.author,
            "content": str(e.body.get("content", "")),
            "when": e.stamp.event_time,
            "message_id": str(e.body.get("message_id", "")),
        })
    rows.sort(key=lambda r: r["when"])
    return rows
