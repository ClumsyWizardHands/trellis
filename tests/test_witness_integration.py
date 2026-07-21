"""Integration — the Witness runs a full cycle against a scripted model:
sense → resolve → act → verify → remember, with every refusal live at once.
This is the harness working end-to-end with zero network and zero API keys."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from trellis.agent import Event, Witness
from trellis.emp import EMP
from trellis.loops import Outcome
from trellis.memory import Workspace
from trellis.passes import Pass, PassExchange, PassStatus
from trellis.prompt import assemble_prompt, PromptBudgetExceeded
from trellis.providers.mock import MockProvider
from trellis.surfaces import ConversationKey, Surface


@pytest.fixture
def emp():
    return EMP(
        name="Witness",
        ends=["the team's context is held and current"],
        means=["read the surface; write beside it"],
        principles=["never fail silently", "an unresolved T is a hidden no",
                    "stage, don't fire"],
        authored_by="Alex Crowell",
    )


@pytest.fixture
def key():
    return ConversationKey("witness:witness", Surface.CHANNEL, "chiefs-of-staffs", "")


@pytest.fixture
def witness(emp, key, ledger, tmp_path, ground):
    ws = Workspace(tmp_path / "ws", ledger)
    ex = PassExchange(tmp_path / "exchange", ground)
    return Witness(emp, MockProvider(id="mock-model"), ledger, ws, key,
                   exchange=ex, ground=ground)


def _events(ground):
    old = ground.now() - timedelta(days=40)
    new = ground.now() - timedelta(hours=2)
    return [
        Event("brett", "time blindness is a liability we must eliminate", old),
        Event("brett", "stared at long enough, time blindness might be an asset", new),
    ]


def test_full_cycle_with_opinions(witness, ground, ledger):
    opinions = [{
        "subject": "treat time-blindness as exploitable, not just a defect",
        "verdict": "Y",
        "rationale": "Brett's newer statement supersedes the older; the read follows",
        "emp_lineage": "EMP:ends[0]",
    }]
    witness.provider.enqueue_text(json.dumps(opinions))
    outcome = witness.witness_cycle(_events(ground))
    assert outcome == Outcome.OK

    # the decision is on the record with lineage
    decisions = ledger.current("decision")
    assert len(decisions) == 1
    assert decisions[0].body["emp_lineage"] == "EMP:ends[0]"

    # the read exists beside the agent, with ages annotated
    read = witness.workspace.read("read/current-read.md")
    assert "40d ago" in read and "2h ago" in read

    # and the completion was checked by a NON-maker, in the ledger. The routine
    # witness claim carries no artifact predicate (just an updated read + a
    # recorded decision), so the honest verdict is PRECONDITIONS_PASSED, NOT
    # VERIFIED — a maker's own loop label no longer launders existence into
    # outcome-grade truth (D25; Codex#7 / FableG5b).
    verifications = [e for e in ledger.entries() if e.kind == "verification"]
    assert len(verifications) == 1
    assert verifications[0].body["maker"] == witness.id
    assert verifications[0].author != witness.id
    assert verifications[0].body["status"] == "preconditions_passed"


def test_empty_opinions_is_nothing_new_not_manufactured_usefulness(witness, ground, ledger):
    """The sycophancy defense: [] is a legitimate answer and lands as a loud
    NOTHING_NEW, not as invented opinions."""
    witness.provider.enqueue_text("[]")
    outcome = witness.witness_cycle(_events(ground))
    assert outcome == Outcome.NOTHING_NEW
    assert ledger.current("decision") == []
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert ends[-1].body["checked"] == ["brett", "brett"]


def test_malformed_model_output_fails_loudly_after_retry(witness, ground, ledger):
    witness.provider.enqueue_text("sure! here are my thoughts: ...")
    witness.provider.enqueue_text("i really think this is fine")
    outcome = witness.witness_cycle(_events(ground))
    assert outcome == Outcome.FAILED
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert "well-formed" in ends[-1].body["reason"]


def test_model_sees_age_tags_and_status_rail(witness, ground):
    witness.provider.enqueue_text("[]")
    witness.witness_cycle(_events(ground))
    call = witness.provider.calls[0]
    assert "[stale" in call["messages"][0]["content"] or \
           "[expired" in call["messages"][0]["content"]   # 40d-old conversation
    assert "fresh" in call["messages"][0]["content"]       # 2h-old line
    assert "Clock (harness-injected" in call["system"]
    assert "sycophancy defect" in call["messages"][0]["content"]


def test_outbound_is_staged_never_fired(witness, ledger):
    witness.propose_outbound("discord_post", "#chiefs-of-staffs", "morning digest")
    assert len(witness.outbox.pending()) == 1
    fired = [e for e in ledger.entries()
             if e.kind == "staged_action" and e.body.get("event") == "fired"]
    assert fired == []


def test_pass_inbox_shows_in_prompt(emp, key, ledger, tmp_path, ground):
    ws = Workspace(tmp_path / "ws2", ledger)
    ex = PassExchange(tmp_path / "ex2", ground)
    w = Witness(emp, MockProvider(), ledger, ws, key, exchange=ex, ground=ground)
    p = Pass("moro", w.id, "confirm the attribution fixes landed with evidence",
             context="see ledger entries tagged verify from yesterday")
    p.transition(PassStatus.SENT, "moro", ground)
    ex.save(p)
    w.provider.enqueue_text("[]")
    w.witness_cycle([Event("x", "hello", ground.now())])
    assert "passes waiting for you: 1" in w.provider.calls[0]["system"]


def test_prompt_budget_is_enforced(emp, ground, key):
    fat_map = [f"file-{i}.md — " + "x" * 200 for i in range(200)]
    # maps are truncated to 20 titles, so even this passes...
    assemble_prompt(emp, ground, key, workspace_map=fat_map)
    # ...but a genuinely fat EMP kernel blows the budget loudly
    fat_emp = EMP(name="Fat", ends=["e" * 2000] * 5, means=["m" * 2000] * 5,
                  principles=["p" * 2000] * 5, authored_by="x")
    with pytest.raises(PromptBudgetExceeded):
        assemble_prompt(fat_emp, ground, key)
