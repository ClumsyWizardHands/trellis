"""The context compiler — reload the read before forming an opinion.

Pins the fix for the Codex context-engineering audit's central finding: the
opinion is compiled over the PRIOR READ + relevant decisions + open obligations +
corrections + verifications, not the current batch alone — and the compilation is
deterministic and auditable via a ContextManifest (what was included/excluded and
why)."""

from datetime import timedelta

import pytest

from trellis.context import ContextCompiler
from trellis.decisions import Decision, DecisionLog, POV, Verdict
from trellis.curiosity import Question, QuestionLog, assumption_key
from trellis.memory import Workspace


def _decide(ledger, ground, subject, verdict=Verdict.Y, rationale="because"):
    return DecisionLog(ledger, ground).record(
        Decision(subject, verdict, rationale, "witness", "EMP:ends[0]"))


def test_prior_read_is_reloaded_the_missing_input(ledger, ground, tmp_path):
    ws = Workspace(tmp_path / "ws", ledger, ground)
    ws.write("read/pricing.md", "# Pricing read\nthe funder confirmed", "witness",
             "the current synthesized pricing read exists nowhere else in this form", title="Pricing read")
    cc = ContextCompiler(ledger, ground).compile(subjects=["pricing"], budget_tokens=3000)
    reads = [i for i in cc.items if i.type == "prior_read"]
    assert reads and "Pricing read" in reads[0].summary
    assert reads[0].mandatory is True                 # the read is never dropped


def test_relevant_decisions_are_compiled_in_by_subject(ledger, ground):
    _decide(ledger, ground, "Lock the July pricing framing")
    _decide(ledger, ground, "Hire a second designer")     # unrelated
    cc = ContextCompiler(ledger, ground).compile(subjects=["july pricing framing"])
    subj = [i.summary for i in cc.items if i.type == "decision"]
    assert any("pricing" in s.lower() for s in subj)
    assert not any("designer" in s.lower() for s in subj)   # unrelated, excluded from relevance


def test_open_obligations_are_full_objects_not_counts(ledger, ground, clock):
    povs = [POV("a", "1"), POV("b", "2"), POV("c", "3")]
    DecisionLog(ledger, ground).record(Decision(
        "Pricing model needs the funder view", Verdict.T, "unsettled", "witness", "EMP:means[0]",
        povs=povs, owner="alex", missing="the funder's confirmation",
        revisit_at=ground.now() - timedelta(days=1)))   # already a hidden no
    cc = ContextCompiler(ledger, ground).compile(subjects=["pricing model funder"])
    obl = [i for i in cc.items if i.type == "obligation"]
    assert obl and "funder's confirmation" in obl[0].summary   # the missing piece is carried
    assert obl[0].mandatory is True


def test_stale_curiosity_touching_the_subject_is_surfaced(ledger, ground, clock):
    ql = QuestionLog(ledger, ground)
    ql.ask(Question("funder alignment", "the funder is aligned on pricing",
                    "a statement", "witness", ground.now() + timedelta(hours=1)), "witness")
    clock.advance(hours=2)
    cc = ContextCompiler(ledger, ground).compile(subjects=["funder pricing"])
    assert any(i.type == "obligation" and "STALE QUESTION" in i.summary for i in cc.items)


def test_corrections_are_made_visible(ledger, ground):
    log = DecisionLog(ledger, ground)
    povs = [POV("a", "1"), POV("b", "2"), POV("c", "3")]
    t = log.record(Decision("Release date is a triangulation", Verdict.T, "unsettled",
                            "witness", "EMP:ends[0]", povs=povs, owner="alex",
                            missing="the ship gate", revisit_at=ground.now() + timedelta(days=2)))
    log.resolve(t.body["decision_id"],
                Decision("Release date is a triangulation", Verdict.Y, "gate cleared",
                         "witness", "EMP:ends[0]"))
    cc = ContextCompiler(ledger, ground).compile(subjects=["release date triangulation"])
    corr = [i for i in cc.items if i.type == "correction"]
    assert corr and "superseded" in corr[0].summary


def test_manifest_records_exclusions_with_reasons(ledger, ground):
    # many relevant decisions, a tiny budget → some must be excluded, with a reason
    for i in range(8):
        _decide(ledger, ground, f"pricing decision number {i} about the framing",
                rationale="a fairly long rationale " * 4)
    cc = ContextCompiler(ledger, ground).compile(subjects=["pricing framing"], budget_tokens=120)
    man = cc.manifest.to_dict()
    assert man["excluded"], "a tight budget must record what was dropped and why"
    assert all("reason" in x for x in man["excluded"])
    assert man["budgets"]["tokens_used"] <= 120 + 40   # mandatory can nudge; decisions are bounded


def test_compilation_is_deterministic(ledger, ground):
    _decide(ledger, ground, "Lock the July pricing framing")
    a = ContextCompiler(ledger, ground).compile(subjects=["july pricing"]).manifest.to_dict()
    b = ContextCompiler(ledger, ground).compile(subjects=["july pricing"]).manifest.to_dict()
    assert a == b


def test_prompt_block_groups_prior_read_first(ledger, ground, tmp_path):
    ws = Workspace(tmp_path / "ws", ledger, ground)
    ws.write("read/r.md", "# R\nx", "witness", "this synthesized read exists nowhere else in the record right now", title="The read")
    _decide(ledger, ground, "a pricing decision")
    block = ContextCompiler(ledger, ground).compile(subjects=["pricing", "read"]).to_prompt_block()
    assert "Compiled context" in block
    assert block.index("prior read") < block.index("Relevant prior decisions")   # read first
