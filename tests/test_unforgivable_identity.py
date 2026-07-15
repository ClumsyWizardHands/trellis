"""Watch-list unforgivable — hallucinated embodiment; plus scope-drift/can't-say-no
(#6). No soul.md; the Y/N/T grammar makes N cheap and T honest."""

from datetime import datetime, timedelta, timezone

import pytest

from trellis.decisions import (Decision, DecisionLog, IncompleteTriangulationError,
                               POV, Verdict)
from trellis.emp import (EMP, EMPValidationError, SoulRefusalError, lint_identity,
                         load_emp, HONEST_IDENTITY)


EMP_MD = """# Witness — the contextual reader
authored-by: Alex Crowell

## Ends
- The team's context is held and current, so no one works functionally blind

## Means
- Read-only access to the surface; a workspace beside it; a ledger

## Principles
- Never fail silently
- An unresolved T is a hidden no

## Identity
I am an agent. I perceive through tool calls, not senses. I hold state in files.

## Friction
- 2026-02-22: ignored an explicit ownership instruction (Brett, Alistar) — never again
"""


def test_soul_files_are_refused_by_name(tmp_path):
    for bad in ("SOUL.md", "persona.md", "character-sheet.md", "spirit.md"):
        p = tmp_path / bad
        p.write_text("# I am alive\n## Ends\n- x")
        with pytest.raises(SoulRefusalError):
            load_emp(p)


def test_embodiment_language_is_linted():
    violations = lint_identity(
        "I can see the dashboard.\nLet me eyeball the pixels.\n"
        "I feel sad about this.\nMy eyes are drawn to the chart.")
    labels = {v.label for v in violations}
    assert "claims sight" in labels
    assert "claims felt emotion" in labels
    assert "claims a body" in labels
    # honest tool-perception language is NOT flagged:
    assert lint_identity("I can see the file at logs/gateway.log") == []
    assert lint_identity(HONEST_IDENTITY) == []


def test_emp_loads_and_requires_human_authored_ends(tmp_path):
    p = tmp_path / "witness-emp.md"
    p.write_text(EMP_MD)
    emp = load_emp(p)
    assert emp.name == "Witness"
    assert emp.authored_by == "Alex Crowell"
    assert "hidden no" in emp.principles[1]

    p2 = tmp_path / "no-author.md"
    p2.write_text(EMP_MD.replace("authored-by: Alex Crowell\n", ""))
    with pytest.raises(EMPValidationError, match="authored_by"):
        load_emp(p2)


def test_emp_with_hallucinating_identity_fails_strict(tmp_path):
    p = tmp_path / "bad-identity.md"
    p.write_text(EMP_MD.replace(
        "I am an agent. I perceive through tool calls, not senses. I hold state in files.",
        "I am alive and I feel deeply about the mission. My heart is in this."))
    with pytest.raises(EMPValidationError, match="embodiment"):
        load_emp(p)
    emp = load_emp(p, strict=False)   # non-strict: loads but reports
    assert emp.validate(strict=False)


def test_no_is_first_class_and_returnable(ledger):
    log = DecisionLog(ledger)
    d = Decision(subject="auto-post the digest to #general",
                 verdict=Verdict.N,
                 rationale="stage-don't-fire is doctrine; nothing auto-posts",
                 author="witness:test", emp_lineage="EMP:principles[0]",
                 returnable_note="reopen if the team ratifies autonomous posting")
    entry = log.record(d)
    assert entry.body["verdict"] == "N"


def test_t_without_three_povs_is_refused():
    with pytest.raises(IncompleteTriangulationError, match=">=3 POVs"):
        Decision(subject="memory on-agent vs beside", verdict=Verdict.T,
                 rationale="live fork", author="w", emp_lineage="EMP:principles[1]",
                 povs=[POV("brett", "beside; the agent dies"),
                       POV("clare", "mount the protocol folder")],
                 owner="alex", missing="sarah's read",
                 revisit_at=datetime(2026, 8, 1, tzinfo=timezone.utc))


def test_t_requires_owner_missing_and_revisit(ground):
    povs = [POV("brett", "beside"), POV("clare", "on-agent"), POV("sarah", "workflow-first")]
    with pytest.raises(IncompleteTriangulationError, match="owner"):
        Decision("fork", Verdict.T, "r", "w", "EMP:x", povs=povs,
                 missing="cost data", revisit_at=ground.now())
    with pytest.raises(IncompleteTriangulationError, match="revisit"):
        Decision("fork", Verdict.T, "r", "w", "EMP:x", povs=povs,
                 owner="alex", missing="cost data")
    with pytest.raises(IncompleteTriangulationError, match="missing piece"):
        Decision("fork", Verdict.T, "r", "w", "EMP:x", povs=povs,
                 owner="alex", revisit_at=ground.now())


def test_unresolved_t_surfaces_as_hidden_no(ledger, ground, clock):
    log = DecisionLog(ledger)
    povs = [POV("brett", "a"), POV("clare", "b"), POV("sarah", "c")]
    t = Decision("system of record", Verdict.T, "unsettled", "w", "EMP:ends[0]",
                 povs=povs, owner="alex", missing="verification data",
                 revisit_at=ground.now() + timedelta(days=7))
    log.record(t)
    assert log.hidden_nos() == []
    clock.advance(days=8)
    hidden = log.hidden_nos()
    assert len(hidden) == 1 and hidden[0].body["subject"] == "system of record"


def test_resolution_supersedes_and_lineage_walks_upstream(ledger, ground):
    log = DecisionLog(ledger)
    povs = [POV("brett", "a"), POV("clare", "b"), POV("sarah", "c")]
    t = Decision("obsidian vs drive", Verdict.T, "unsettled", "w", "EMP:means[0]",
                 povs=povs, owner="alex", missing="Brett's July ruling",
                 revisit_at=ground.now() + timedelta(days=14))
    log.record(t)
    y = Decision("obsidian vs drive", Verdict.Y,
                 "keep Obsidian, back up to Drive, energy goes to verification "
                 "(Brett, 2026-07-11)", "alex", "EMP:means[0]")
    log.resolve(t.id, y)
    assert log.hidden_nos() == []          # resolved Ts stop being hidden nos
    chain = log.upstream(y.id)
    assert [c["verdict"] for c in chain] == ["Y", "T"]   # breadcrumbs upstream
