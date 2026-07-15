"""Ingestion + the recall-with-provenance query that beats human memory at scale."""

from datetime import datetime, timedelta, timezone

import pytest

from trellis.ingest import (CalendarEvent, DiscordMessage, ingest_calendar,
                            ingest_discord, position_history, temporal_context)


def _msg(author, content, days_ago, ground, **kw):
    return DiscordMessage(author=author, content=content,
                          posted_at=ground.now() - timedelta(days=days_ago),
                          channel="c-chiefs", channel_name="chiefs-of-staffs", **kw)


def test_message_without_author_is_refused(ledger):
    with pytest.raises(ValueError, match="attribution is required"):
        ingest_discord(ledger, [DiscordMessage(
            author="  ", content="x", posted_at=ledger.ground.now(), channel="c")])


def test_event_time_is_the_messages_own_timestamp(ledger, ground, clock):
    m = _msg("brett", "pricing should be $75k", 40, ground)
    [entry] = ingest_discord(ledger, [m])
    # event_time is 40 days ago; write_time is now — the April-reads-as-June bug
    assert (ground.now() - entry.stamp.event_time).days == 40
    assert entry.stamp.write_time == clock.t


def test_dm_is_keyed_as_dm_never_a_channel(ledger, ground):
    m = _msg("sarah", "private", 1, ground, is_dm=True)
    [entry] = ingest_discord(ledger, [m])
    assert entry.body["surface"] == "dm"
    assert "__dm__" in entry.body["storage_key"]


def test_position_history_reconstructs_with_provenance(ledger, ground, clock):
    """The killer query: Brett's view on time-blindness, in order, newest wins."""
    ingest_discord(ledger, [
        _msg("brett", "time blindness is a liability we must eliminate", 84, ground),
        _msg("brett", "time blindness might be an asset if you stare long enough", 1, ground),
        _msg("sarah", "time is the whole ballgame for memory", 3, ground),   # different author
        _msg("brett", "unrelated: the merch drop looks great", 2, ground),   # different topic
    ])
    hist = position_history(ledger, ground, person="brett", topic="time blindness")
    assert len(hist.statements) == 2                     # only Brett, only on-topic
    assert hist.statements[0].content.startswith("time blindness is a liability")
    assert "asset" in hist.current.content               # newest wins
    assert hist.shifted
    assert hist.statements[0].staleness == "expired"     # 84d-old position
    assert hist.current.staleness == "fresh"             # 1d-old
    rendered = hist.render()
    assert "supersedes the above" in rendered and "CURRENT" in rendered
    assert "View shifted" in rendered


def test_position_history_empty_is_honest(ledger, ground):
    hist = position_history(ledger, ground, person="peter", topic="nonexistent")
    assert hist.statements == [] and hist.current is None
    assert "No recorded statements" in hist.render()


def test_temporal_context_grounds_the_agent(ledger, ground, clock):
    """So 'the call we just had' resolves to a real event, not a guess."""
    now = ground.now()
    ingest_calendar(ledger, [
        CalendarEvent("Brett+Sarah+Clare sync", now - timedelta(hours=1),
                      now - timedelta(minutes=15), attendees=("brett", "sarah", "clare")),
        CalendarEvent("Peter / CFA pricing", now + timedelta(hours=2),
                      now + timedelta(hours=3), attendees=("peter",)),
    ])
    ctx = temporal_context(ledger, ground)
    assert ctx["just_happened"]["title"] == "Brett+Sarah+Clare sync"
    assert ctx["next_up"]["title"] == "Peter / CFA pricing"
    # the funder-vs-CFA confusion (Sarah, 2026-07-01) is now answerable from state
    assert "peter" in ctx["next_up"]["attendees"]
