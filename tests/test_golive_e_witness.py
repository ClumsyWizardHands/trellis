"""Witness-cycle correctness & safety — the go-live hardening regressions (lane E).

Each test reproduces a defect the pre-live audits confirmed, then pins the fix:

  * FableG2  — a repeated opinion raises CollidingDecisionError that ESCAPES the
    cycle and crashes the driver; must fail-closed-but-alive (skip is ledgered,
    no crash, no silent fork).
  * Codex#10 — a verifier exception after loop_run_end:ok leaves an OK cycle with
    NO verification record; the failure must be ledgered before it propagates.
  * Codex#11 — malformed-but-plausible structured output (povs:["not-an-object"])
    passes parsing then crashes _to_decision; a bad shape must trigger the RETRY.
  * Codex#12 — max_provider_calls=1 permitted two provider calls; enforce it
    prospectively so exactly one call is made.
  * Codex#8  — the compiler passed only a title-pointer of the prior read (never
    its content) and recorded no manifest on zero-event cycles; load a bounded
    excerpt and manifest every cycle, privacy-at-selection fail-closed.
"""

import json
from datetime import timedelta

import pytest

from trellis.agent import Event, Witness
from trellis.context import ContextCompiler
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


def _one_opinion(subject="lock the july pricing framing"):
    return [{
        "subject": subject,
        "verdict": "Y",
        "rationale": "the newer signal supersedes the older; the read follows",
        "emp_lineage": "EMP:ends[0]",
    }]


# --------------------------------------------------------------------------
# FableG2 — a repeated opinion must not crash the driver or silently fork.
# --------------------------------------------------------------------------

def test_repeated_opinion_does_not_crash_and_does_not_fork(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    events = [Event("brett", "the july pricing framing", ground.now())]

    w.provider.enqueue_text(json.dumps(_one_opinion()))
    out1 = w.witness_cycle(events)
    assert out1 == Outcome.OK
    assert len(ledger.current("decision")) == 1

    # The SAME batch again: DecisionLog.record() raises CollidingDecisionError.
    # It must be caught per-opinion — the cycle survives, no second live head is
    # minted, and the skip is on the record (nothing silently lost).
    w.provider.enqueue_text(json.dumps(_one_opinion()))
    out2 = w.witness_cycle(events)          # must NOT raise

    assert len(ledger.current("decision")) == 1, "a second live head is a silent fork"
    skipped = [e for e in ledger.entries() if e.kind == "opinion_skipped"]
    assert len(skipped) == 1
    assert "collide" in skipped[0].body["reason"].lower() or \
           "reopen" in skipped[0].body["reason"].lower()
    assert out2 in (Outcome.OK, Outcome.NOTHING_NEW)


# --------------------------------------------------------------------------
# Codex#10 — a verifier crash must be ledgered, never leave an OK cycle
# looking silently verified.
# --------------------------------------------------------------------------

class _ExplodingVerifier:
    id = "rule-verifier:exploding"

    def verify(self, claim):
        raise RuntimeError("verifier endpoint down")


def test_verifier_crash_is_ledgered_before_it_propagates(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground, verifier=_ExplodingVerifier())
    w.provider.enqueue_text(json.dumps(_one_opinion()))

    with pytest.raises(RuntimeError):
        w.witness_cycle([Event("brett", "the july pricing framing", ground.now())])

    # the cycle was recorded OK — but the verification failure is NOT silent:
    errs = [e for e in ledger.entries() if e.kind == "verification_error"]
    assert len(errs) == 1
    assert errs[0].body["status"] == "error"
    assert "endpoint down" in errs[0].body["error"]


# --------------------------------------------------------------------------
# Codex#11 — a plausible-but-malformed nested shape must trigger the retry,
# not a late TypeError in _to_decision.
# --------------------------------------------------------------------------

def test_bad_pov_shape_triggers_retry_not_a_late_crash(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    bad = [{
        "subject": "release date",
        "verdict": "T",
        "rationale": "unsettled",
        "emp_lineage": "EMP:ends[0]",
        "povs": ["not-an-object"],          # syntactically valid JSON, wrong shape
    }]
    w.provider.enqueue_text(json.dumps(bad))   # first call: malformed shape
    w.provider.enqueue_text("[]")              # retry: clean

    outcome = w.witness_cycle([Event("brett", "release date", ground.now())])

    assert outcome == Outcome.NOTHING_NEW              # the retry recovered
    assert len(w.provider.calls) == 2                  # the bad shape cost a RETRY
    assert ledger.current("decision") == []            # nothing malformed slipped through


# --------------------------------------------------------------------------
# Codex#12 — max_provider_calls=1 must permit exactly one provider call.
# --------------------------------------------------------------------------

def test_one_provider_call_budget_permits_exactly_one_call(emp, key, ledger, tmp_path, ground):
    budget = Budget(max_provider_calls=1)
    w = _make_witness(emp, key, ledger, tmp_path, ground, budget=budget)
    w.provider.enqueue_text("garbage, not an array")   # call 1 (malformed)
    w.provider.enqueue_text("[]")                       # must NEVER be consumed

    outcome = w.witness_cycle([Event("brett", "anything", ground.now())])

    assert len(w.provider.calls) == 1, "max_provider_calls=1 must permit exactly one call"
    assert budget.spent_provider_calls == 1
    assert outcome == Outcome.BUDGET_EXCEEDED


def test_budget_marks_exhaustion_immediately_after_the_limiting_charge():
    b = Budget(max_provider_calls=1)
    assert b.exceeded(0) is None
    b.charge()
    assert b.exceeded(0) is not None                   # exhausted the moment the limit is met


# --------------------------------------------------------------------------
# Codex#8 — the prior read CONTENT reaches the model, and a manifest is
# recorded on EVERY cycle including zero-event cycles.
# --------------------------------------------------------------------------

def test_prior_read_content_reaches_the_model(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    w.workspace.write(
        "read/current-read.md",
        "# Pricing read\nULTRA_SECRET_PRIOR_FACT: the funder confirmed the July number",
        w.id,
        "the current synthesized pricing read exists nowhere else in this form",
        title="Pricing read")

    w.provider.enqueue_text("[]")
    w.witness_cycle([Event("brett", "the july pricing number", ground.now())])

    user_msg = w.provider.calls[0]["messages"][0]["content"]
    assert "ULTRA_SECRET_PRIOR_FACT" in user_msg, "the model never actually got its prior read"


def test_zero_event_cycle_still_records_a_manifest(emp, key, ledger, tmp_path, ground):
    w = _make_witness(emp, key, ledger, tmp_path, ground)
    w.provider.enqueue_text("[]")
    outcome = w.witness_cycle([])                       # zero events

    assert outcome == Outcome.NOTHING_NEW
    manifests = [e for e in ledger.entries() if e.kind == "context_manifest"]
    assert len(manifests) == 1, "even a zero-event cycle must compile + manifest"


def test_more_private_read_content_is_withheld_from_a_public_packet(ledger, ground, tmp_path):
    """Privacy-at-selection: a DM-scoped read's CONTENT must not load into a
    CHANNEL packet; the pointer may remain, the secret body may not."""
    ws = Workspace(tmp_path / "ws", ledger, ground)
    # a public read (untagged, the agent's own) — content loads
    ws.write("read/public.md", "# Public\nPUBLIC_FACT is shareable", "witness:w",
             "this synthesized public read exists nowhere else in this form",
             title="Public read")
    # a DM-scoped read — content must be withheld from a channel packet
    (ws.root / "read").mkdir(parents=True, exist_ok=True)
    (ws.root / "read" / "secret.md").write_text("# Secret\nDM_ONLY_SECRET leak me not",
                                                encoding="utf-8")
    ledger.append("memory_write", "witness:w",
                  {"path": "read/secret.md", "title": "Secret read", "surface": "dm"},
                  tags=("memory",))

    channel_key = ConversationKey("witness:w", Surface.CHANNEL, "chiefs", "")
    cc = ContextCompiler(ledger, ground).compile(
        subjects=["fact"], workspace=ws, packet_key=channel_key)
    block = cc.to_prompt_block()

    assert "PUBLIC_FACT" in block                       # the agent's own read loads
    assert "DM_ONLY_SECRET" not in block                # the more-private read is withheld
    reasons = " ".join(x["reason"] for x in cc.manifest.excluded)
    assert "withheld" in reasons or "private" in reasons
