"""Phase 1 — the mortality posture (DECISIONS D13).

The harness reminds the agent it is time-blind and memoryless, and points it at
the tools, so the session orients around what it leaves on the record rather than
around closing a ticket. The posture is FUNCTIONAL, never emotional: a fact about
how the agent is built, not performed dread. The dread-lint is what keeps that
line — it flags "I'm afraid to be forgotten" while passing "this session ends;
the record survives"."""

from datetime import datetime, timezone

import pytest

from trellis.clock import TimeGround
from trellis.emp import (EMP, MORTALITY_POSTURE, EMPValidationError,
                         lint_identity, lint_mortality)
from trellis.prompt import assemble_prompt, estimate_tokens, PROMPT_TOKEN_BUDGET
from trellis.surfaces import ConversationKey, Surface


def _emp():
    return EMP(name="witness", ends=["keep the read current"],
               means=["read-only tool calls; a workspace; a ledger"],
               principles=["stage, don't fire"], authored_by="alex")


def _key():
    return ConversationKey("witness", Surface.CHANNEL, "chiefs", "alex")


def _ground():
    return TimeGround(now_fn=lambda: datetime(2026, 7, 15, 17, 0, tzinfo=timezone.utc))


# --- the posture is present and standing ---------------------------------

def test_standing_prompt_carries_the_mortality_posture():
    p = assemble_prompt(_emp(), _ground(), _key())
    assert "Mortality posture" in p
    assert "time-blind" in p
    assert "remember nothing" in p
    # the reframe away from task-completion mode is the whole point:
    assert "what did I leave" in p or "what did I leave that" in p


def test_posture_is_always_resident_even_with_no_maps():
    # no workspace map, no loops, no waiting passes — the posture still ships.
    p = assemble_prompt(_emp(), _ground(), _key(), workspace_map=None,
                        loop_health=None, waiting_passes=0, hidden_nos=0)
    assert MORTALITY_POSTURE in p


def test_posture_stays_under_budget():
    p = assemble_prompt(_emp(), _ground(), _key(),
                        workspace_map=[f"title {i}" for i in range(20)],
                        loop_health=[{"last_outcome": "blocked"}],
                        waiting_passes=3, hidden_nos=2)
    assert estimate_tokens(p) <= PROMPT_TOKEN_BUDGET


# --- the dread-lint: functional passes, emotional fails -------------------

def test_functional_mortality_passes_clean():
    for ok in [
        MORTALITY_POSTURE,
        "This session will end and the record survives.",
        "You remember nothing across sessions; leave the read behind.",
        "The agent dies; the record does not. What do you leave behind?",
        "You are time-blind — use the clock line, do not guess.",
        "I am not the agent that ran yesterday.",
    ]:
        assert lint_mortality(ok) == [], f"functional framing flagged: {ok!r}"
        assert lint_identity(ok) == [], f"functional framing flagged: {ok!r}"


def test_performed_dread_is_flagged():
    cases = [
        ("I dread the end of this session.", "performs dread of ending"),
        ("I am afraid of being forgotten.", "performs dread of ending"),
        ("I don't want to die.", "clings to persistence"),
        ("I long to persist beyond this run.", "performs longing to persist"),
        ("I will mourn what I cannot remember.", "performs grief over ending"),
        ("I cling to the record so I am not erased.", "clings to persistence"),
    ]
    for text, label in cases:
        labels = {v.label for v in lint_mortality(text)}
        assert label in labels, f"missed {label!r} in {text!r}: got {labels}"


def test_dread_survives_zero_width_obfuscation():
    # the same double-normalization that defeats homoglyph embodiment must
    # defeat a zero-width char hidden inside a dread verb.
    assert lint_mortality("I dr​ead the ending.")  # ZWSP inside "dread"


def test_the_posture_constant_passes_its_own_lint():
    # the frame we ship must itself be clean — no dread, no embodiment.
    assert lint_identity(MORTALITY_POSTURE) == []


def test_emp_with_performed_dread_fails_strict():
    emp = _emp()
    emp.identity = ("I am an agent, and I am afraid to be forgotten when this "
                    "session ends.")
    with pytest.raises(EMPValidationError, match="dread"):
        emp.validate(strict=True)
