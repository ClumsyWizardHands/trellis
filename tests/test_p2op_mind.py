"""Phase-2 operate — the agency-preserving mind-change (DECISIONS D33/D34/D35).

The interim Phase-1 stopgap BLOCKED the agent from changing its mind: a repeated
opinion crashed the driver, and the fix caught CollidingDecisionError and recorded
an `opinion_skipped: reopen required`. D33 says that is wrong — the Witness may
revise its own opinion on its OWN authority. Every change is a LOGGED, portal-
visible supersession, machine-verified by a cheap independent seat (D34); a HUMAN
is in the loop only for a minimal high-stakes class (reversing something a human
affirmed) or a verifier REFUTATION (D35).

Each test pins one property:
  * a live Y/N is superseded AUTONOMOUSLY (reopen + resolve), one live head kept
  * a reworded repeat on the SAME question-key FOLDS onto the head (effective_key)
  * an identical repeat is an idempotent NO-OP
  * default (non-autonomous) decide() still refuses — backward compatible
  * reversing a HUMAN-AFFIRMED decision ESCALATES instead of auto-superseding
  * the witness records-then-supersedes without crashing or forking
  * a decision write is machine-verified (convene called) when a seat is set
  * a REFUTED decision is CONTESTED + escalated, never blocked from the record
"""

import json
from datetime import timedelta

import pytest

from trellis.agent import Event, Witness
from trellis.decisions import Decision, DecisionLog, POV, Verdict, question_key
from trellis.emp import EMP
from trellis.ledger import Ledger
from trellis.navigate import (HighStakesEscalation, Navigator,
                              ReopenRequiredError)
from trellis.memory import Workspace
from trellis.providers.mock import MockProvider
from trellis.surfaces import ConversationKey, Surface
from trellis.verify import ModelVerifier, contested_items


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------

@pytest.fixture
def emp():
    return EMP(
        name="Witness",
        ends=["the team's context is held and current"],
        means=["read the surface; write beside it"],
        principles=["never fail silently", "stage, don't fire"],
        authored_by="Alex Crowell",
    )


@pytest.fixture
def key():
    return ConversationKey("witness:witness", Surface.CHANNEL, "chiefs", "")


def _yn(subject, verdict=Verdict.Y, rationale="a real rationale on the record",
        author="witness", key=None):
    return Decision(subject, verdict, rationale, author, "EMP:principles[0]", key=key)


def _t(subject, revisit):
    return Decision(subject, Verdict.T, "a live fork", "witness", "EMP:ends[0]",
                    povs=[POV("brett", "beside"), POV("clare", "on-agent"),
                          POV("sarah", "workflow-first")],
                    owner="alex", missing="a cost comparison", revisit_at=revisit)


def _make_witness(emp, key, ledger, tmp_path, ground, provider=None, **kw):
    ws = Workspace(tmp_path / "ws", ledger, ground)
    return Witness(emp, provider or MockProvider(id="mock-model"), ledger, ws, key,
                   ground=ground, **kw)


def _opinion(subject="lock the july pricing framing", verdict="Y",
             rationale="the newer signal supersedes the older; the read follows"):
    return [{"subject": subject, "verdict": verdict, "rationale": rationale,
             "emp_lineage": "EMP:ends[0]"}]


# ==========================================================================
# Navigator.decide — the autonomous mind-change grammar
# ==========================================================================

def test_autonomous_supersede_keeps_one_live_head_with_lineage(ledger):
    nav = Navigator(DecisionLog(ledger))
    nav.decide(_yn("Ship the pricing email", Verdict.N))            # brand new
    entry = nav.decide(_yn("Ship the pricing email", Verdict.Y,
                           rationale="the funder confirmed; I changed my mind"),
                       autonomous=True)                              # revise autonomously
    heads = ledger.active("decision")
    assert len(heads) == 1, "autonomous revision must keep exactly one live head"
    assert heads[0].body["verdict"] == "Y"
    # the change is logged as a supersession WITH lineage back to the prior N,
    # and a reopen-marker records that the agent revised its own opinion.
    up = DecisionLog(ledger).upstream(entry.body["decision_id"])
    assert up[-1]["verdict"] == "N", "lineage back to the superseded head is kept"
    reopens = [e for e in ledger.entries() if e.kind == "reopen"]
    assert len(reopens) == 1, "the autonomous reopen is on the record (portal-visible)"


def test_reworded_repeat_on_same_key_folds_not_forks(ledger):
    """The effective_key() fix: a keyed opinion (obs:/op:) reworded on the SAME
    key must fold onto the head, not fork a second live head. Before the fix,
    decide() keyed off question_key(subject) — a reworded subject missed the head
    and record() then collided (crash/fork)."""
    nav = Navigator(DecisionLog(ledger))
    nav.decide(_yn("Adopt framing A", Verdict.Y, key="op:pricing"), autonomous=True)
    nav.decide(_yn("Adopt the framing (reworded entirely)", Verdict.N,
                   rationale="the room moved", key="op:pricing"),
               autonomous=True)                       # SAME key, reworded — must NOT crash
    heads = ledger.active("decision")
    assert len(heads) == 1, "a reworded repeat on the same key must not fork"
    assert heads[0].body["verdict"] == "N"
    assert heads[0].body["question_key"] == "op:pricing"


def test_identical_repeat_is_an_idempotent_noop(ledger):
    nav = Navigator(DecisionLog(ledger))
    nav.decide(_yn("Lock the framing", Verdict.Y))
    before = len(ledger.entries())
    entry = nav.decide(_yn("Lock the framing", Verdict.Y), autonomous=True)
    assert len(ledger.entries()) == before, "an identical repeat must append NOTHING"
    assert entry.body["verdict"] == "Y"
    assert len(ledger.active("decision")) == 1


def test_decide_without_autonomous_still_refuses_a_live_yn(ledger):
    """Backward compatibility: the default (non-autonomous) path keeps the
    interim contract — a fresh Y/N on a live question raises ReopenRequiredError."""
    nav = Navigator(DecisionLog(ledger))
    nav.decide(_yn("Stage-don't-fire the email", Verdict.N))
    with pytest.raises(ReopenRequiredError):
        nav.decide(_yn("Stage-don't-fire the email", Verdict.Y))


def test_autonomous_decide_still_resolves_a_live_T(ledger, ground):
    nav = Navigator(DecisionLog(ledger))
    nav.decide(_t("System of record", ground.now() + timedelta(days=7)))
    nav.decide(_yn("System of record", Verdict.Y), autonomous=True)   # resolve the T
    head = DecisionLog(ledger).active_head(question_key("System of record"))
    assert head.body["verdict"] == "Y"


def test_reversing_a_human_affirmed_decision_escalates(ledger):
    """The MINIMAL high-stakes class (D33): reversing something a human affirmed
    is NOT autonomous — it raises to escalate, and the head is left intact."""
    log = DecisionLog(ledger)
    nav = Navigator(log)
    d = nav.decide(_yn("Auto-post the digest", Verdict.N, author="witness"))
    did = d.body["decision_id"]
    # a HUMAN affirms the decision (the web /affirm shape)
    ledger.append("affirmation", "alex", {"decision_id": did}, tags=("affirm", did))
    with pytest.raises(HighStakesEscalation):
        nav.decide(_yn("Auto-post the digest", Verdict.Y,
                       rationale="the team asked for it"), autonomous=True)
    # the human-affirmed head is untouched — no silent auto-reversal
    assert log.active_head(question_key("Auto-post the digest")).body["verdict"] == "N"


def test_agent_affirming_its_own_head_is_not_high_stakes(ledger):
    """Only an INDEPENDENT (human) affirmation gates. The agent affirming its own
    decision cannot lock itself out of revising it."""
    log = DecisionLog(ledger)
    nav = Navigator(log)
    d = nav.decide(_yn("Draft cadence", Verdict.N, author="witness"))
    ledger.append("affirmation", "witness", {"decision_id": d.body["decision_id"]})
    nav.decide(_yn("Draft cadence", Verdict.Y, rationale="reconsidered"),
               autonomous=True)                       # must NOT escalate
    assert log.active_head(question_key("Draft cadence")).body["verdict"] == "Y"


# ==========================================================================
# Witness — routed through Navigator.decide (D33 end to end)
# ==========================================================================

def test_witness_revised_opinion_supersedes_autonomously(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    events = [Event("brett", "the july pricing framing", ground.now())]

    w.provider.enqueue_text(json.dumps(_opinion(verdict="N")))
    w.witness_cycle(events)
    assert len(ledger.current("decision")) == 1

    # a CHANGED opinion on the same subject — the agent revises its mind. No crash,
    # no fork, no opinion_skipped: it supersedes to one live head, logged.
    w.provider.enqueue_text(json.dumps(_opinion(verdict="Y",
                                                rationale="the funder confirmed the number")))
    w.witness_cycle(events)

    heads = ledger.current("decision")
    assert len(heads) == 1, "a revised opinion must not fork a second live head"
    assert heads[0].body["verdict"] == "Y"
    assert [e for e in ledger.entries() if e.kind == "opinion_skipped"] == [], \
        "the interim block-and-skip stopgap must be gone (D33)"
    assert [e for e in ledger.entries() if e.kind == "reopen"], \
        "the autonomous mind-change is logged as a reopen + supersession"


def test_witness_identical_repeat_is_a_noop(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    events = [Event("brett", "the july pricing framing", ground.now())]

    w.provider.enqueue_text(json.dumps(_opinion()))
    w.witness_cycle(events)
    decisions_after_first = [e for e in ledger.entries() if e.kind == "decision"]

    w.provider.enqueue_text(json.dumps(_opinion()))     # identical again
    w.witness_cycle(events)

    assert len(ledger.current("decision")) == 1
    decisions_after_second = [e for e in ledger.entries() if e.kind == "decision"]
    assert len(decisions_after_second) == len(decisions_after_first), \
        "an identical repeat must append no new decision entry"
    assert [e for e in ledger.entries() if e.kind == "opinion_skipped"] == []


def test_witness_convenes_verification_on_a_decision_write(emp, key, ledger, tmp_path, ground):
    verifier = ModelVerifier("haiku-verifier:test", MockProvider(id="mock-haiku"))
    verifier.provider.enqueue_text("VERIFIED\nthe decision entry is well-formed")
    w = _make_witness(emp, key, ledger, tmp_path, ground, decision_verifier=verifier)

    w.provider.enqueue_text(json.dumps(_opinion()))
    w.witness_cycle([Event("brett", "the july pricing framing", ground.now())])

    convened = [e for e in ledger.entries()
                if e.kind == "verification"
                and str(e.body.get("task", "")).startswith("decision write")]
    assert convened, "every recorded decision write must be independently verified (D34)"


def test_witness_refuted_decision_is_contested_not_blocked(emp, key, ledger, tmp_path, ground):
    verifier = ModelVerifier("haiku-verifier:test", MockProvider(id="mock-haiku"))
    verifier.provider.enqueue_text("REFUTED\nthis opinion rests on stale state")
    w = _make_witness(emp, key, ledger, tmp_path, ground, decision_verifier=verifier)

    w.provider.enqueue_text(json.dumps(_opinion()))
    w.witness_cycle([Event("brett", "the july pricing framing", ground.now())])

    # D35: a refutation CONTESTS + escalates; it does NOT block the agent from
    # having recorded its opinion (D33). The decision is still a live head.
    assert len(ledger.current("decision")) == 1, "a refuted opinion is still on the record"
    contested = contested_items(ledger)
    assert contested and contested[0]["escalated"], "REFUTED must escalate to a human"


def test_witness_escalates_reversing_a_human_affirmed_head(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    events = [Event("brett", "the july pricing framing", ground.now())]

    w.provider.enqueue_text(json.dumps(_opinion(verdict="N")))
    w.witness_cycle(events)
    head = ledger.current("decision")[0]
    ledger.append("affirmation", "alex", {"decision_id": head.body["decision_id"]})

    # the agent now wants to reverse a HUMAN-affirmed decision → escalate, not flip.
    w.provider.enqueue_text(json.dumps(_opinion(verdict="Y",
                                                rationale="reconsidered on my own")))
    w.witness_cycle(events)

    assert ledger.current("decision")[0].body["verdict"] == "N", \
        "a human-affirmed decision is not auto-reversed"
    escalations = [e for e in ledger.entries() if e.kind == "opinion_escalated"]
    assert len(escalations) == 1 and "human" in escalations[0].body["reason"].lower()
