"""test_p2_bridge.py — the live-Discord ingestion bridge (D31 + D32).

A live Discord message rides the IDEMPOTENT sources.Ingestor, not the dedup-less
append path:
  * re-poll is a no-op — two identical passes land ONE set of ledger items (D31);
  * a threaded message is readable when its PARENT CHANNEL is allowlisted (D32);
  * a non-allowlisted channel's message is dropped AND counted (never silent);
  * author_id (the snowflake) resolves to a stable canonical id across a rename.
"""

from datetime import timedelta

import pytest

from trellis.ingest import DiscordMessage, discord_to_rawitem
from trellis.isolation import (AgentIdentity, Isolation, SurfaceAllowlist,
                               ingest_scoped_discord_idempotent)
from trellis.registry import IdentityRegistry
from trellis.sources import RawItem

TRELLIS_CH = "chan-trellis"
OTHER_CH = "chan-vex-atlas"
THREAD = "thread-987"


def _msg(author, content, channel, ground, **kw):
    return DiscordMessage(author=author, content=content,
                          posted_at=ground.now(), channel=channel, **kw)


def _discord_entries(ledger):
    return [e for e in ledger.active("discord_message")]


# ----- the bridge maps a message to a RawItem -------------------------------

def test_discord_to_rawitem_carries_id_and_meta(ground):
    m = _msg("alex", "hello", TRELLIS_CH, ground, message_id="mid-1",
             channel_name="chiefs", author_id="42", thread_id=THREAD)
    item = discord_to_rawitem(m)
    assert isinstance(item, RawItem)
    assert item.item_id == "mid-1"           # id-keyed → re-poll is a no-op
    assert item.source == "discord"
    assert item.channel == TRELLIS_CH
    assert item.event_time == m.posted_at
    meta = dict(item.meta)
    assert meta["thread"] == THREAD
    assert meta["channel_name"] == "chiefs"
    assert meta["author_id"] == "42"
    assert meta["storage_key"]               # a real ConversationKey storage key


def test_author_id_resolves_to_canonical_human_in_dm_key(ledger, ground):
    reg = IdentityRegistry(ledger)
    m = _msg("Bob", "dm hi", "dm-1", ground, message_id="d1",
             author_id="42", is_dm=True)
    item = discord_to_rawitem(m, registry=reg, agent="trellis")
    canon = reg.canonical_for("42")
    assert canon                             # the snowflake was registered
    # the DM key individuates on the STABLE canonical id, not the mutable name
    assert canon in dict(item.meta)["storage_key"]


# ----- D31: re-poll is a no-op ----------------------------------------------

def test_repoll_is_a_noop(ledger, ground):
    iso = Isolation(identity=AgentIdentity(name="trellis"),
                    allow=SurfaceAllowlist(read=frozenset({TRELLIS_CH})))
    reg = IdentityRegistry(ledger)
    batch = [
        _msg("alex", "first", TRELLIS_CH, ground, message_id="a", author_id="1"),
        _msg("alex", "second", TRELLIS_CH, ground, message_id="b", author_id="1"),
    ]
    r1 = ingest_scoped_discord_idempotent(ledger, batch, iso, reg)
    r2 = ingest_scoped_discord_idempotent(ledger, batch, iso, reg)   # identical re-poll

    assert r1.result.processed == 2
    assert r2.result.processed == 0 and r2.result.skipped_duplicate == 2
    # exactly ONE set of discord_message items — no double-write
    entries = _discord_entries(ledger)
    assert len(entries) == 2
    assert sorted(e.body["content"] for e in entries) == ["first", "second"]


# ----- D32: a thread under an allowlisted channel INGESTS -------------------

def test_thread_under_allowlisted_channel_ingests(ledger, ground):
    """Thread ids are dynamic and can't be pre-listed; a threaded message is
    readable via its PARENT CHANNEL. Today it is silently dropped."""
    iso = Isolation(identity=AgentIdentity(name="trellis"),
                    allow=SurfaceAllowlist(read=frozenset({TRELLIS_CH})))
    reg = IdentityRegistry(ledger)
    m = _msg("alex", "in a thread", TRELLIS_CH, ground, message_id="t1",
             thread_id=THREAD, author_id="1")            # thread id NOT allowlisted
    r = ingest_scoped_discord_idempotent(ledger, [m], iso, reg)

    assert r.admitted == 1 and r.dropped == 0
    entries = _discord_entries(ledger)
    assert len(entries) == 1 and entries[0].body["content"] == "in a thread"
    assert entries[0].body["surface"] == "thread"


# ----- D32: a non-allowlisted channel is dropped AND counted ----------------

def test_non_allowlisted_channel_is_dropped_and_counted(ledger, ground):
    iso = Isolation(identity=AgentIdentity(name="trellis"),
                    allow=SurfaceAllowlist(read=frozenset({TRELLIS_CH})))
    reg = IdentityRegistry(ledger)
    batch = [
        _msg("alex", "mine", TRELLIS_CH, ground, message_id="a", author_id="1"),
        _msg("nope", "another agent's", OTHER_CH, ground, message_id="x", author_id="9"),
        _msg("nope", "another agent's too", OTHER_CH, ground, message_id="y", author_id="9"),
    ]
    r = ingest_scoped_discord_idempotent(ledger, batch, iso, reg)

    assert r.admitted == 1
    assert r.dropped == 2                                  # never silent
    assert r.dropped_by_surface[OTHER_CH] == 2            # counted per surface
    all_content = [e.body.get("content") for e in ledger.entries()
                   if e.kind == "discord_message"]
    assert "another agent's" not in all_content


def test_thread_under_non_allowlisted_channel_is_dropped_and_counted(ledger, ground):
    iso = Isolation(identity=AgentIdentity(name="trellis"),
                    allow=SurfaceAllowlist(read=frozenset({TRELLIS_CH})))
    reg = IdentityRegistry(ledger)
    m = _msg("nope", "thread on another agent's channel", OTHER_CH, ground,
             message_id="t9", thread_id="thread-other", author_id="9")
    r = ingest_scoped_discord_idempotent(ledger, [m], iso, reg)
    assert r.admitted == 0 and r.dropped == 1
    assert r.dropped_by_surface["thread-other"] == 1
    assert _discord_entries(ledger) == []


# ----- D32/G11: author_id is a stable canonical id across a rename ----------

def test_author_id_stable_canonical_across_rename(ledger, ground):
    iso = Isolation(identity=AgentIdentity(name="trellis"),
                    allow=SurfaceAllowlist(read=frozenset({TRELLIS_CH})))
    reg = IdentityRegistry(ledger)
    m1 = _msg("Bob", "before rename", TRELLIS_CH, ground, message_id="a",
              author_id="42")
    ingest_scoped_discord_idempotent(ledger, [m1], iso, reg)
    canon_before = reg.canonical_for("42")

    m2 = _msg("Bobby McNewname", "after rename", TRELLIS_CH, ground, message_id="b",
              author_id="42")                              # same person, new name
    ingest_scoped_discord_idempotent(ledger, [m2], iso, reg)
    canon_after = reg.canonical_for("42")

    assert canon_before == canon_after                     # identity did not move
    assert reg.label(canon_after) == "Bobby McNewname"     # label followed the rename


# ----- attribution is still required ----------------------------------------

def test_blank_author_is_refused(ground):
    m = _msg("", "no attribution", TRELLIS_CH, ground, message_id="z")
    with pytest.raises(ValueError, match="attribution"):
        discord_to_rawitem(m)
