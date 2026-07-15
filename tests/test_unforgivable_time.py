"""Unforgivable #4 — time-blindness. The harness carries time so the model
doesn't have to guess. (Dossier rank #4; Brett's thesis, 2026-04-22)"""

from datetime import datetime, timedelta, timezone

import pytest

from trellis.clock import (HEARTBEAT_OK, Schedule, ScheduleKind, Staleness,
                           Stamp, TimeGround, parse_iso)


def test_naive_timestamps_are_refused():
    with pytest.raises(ValueError, match="naive"):
        parse_iso("2026-07-15T12:00:00")
    with pytest.raises(ValueError):
        Stamp(datetime(2026, 7, 15), datetime(2026, 7, 15, tzinfo=timezone.utc))


def test_bitemporal_stamp_keeps_both_truths(ground, clock):
    april = datetime(2026, 4, 22, tzinfo=timezone.utc)
    s = ground.stamp(event_time=april)
    assert s.event_time == april
    assert s.write_time == clock.t
    # the April-minted-in-July bug is unrepresentable: both times exist
    assert s.capture_lag > timedelta(days=80)


def test_staleness_decays_by_volatility(ground, clock):
    said_now = clock.t
    assert ground.staleness(said_now, "conversation") == Staleness.FRESH
    clock.advance(days=5)
    # 5 days on a 2-day half-life conversation → stale
    assert ground.staleness(said_now, "conversation") in (Staleness.STALE, Staleness.EXPIRED)
    # 5 days on a 180-day half-life principle → still fresh
    assert ground.staleness(said_now, "principle") == Staleness.FRESH


def test_annotation_makes_age_visible_in_text(ground, clock):
    t0 = clock.t
    clock.advance(days=30)
    out = ground.annotate("Brett prefers X", t0, volatility="position")
    assert "30d ago" in out and "2026-07-15" in out
    assert out.startswith("[")  # the tag leads; a skimming model still sees it


def test_newest_wins(ground):
    older = (datetime(2026, 3, 1, tzinfo=timezone.utc), "time-blindness is a liability")
    newer = (datetime(2026, 7, 14, tzinfo=timezone.utc), "time-blindness can be an asset")
    t, statement = ground.newest_wins([older, newer])
    assert "asset" in statement


def test_heartbeat_requires_checklist_and_cron_requires_prompt():
    with pytest.raises(ValueError, match="checklist"):
        Schedule("hb", ScheduleKind.HEARTBEAT, timedelta(minutes=30))
    with pytest.raises(ValueError, match="standalone prompt"):
        Schedule("cr", ScheduleKind.CRON, timedelta(days=1))


def test_schedule_verification_answers_was_it_actually_scheduled(ground, clock):
    """Sarah, 2026-07-01: 'we never verified whether the cron jobs were
    actually scheduled. They were not.' Now it's a query."""
    s = Schedule("morning", ScheduleKind.CRON, timedelta(days=1),
                 prompt="assemble the morning surface")
    v = s.verify(ground)
    assert v["ok"] is False and v["reason"] == "never fired"

    s.record_firing(ground)
    assert s.verify(ground)["ok"] is True

    clock.advance(days=4)  # silent for 4 days on a daily cadence
    v = s.verify(ground)
    assert v["ok"] is False and "silent" in v["reason"]


def test_heartbeat_due_respects_active_hours(ground, clock):
    s = Schedule("hb", ScheduleKind.HEARTBEAT, timedelta(minutes=30),
                 checklist="HEARTBEAT.md", active_hours=(7, 22))
    clock.t = clock.t.replace(hour=3)
    assert s.due(ground) is False   # 3am: not burning budget while Alex sleeps
    clock.t = clock.t.replace(hour=9)
    assert s.due(ground) is True
    assert HEARTBEAT_OK == "HEARTBEAT_OK"
