"""Web layer — the PURE parts (views + glyph) tested deterministically, no
server, no FastAPI. The app.py wiring is a thin shell over these."""

from datetime import timedelta

import pytest

from trellis.agent import Event, Witness
from trellis.decisions import Decision, DecisionLog, POV, Verdict
from trellis.emp import EMP
from trellis.memory import Workspace
from trellis.stage import Outbox, StagedAction
from trellis.surfaces import ConversationKey, Surface
from web import views
from web.glyph import GlyphStats, render_glyph, reflection


@pytest.fixture
def populated(ledger, ground, tmp_path):
    """A ledger with a bit of everything, for the views."""
    log = DecisionLog(ledger, ground)
    log.record(Decision("adopt X", Verdict.Y, "clear win", "witness:a", "EMP:ends[0]"))
    log.record(Decision("auto-post digest", Verdict.N, "stage don't fire", "witness:a",
                        "EMP:principles[0]"))
    povs = [POV("brett", "beside"), POV("clare", "on-agent"), POV("sarah", "workflow")]
    old_t = Decision("memory fork", Verdict.T, "unsettled", "witness:a", "EMP:principles[1]",
                     povs=povs, owner="alex", missing="cost data",
                     revisit_at=ground.now() - timedelta(days=1))  # already a hidden no
    log.record(old_t)
    box = Outbox(ledger, ground)
    box.stage(StagedAction("discord_post", "#chiefs", "the morning digest",
                           created_by="witness:a"))
    ws = Workspace(tmp_path / "ws", ledger)
    ws.write("read/r.md", "content", "witness:a",
             "the current read exists nowhere else in this synthesized form")
    return ledger


def test_decision_timeline_and_hidden_nos(populated, ground):
    rows = views.decision_timeline(populated, ground)
    verdicts = {r["verdict"] for r in rows}
    assert verdicts == {"Y", "N", "T"}
    hidden = [r for r in rows if r["hidden_no"]]
    assert len(hidden) == 1 and hidden[0]["verdict"] == "T"


def test_inbox_shows_pending_only(populated, ground):
    box = views.inbox(populated, ground)
    assert len(box) == 1 and box[0]["kind"] == "discord_post"


def test_roster_and_memory_map(populated, ground):
    ros = views.roster(populated, ground)
    assert any(r["agent"] == "witness:a" for r in ros)
    mm = views.memory_map(populated, ground)
    assert mm and mm[0]["path"] == "read/r.md"


def test_activity_feed_is_a_story(populated, ground):
    feed = views.activity_feed(populated, ground)
    stories = " ".join(f["story"] for f in feed)
    assert "decided" in stories and "staged" in stories


def test_growth_stats_are_real_numbers(populated, ground):
    s = views.growth_stats(populated, ground)
    assert s["decisions"] == 3 and s["open_ts"] == 1 and s["entries"] > 0


# ---- the reflection portal views (Phase 3, pure) ---------------------------

def test_reflection_view_none_until_ritual_runs(populated, ground):
    assert views.reflection_view(populated, ground) is None


def test_reflection_view_reads_the_ritual_output(populated, ground):
    from trellis.reflect import ReflectionRitual, SelfChange
    from trellis.verify import RuleVerifier
    d = views.decision_timeline(populated, ground)[0]
    r = ReflectionRitual(populated, author="witness:r",
                         verifier=RuleVerifier("verifier:x", populated), ground=ground)
    r.run("s1", "held the read; this session ends and the record survives",
          "a synthesized read on the team's memory fork that exists in no single transcript",
          self_change=SelfChange("EMP:friction", "record the burn", "it recurred",
                                 evidence_ids=[populated.entries()[0].id]))
    v = views.reflection_view(populated, ground)
    assert v is not None
    assert v["cited_count"] >= 1 and v["self_image"]["entries"] > 0
    assert v["self_change"]["verified"] is True


def test_decision_walk_reconstructs_a_decision(populated, ground):
    d = views.decision_timeline(populated, ground)[0]
    w = views.decision_walk(populated, d["id"], ground)
    assert w is not None and w["verdict"] in ("Y", "N", "T")
    assert w["subject"] == d["subject"]
    assert views.decision_walk(populated, "nonexistent", ground) is None


def test_open_questions_unions_hidden_and_reopened(populated, ground):
    from trellis.decisions import DecisionLog
    # the fixture already has one hidden-no T; reopen the N to add a reopened one
    n = [r for r in views.decision_timeline(populated, ground) if r["verdict"] == "N"][0]
    DecisionLog(populated, ground).reopen(n["id"], "raised again", "alex")
    oq = views.open_questions_view(populated, ground)
    kinds = {q["kind"] for q in oq}
    assert kinds == {"hidden-no", "reopened"}


# ---- glyph: deterministic + honest -----------------------------------------

def test_glyph_is_deterministic():
    s = GlyphStats(decisions=10, verified=8, checked=10, trust=0.8, memories=6,
                   loop_runs=4, open_ts=1, age_days=12, entries=40)
    assert render_glyph(s) == render_glyph(s)      # same stats → same picture


def test_glyph_changes_with_state():
    newborn = GlyphStats(entries=1)
    grown = GlyphStats(decisions=20, verified=18, checked=20, trust=0.9,
                       memories=9, open_ts=0, age_days=30, entries=120)
    assert render_glyph(newborn) != render_glyph(grown)   # growth is visible


def test_glyph_is_valid_svg():
    svg = render_glyph(GlyphStats(entries=10, checked=3, trust=0.5))
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "viewBox" in svg


def test_reflection_ties_visuals_to_numbers():
    s = GlyphStats(verified=8, checked=10, trust=0.8, memories=6, open_ts=2,
                   age_days=9, entries=40)
    refl = reflection(s)
    joined = " ".join(refl)
    assert "80%" in joined           # trust surfaced honestly
    assert "6 memories" in joined
    assert "unresolved" in joined    # the 2 open Ts explained


def test_unproven_trust_is_pale_not_low():
    refl = reflection(GlyphStats(entries=5, checked=0, trust=None))
    assert any("unearned" in x or "unproven" in x for x in refl)


def test_witness_cycle_feeds_the_views(ledger, ground, tmp_path):
    """End to end: a real witness cycle → the ledger → the views render it."""
    from web.glyph import GlyphStats
    emp = EMP(name="W", ends=["hold context"], means=["read"], principles=["never fail silently"],
              authored_by="Alex")
    key = ConversationKey("witness:w", Surface.CHANNEL, "c", "")
    ws = Workspace(tmp_path / "ws", ledger)
    from trellis.providers.mock import MockProvider
    import json as _json
    prov = MockProvider()
    prov.enqueue_text(_json.dumps([{"subject": "note the shift", "verdict": "Y",
                                    "rationale": "newer supersedes older",
                                    "emp_lineage": "EMP:ends[0]"}]))
    w = Witness(emp, prov, ledger, ws, key, ground=ground)
    w.witness_cycle([Event("brett", "a thing happened", ground.now())])
    stats = views.growth_stats(ledger, ground)
    assert stats["decisions"] == 1 and stats["checked"] >= 1
    # and it renders
    assert render_glyph(GlyphStats.from_growth(stats)).startswith("<svg")
