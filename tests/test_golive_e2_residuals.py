"""Go-live E2 residuals — the two holes the prior fleet's own verifier confirmed
were still open after the Codex#11 / Codex#12 fixes landed.

RESIDUAL 1 (Codex#11 incomplete) — `_parse_opinions` validated verdict, povs, and
revisit_days inside the retryable block, but left `subject`, `rationale`,
`emp_lineage`, and `owner` type-unchecked. A syntactically-valid opinion with a
numeric `subject` or an object `rationale` passed parsing, then crashed LATE in
Decision.__post_init__ (`.strip()` on a non-string) and ESCAPED the cycle as an
unhandled crash. A bad field TYPE must trigger the RETRY like any other malformed
output — never a late crash.

RESIDUAL 2 (Codex#12 side effect) — spending the last allowed provider call on a
VALID opinion retroactively relabeled the whole cycle BUDGET_EXCEEDED, which
suppressed run.ok() and SKIPPED the cost-free RuleVerifier, leaving a recorded
decision UNVERIFIED. A cycle that recorded its decision(s) within budget must still
run its free (non-provider) verification and end with a non-error outcome. The cap
must prevent an ADDITIONAL provider call, not invalidate completed, in-budget work.
"""

import json

import pytest

from trellis.agent import Event, Witness
from trellis.emp import EMP
from trellis.loops import Budget, Outcome
from trellis.memory import Workspace
from trellis.providers.mock import MockProvider
from trellis.surfaces import ConversationKey, Surface


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


def _make_witness(emp, key, ledger, tmp_path, ground, provider=None, **kw):
    ws = Workspace(tmp_path / "ws", ledger, ground)
    return Witness(emp, provider or MockProvider(id="mock-model"), ledger, ws, key,
                   ground=ground, **kw)


def _valid_opinion(subject="lock the july pricing framing"):
    return [{
        "subject": subject,
        "verdict": "Y",
        "rationale": "the newer signal supersedes the older; the read follows",
        "emp_lineage": "EMP:ends[0]",
    }]


# --------------------------------------------------------------------------
# RESIDUAL 1 — a bad field TYPE must trigger the RETRY, not a late crash.
# --------------------------------------------------------------------------

def test_non_string_subject_triggers_retry_not_a_late_crash(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    bad = [{
        "subject": 12345,                       # numeric subject: valid JSON, wrong type
        "verdict": "Y",
        "rationale": "a plausible rationale",
        "emp_lineage": "EMP:ends[0]",
    }]
    w.provider.enqueue_text(json.dumps(bad))    # call 1: bad shape
    w.provider.enqueue_text("[]")               # retry: clean

    outcome = w.witness_cycle([Event("brett", "pricing", ground.now())])   # must NOT raise

    assert outcome == Outcome.NOTHING_NEW               # the retry recovered
    assert len(w.provider.calls) == 2                   # the bad type cost a RETRY
    assert ledger.current("decision") == []             # nothing malformed slipped through


def test_object_rationale_triggers_retry_not_a_late_crash(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    bad = [{
        "subject": "release date",
        "verdict": "Y",
        "rationale": {"text": "not a plain-language string"},   # object rationale
        "emp_lineage": "EMP:ends[0]",
    }]
    w.provider.enqueue_text(json.dumps(bad))    # call 1: bad shape
    w.provider.enqueue_text("[]")               # retry: clean

    outcome = w.witness_cycle([Event("brett", "release date", ground.now())])   # must NOT raise

    assert outcome == Outcome.NOTHING_NEW
    assert len(w.provider.calls) == 2
    assert ledger.current("decision") == []


def test_non_string_emp_lineage_triggers_retry(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    bad = [{
        "subject": "release date",
        "verdict": "Y",
        "rationale": "a plausible rationale",
        "emp_lineage": ["EMP:ends[0]"],         # list, not a string
    }]
    w.provider.enqueue_text(json.dumps(bad))
    w.provider.enqueue_text("[]")

    outcome = w.witness_cycle([Event("brett", "release date", ground.now())])   # must NOT raise

    assert outcome == Outcome.NOTHING_NEW
    assert len(w.provider.calls) == 2
    assert ledger.current("decision") == []


# --------------------------------------------------------------------------
# RESIDUAL 2 — a VALID opinion under max_provider_calls=1 is recorded AND
# verified AND ends with a non-error outcome; the cap only blocks a SECOND call.
# --------------------------------------------------------------------------

def test_one_call_valid_opinion_is_recorded_and_verified(emp, key, ledger, tmp_path, ground):
    budget = Budget(max_provider_calls=1)
    w = _make_witness(emp, key, ledger, tmp_path, ground, budget=budget)
    w.provider.enqueue_text(json.dumps(_valid_opinion()))   # the one allowed call: valid

    outcome = w.witness_cycle([Event("brett", "the july pricing framing", ground.now())])

    # exactly one provider call was permitted and spent on real work
    assert len(w.provider.calls) == 1
    assert budget.spent_provider_calls == 1
    # the decision was recorded ...
    assert len(ledger.current("decision")) == 1
    # ... AND the free (non-provider) verifier still ran ...
    verifications = [e for e in ledger.entries() if e.kind == "verification"]
    assert len(verifications) == 1, "an in-budget completed decision must still be verified"
    # ... and the cycle ends with a non-error outcome, not BUDGET_EXCEEDED.
    assert outcome == Outcome.OK
