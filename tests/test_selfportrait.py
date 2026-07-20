"""The daily self-portrait morph — evolving, but honest.

Pins: the portrait is a deterministic function of the ledger snapshot chain (no
performed selfhood); it reads the reflection_log snapshots the ritual already
writes; it visibly builds on the previous day (ghost + morph + strip + delta);
and it renders valid SVG."""

from datetime import timedelta

from web.glyph import GlyphStats
from web.selfportrait import (portrait_delta, render_growth_strip, render_morph,
                             render_self_portrait, snapshot_series)


def _stats(entries, checked=0, verified=0, trust=None, open_ts=0, memories=0, age=3.0):
    return GlyphStats(entries=entries, checked=checked, verified=verified, trust=trust,
                      open_ts=open_ts, memories=memories, age_days=age, decisions=entries // 5)


def test_portrait_is_deterministic_in_the_snapshot():
    a = render_self_portrait(_stats(50, 6, 5, 0.83), prev=_stats(42, 5, 4, 0.8))
    b = render_self_portrait(_stats(50, 6, 5, 0.83), prev=_stats(42, 5, 4, 0.8))
    assert a == b and a.startswith("<svg") and a.rstrip().endswith("</svg>")


def test_portrait_builds_on_yesterday_with_a_ghost():
    with_prev = render_self_portrait(_stats(50, 6, 5, 0.83), prev=_stats(42, 5, 4, 0.8))
    solo = render_self_portrait(_stats(50, 6, 5, 0.83), prev=None)
    # the ghost layer only appears when there is a previous day to build on
    assert 'opacity="0.22"' in with_prev
    assert 'opacity="0.22"' not in solo


def test_morph_crossfades_yesterday_to_today_deterministically():
    m = render_morph(_stats(42, 5, 4, 0.8), _stats(50, 6, 5, 0.83))
    assert "<animate" in m and "repeatCount=\"indefinite\"" in m
    assert m == render_morph(_stats(42, 5, 4, 0.8), _stats(50, 6, 5, 0.83))  # no clock/random


def test_snapshot_series_reads_the_reflection_chain(ledger, ground, clock):
    # two ritual snapshots on different days, oldest first
    ledger.append("reflection_log", "witness",
                  {"self_image": {"entries": 20, "decisions": 3, "checked": 2,
                                  "verified": 2, "trust": 1.0, "open_ts": 0, "memories": 1,
                                  "age_days": 3.0}}, event_time=ground.now())
    clock.advance(days=1)
    ledger.append("reflection_log", "witness",
                  {"self_image": {"entries": 30, "decisions": 5, "checked": 3,
                                  "verified": 2, "trust": 0.66, "open_ts": 1, "memories": 2,
                                  "age_days": 4.0}}, event_time=ground.now())
    series = snapshot_series(ledger, include_live=False)
    assert len(series) == 2
    assert series[0][1].entries == 20 and series[1][1].entries == 30   # oldest → newest


def test_growth_strip_renders_the_chain(ledger, ground):
    series = [("2026-07-18", _stats(20)), ("2026-07-19", _stats(30)),
              ("2026-07-20", _stats(40, trust=0.8))]
    svg = render_growth_strip(series)
    assert svg.startswith("<svg") and "07-20" in svg and svg.count("aria-label") == 1


def test_portrait_delta_describes_change_relative_to_yesterday():
    lines = portrait_delta(_stats(42, 5, 4, 0.8), _stats(50, 6, 5, 0.83))
    joined = " ".join(lines)
    assert "42 → 50" in joined and "trust" in joined.lower()
    # no change → honest stillness, not a fabricated difference
    same = portrait_delta(_stats(50, 6, 5, 0.83), _stats(50, 6, 5, 0.83))
    assert any("held steady" in l or "stillness" in l for l in same)


def test_first_portrait_has_no_yesterday():
    lines = portrait_delta(None, _stats(20))
    assert any("first portrait" in l for l in lines)
