"""Phase 2 — memory as navigation (DECISIONS D14-D17).

Five moves, each with the adversarial check the plan's stress-test demanded:
  2a titles + search-by-title  · a title can never be un-findable
  2b WALK/REOPEN/DECIDE        · WALK never emits a verdict; no silent re-decide
  2c resolved-head cache       · the cache never serves a retired head
  2d one current-truth resolver· no read path serves a validity-retired sapling
  2e fold-not-clobber          · an overwrite never loses content
"""

from datetime import datetime, timedelta, timezone

import pytest

from trellis.decisions import (CollidingDecisionError, Decision, DecisionLog,
                               POV, Verdict, question_key)
from trellis.ledger import Ledger
from trellis.memory import TitleError, Workspace
from trellis.navigate import Navigator, ReopenRequiredError, Walk

GOODJ = ("this synthesized judgment exists nowhere in transcripts or logs and "
         "cannot be re-derived mechanically")


def _yn(subject, verdict=Verdict.Y, author="witness"):
    return Decision(subject, verdict, "a real rationale on the record", author,
                    "EMP:principles[0]")


def _t(subject, revisit):
    return Decision(subject, Verdict.T, "a live fork", "witness", "EMP:ends[0]",
                    povs=[POV("brett", "beside"), POV("clare", "on-agent"),
                          POV("sarah", "workflow-first")],
                    owner="alex", missing="a cost comparison", revisit_at=revisit)


# ============ 2d — ONE current-truth resolver (flaw #4) ==================

def test_retire_drops_from_active_but_survives_in_lineage(ledger, clock):
    e = ledger.append("fact", "witness", {"claim": "pricing is $X"})
    assert e in ledger.active("fact")
    ledger.retire(e.id, "witness", reason="pricing changed")
    # retired-but-unsuperseded: gone from every truth-serving read...
    assert ledger.active("fact") == []
    assert ledger.current("fact") == []          # current() IS active() now
    assert ledger.search("pricing") == []
    # ...but never deleted: audit still sees it
    assert ledger.get(e.id) is not None
    assert e.id in {x.id for x in ledger.lineage(e.id)}


def test_current_and_active_are_the_same_predicate(ledger):
    a = ledger.append("fact", "w", {"n": 1})
    b = ledger.append("fact", "w", {"n": 2})
    assert {x.id for x in ledger.current("fact")} == {x.id for x in ledger.active("fact")}
    ledger.retire(a.id, "w")
    assert {x.id for x in ledger.current("fact")} == {x.id for x in ledger.active("fact")} == {b.id}


def test_retirement_is_appended_never_mutates_the_entry(ledger):
    e = ledger.append("fact", "w", {"n": 1})
    before = ledger.get(e.id)
    ledger.retire(e.id, "w")
    after = ledger.get(e.id)
    assert before.body == after.body and before.stamp.write_time == after.stamp.write_time


# ============ 2b — anti-fork: no silent re-decide (flaw #1) ==============

def test_record_refuses_a_colliding_live_decision(ledger):
    log = DecisionLog(ledger)
    log.record(_yn("Auto-post the digest to #general", Verdict.N))
    with pytest.raises(CollidingDecisionError):
        log.record(_yn("auto-post the digest to #general", Verdict.Y))  # case-fold collision


def test_question_key_is_homoglyph_and_punctuation_stable():
    # a Cyrillic 'е' twin must not open a second live head on the same question
    assert question_key("Ship the release") == question_key("Ship the relеase")
    assert question_key("Memory: on-agent vs beside?") == question_key("memory on agent vs beside")


def test_two_live_heads_cannot_answer_one_question_even_unlinked(ledger):
    """The exact stress-test finding: an UNLINKED fresh Y/N (supersedes=None) on
    a settled question used to slip past the anti-fork guard."""
    log = DecisionLog(ledger)
    log.record(_yn("Adopt the July framing", Verdict.Y))
    with pytest.raises(CollidingDecisionError):
        log.record(_yn("Adopt the July framing", Verdict.N))
    # exactly one live head survives
    heads = [e for e in ledger.active("decision")
             if log._qkey_of(e) == question_key("Adopt the July framing")]
    assert len(heads) == 1


def test_decide_brand_new_records_but_live_yn_needs_reopen(ledger):
    nav = Navigator(DecisionLog(ledger))
    nav.decide(_yn("Stage-don't-fire the pricing email", Verdict.N))
    with pytest.raises(ReopenRequiredError):
        nav.decide(_yn("Stage-don't-fire the pricing email", Verdict.Y))


def test_decide_resolves_a_live_T(ledger, ground):
    log = DecisionLog(ledger)
    nav = Navigator(log)
    t = _t("System of record", ground.now() + timedelta(days=7))
    log.record(t)
    y = _yn("System of record", Verdict.Y)
    nav.decide(y)   # decide on a live T resolves it
    head = log.active_head(question_key("System of record"))
    assert head.body["verdict"] == "Y"
    assert log.upstream(head.body["decision_id"])[-1]["verdict"] == "T"  # lineage kept


# ============ 2b — REOPEN writes a marker, not an illegal T (flaw #2) ====

def test_reopen_never_mints_a_bare_T(ledger):
    log = DecisionLog(ledger)
    d = log.record(_yn("Auto-post morning digest", Verdict.N))
    did = d.body["decision_id"]
    # a trigger has 0 POVs — a bare T would raise; reopen must NOT try to mint one
    marker = log.reopen(did, "team asked about autonomous posting again", "alex")
    assert marker.kind == "reopen" and marker.body["reopens"] == did
    # the decision itself is untouched — no silent flip
    assert log.active_head(question_key("Auto-post morning digest")).body["verdict"] == "N"


def test_reopened_surfaces_then_clears_on_resolve(ledger):
    log = DecisionLog(ledger)
    nav = Navigator(log)
    d = log.record(_yn("Adopt autonomous posting", Verdict.N))
    did = d.body["decision_id"]
    assert log.reopened() == []
    log.reopen(did, "the team ratified it", "alex")
    reopened = log.reopened()
    assert len(reopened) == 1 and reopened[0].body["decision_id"] == did
    assert did in {e.body["decision_id"] for e in log.open_questions()}
    # resolve the reopened head (promote/flip WITH lineage) → marker clears
    nav.resolve(did, _yn("Adopt autonomous posting", Verdict.Y, author="alex"))
    assert log.reopened() == []


def test_open_questions_unions_hidden_nos_and_reopened(ledger, ground, clock):
    log = DecisionLog(ledger)
    t = _t("Obsidian vs Drive", ground.now() + timedelta(days=3))
    log.record(t)
    d = log.record(_yn("Post to #chiefs automatically", Verdict.N))
    log.reopen(d.body["decision_id"], "raised again in standup", "alex")
    clock.advance(days=5)   # the T is now a hidden no
    keys = {e.body["subject"] for e in log.open_questions()}
    assert keys == {"Obsidian vs Drive", "Post to #chiefs automatically"}


# ============ 2b — WALK is read-only, never emits a verdict ===============

def test_walk_reconstructs_why_and_writes_nothing(ledger, ground):
    log = DecisionLog(ledger)
    nav = Navigator(log)
    d = log.record(_yn("Treat time-blindness as an asset", Verdict.Y))
    before = len(ledger.entries())
    w = nav.walk(d.body["decision_id"])
    assert isinstance(w, Walk)
    assert w.as_recorded == "Y" and "rationale" in w.rationale or w.rationale
    assert len(ledger.entries()) == before      # WALK appended nothing
    # type-level: a Walk exposes no way to emit a verdict
    assert not hasattr(w, "record") and not hasattr(w, "decide")


def test_walk_of_unknown_is_none(ledger):
    assert Navigator(DecisionLog(ledger)).walk("nope") is None


# ============ 2c — resolved-head cache never serves a stale head =========

def test_cache_tracks_active_head_across_supersession_and_retire(ledger, ground):
    log = DecisionLog(ledger)
    nav = Navigator(log)
    t = _t("Memory architecture", ground.now() + timedelta(days=7))
    log.record(t)
    qk = question_key("Memory architecture")
    assert nav.cache.head(qk).body["verdict"] == "T"
    nav.decide(_yn("Memory architecture", Verdict.Y))    # resolve → new head
    assert nav.cache.head(qk).body["verdict"] == "Y"     # cache rebuilt
    ledger.retire(nav.cache.head(qk).id, "alex")         # retire the head
    assert nav.cache.head(qk) is None                    # never serves a retired head


# ============ 2a — titles: findable, never vague ========================

def test_vague_or_empty_explicit_title_is_refused(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    for bad in ("notes", "  ", "TODO", "misc"):
        with pytest.raises(TitleError):
            ws.write("x.md", "real content here", "witness", GOODJ, title=bad)


def test_title_search_finds_the_door_by_its_label(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    ws.write("reads/eaf.md", "lots of body text " * 20, "witness", GOODJ,
             title="The read on EAF pricing")
    ws.write("skills/harvest.md", "body " * 10, "witness", GOODJ,
             title="End-of-day harvest routine")
    hits = ws.search_titles("pricing")
    assert len(hits) == 1 and hits[0][1] == "reads/eaf.md"
    # bodies are NOT searched — a keyword only in the body doesn't match
    assert ws.search_titles("body text") == []


def test_retired_memory_leaves_the_title_index(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    r = ws.write("reads/old.md", "content here now", "witness", GOODJ,
                 title="Stale read to retire")
    assert ws.search_titles("stale")
    ledger.retire(r.ledger_entry, "witness", reason="superseded read")
    assert ws.search_titles("stale") == []       # validity-aware index


def test_navigator_search_unions_decisions_and_memory(tmp_path, ledger):
    log = DecisionLog(ledger)
    ws = Workspace(tmp_path / "ws", ledger)
    nav = Navigator(log, ws)
    log.record(_yn("Pricing canon for the one-pager", Verdict.Y))
    ws.write("reads/pricing.md", "x " * 20, "witness", GOODJ,
             title="Pricing evidence from Brett")
    kinds = {h.kind for h in nav.search_titles("pricing")}
    assert kinds == {"decision", "memory"}


# ============ 2e — fold, don't clobber ==================================

def test_overwrite_preserves_the_prior_body(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    ws.write("reads/live.md", "the FIRST synthesized read", "witness", GOODJ,
             title="Live read v1")
    ws.write("reads/live.md", "the SECOND synthesized read", "witness", GOODJ,
             title="Live read v2")
    # the file holds the new content
    assert ws.read("reads/live.md") == "the SECOND synthesized read"
    # the old content is not lost — it's folded into .history
    hist = list((ws.root / ".history").rglob("live.md*"))
    assert hist and "FIRST" in hist[0].read_text()
    # the ledger keeps the lineage: the new write supersedes the old
    writes = [e for e in ledger.entries() if e.kind == "memory_write"]
    assert len(writes) == 2
    assert writes[1].supersedes == writes[0].id
    # only ONE active write for the path (no fork)
    active = [e for e in ledger.active("memory_write") if e.body["path"] == "reads/live.md"]
    assert len(active) == 1 and active[0].body["title"] == "Live read v2"
