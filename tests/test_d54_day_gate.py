"""test_d54_day_gate.py — D54: the human's Y/N/T check gates the day-walk.

Pins: one day at a time — a pending reading HALTS the walk and says so;
Y advances; N triggers a blind re-read (the human's reason deliberately NOT in
the prompt); T folds the human's note INTO the re-read prompt (capped 0.8);
the panel refutes BEFORE the human is bothered (and its refute→re-read loop is
bounded); a counts-only digest never gates; review requires a real identity.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from trellis.ingest import DiscordMessage
from trellis.isolation import (AgentIdentity, Isolation, SurfaceAllowlist,
                               ingest_scoped_discord_idempotent)
from trellis.ledger import Ledger
from trellis.memory import Workspace
from trellis.onboard import (DAY_DIGEST_KIND, OnboardingRitual,
                             day_review_state, latest_day_digest,
                             pending_review_day, record_consent, review_day)
from trellis.panel import VerifierPanel
from trellis.providers.mock import MockProvider
from trellis.registry import IdentityRegistry
from trellis.verify import RuleVerifier

CHAN = "chan-g"
_T0 = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def _iso():
    return Isolation(identity=AgentIdentity(name="trellis"),
                     allow=SurfaceAllowlist(read=frozenset((CHAN,)),
                                            act=frozenset()))


def _seed_days(ledger, n_days, per_day=2):
    msgs = []
    for d in range(n_days):
        for i in range(per_day):
            mid = 1000 + d * per_day + i
            msgs.append(DiscordMessage(
                author="brett", content=f"day {d} msg {i}",
                posted_at=_T0 + timedelta(days=d, minutes=i), channel=CHAN,
                channel_name="g", message_id=str(mid), author_id="u-b"))
    ingest_scoped_discord_idempotent(ledger, msgs, _iso(),
                                     IdentityRegistry(ledger))


def _day_json(summary, conf=0.9):
    return json.dumps({"summary": summary, "notable": [], "unclear": [],
                       "confidence": conf})


def _ritual(ledger, tmp_path, ground, provider, verifier=None):
    record_consent(ledger, "alex", True)
    return OnboardingRitual(ledger, Workspace(tmp_path / "ws", ledger),
                            ground=ground, provider=provider,
                            verifier=verifier,
                            registry=IdentityRegistry(ledger), seed_terms=[],
                            days_per_pass=2, day_gate=True)


def test_gate_halts_the_walk_until_yes(ledger, tmp_path, ground):
    _seed_days(ledger, 3)                              # 07-10..12
    maker = MockProvider(id="mock:s")
    for i in range(3):
        maker.enqueue_text(_day_json(f"reading {i}"))
    ritual = _ritual(ledger, tmp_path, ground, maker)

    s1 = ritual.learning_pass()
    assert s1["days_digested"] == ["2026-07-12"]       # ONE day, newest
    assert s1["awaiting_day_review"] == "2026-07-12"   # and it says so

    s2 = ritual.learning_pass()                        # human hasn't answered
    assert s2["days_digested"] == []                   # the walk WAITS
    assert s2["awaiting_day_review"] == "2026-07-12"

    review_day(ledger, "2026-07-12", "yes", "alex")
    s3 = ritual.learning_pass()
    assert s3["days_digested"] == ["2026-07-11"]       # Y → walk on
    assert day_review_state(ledger, "2026-07-12") == "approved"


def test_no_triggers_a_blind_reread(ledger, tmp_path, ground):
    _seed_days(ledger, 1)
    maker = MockProvider(id="mock:s")
    maker.enqueue_text(_day_json("a sloppy first reading"))
    maker.enqueue_text(_day_json("a more careful reading"))
    ritual = _ritual(ledger, tmp_path, ground, maker)
    ritual.learning_pass()
    review_day(ledger, "2026-07-10", "no", "alex",
               note="it missed the pricing thread entirely")

    s = ritual.learning_pass()
    assert s["days_digested"] == ["2026-07-10"]        # re-read, same day
    reread_prompt = maker.calls[-1]["messages"][0]["content"]
    assert "answered NO" in reread_prompt
    assert "did not say why" in reread_prompt
    assert "pricing" not in reread_prompt              # the reason stays WITHHELD
    d = latest_day_digest(ledger, "2026-07-10")
    assert d.body["summary"] == "a more careful reading"
    assert "human's NO" in d.body["basis"]
    assert day_review_state(ledger, "2026-07-10") == "pending"   # re-checked


def test_triangulate_folds_the_note_into_the_reread(ledger, tmp_path, ground):
    _seed_days(ledger, 1)
    maker = MockProvider(id="mock:s")
    maker.enqueue_text(_day_json("close reading"))
    maker.enqueue_text(_day_json("deeper reading", conf=0.95))
    ritual = _ritual(ledger, tmp_path, ground, maker)
    ritual.learning_pass()
    review_day(ledger, "2026-07-10", "triangulate", "alex",
               note="this was the day the alliance fund pivoted")

    ritual.learning_pass()
    reread_prompt = maker.calls[-1]["messages"][0]["content"]
    assert "TRIANGULATE" in reread_prompt
    assert "alliance fund pivoted" in reread_prompt    # the note STEERS
    d = latest_day_digest(ledger, "2026-07-10")
    assert d.body["confidence"] == 0.8                 # T-informed cap, not 0.95
    assert d.body["human_note"] == "this was the day the alliance fund pivoted"


def test_panel_refutes_before_the_human_is_bothered(ledger, tmp_path, ground):
    _seed_days(ledger, 1)
    maker = MockProvider(id="mock:s")
    maker.enqueue_text(_day_json("an overclaimed reading"))
    maker.enqueue_text(_day_json("a humbler reading"))
    vprov = MockProvider(id="mock:haiku")
    for r in ["REFUTED\noverclaims"] * 4 + ["VERIFIED\nok"] * 4:
        vprov.enqueue_text(r)
    panel = VerifierPanel("onboard-panel", vprov, ledger=ledger,
                          rule_verifier=RuleVerifier("onboard-panel:floor",
                                                     ledger, ground))
    ritual = _ritual(ledger, tmp_path, ground, maker, verifier=panel)

    s1 = ritual.learning_pass()
    assert day_review_state(ledger, "2026-07-10") == "refuted_by_panel"
    assert s1["awaiting_day_review"] is None           # machine gate, not human

    s2 = ritual.learning_pass()                        # machine re-read
    assert s2["days_digested"] == ["2026-07-10"]
    assert "panel refuted" in latest_day_digest(
        ledger, "2026-07-10").body["basis"]
    assert day_review_state(ledger, "2026-07-10") == "pending"   # NOW the human


def test_markdown_bold_verdicts_parse(ledger, tmp_path, ground):
    """A lens answering '**VERIFIED**' must count as VERIFIED (live catch:
    it was recorded INSUFFICIENT); 'NOT VERIFIED' must never count."""
    from trellis.verify import CompletionClaim, Evidence, EvidenceKind, \
        ModelVerifier, VerdictStatus
    claim = CompletionClaim(maker="maker-a", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "content")])
    for reply, want in (("**VERIFIED**\nok", VerdictStatus.VERIFIED),
                        ("`REFUTED`\nbad", VerdictStatus.REFUTED),
                        ("NOT VERIFIED\nhm", VerdictStatus.INSUFFICIENT)):
        p = MockProvider(id="mock:v")
        p.enqueue_text(reply)
        v = ModelVerifier("lens-x", p).verify(claim)
        assert v.status == want, reply


def test_panel_judges_against_the_actual_items(ledger, tmp_path, ground):
    """The lenses receive the day's REAL item lines as OUTPUT evidence — never
    only a ledger id they cannot open (the confabulation fix)."""
    _seed_days(ledger, 1)
    maker = MockProvider(id="mock:s")
    maker.enqueue_text(_day_json("a reading"))
    vprov = MockProvider(id="mock:haiku")
    for _ in range(4):
        vprov.enqueue_text("VERIFIED\nok")
    panel = VerifierPanel("onboard-panel", vprov, ledger=ledger,
                          rule_verifier=RuleVerifier("onboard-panel:floor",
                                                     ledger, ground))
    _ritual(ledger, tmp_path, ground, maker, verifier=panel).learning_pass()
    lens_prompt = vprov.calls[0]["messages"][0]["content"]
    assert "day 0 msg 0" in lens_prompt          # the actual item content
    assert "judge the summary against THESE" in lens_prompt


def test_twice_refuted_day_reaches_the_human(ledger, tmp_path, ground):
    _seed_days(ledger, 1)
    maker = MockProvider(id="mock:s")
    for i in range(3):
        maker.enqueue_text(_day_json(f"reading {i}"))
    vprov = MockProvider(id="mock:haiku")
    for _ in range(12):
        vprov.enqueue_text("REFUTED\nno")
    panel = VerifierPanel("onboard-panel", vprov, ledger=ledger,
                          rule_verifier=RuleVerifier("onboard-panel:floor",
                                                     ledger, ground))
    ritual = _ritual(ledger, tmp_path, ground, maker, verifier=panel)
    ritual.learning_pass()                        # read 1 → refuted (rework 0)
    ritual.learning_pass()                        # machine re-read (rework 1) → refuted
    ritual.learning_pass()                        # machine re-read (rework 2) → refuted
    # the machine's allowance is spent — the day is now the HUMAN's call
    assert pending_review_day(ledger) == "2026-07-10"
    review_day(ledger, "2026-07-10", "yes", "alex")
    assert day_review_state(ledger, "2026-07-10") == "approved"


def test_counts_only_digest_never_gates(ledger, tmp_path, ground):
    _seed_days(ledger, 2)
    ritual = _ritual(ledger, tmp_path, ground, provider=None)
    s1 = ritual.learning_pass()
    assert s1["days_digested"] == ["2026-07-11"]
    assert s1["awaiting_day_review"] is None           # nothing claimed → no gate
    s2 = ritual.learning_pass()
    assert s2["days_digested"] == ["2026-07-10"]       # walk continues


def test_review_requires_identity_and_a_real_claim(ledger, tmp_path, ground):
    from trellis.identity import InvalidIdentityError
    with pytest.raises(KeyError):
        review_day(ledger, "2026-07-10", "yes", "alex")   # nothing digested
    _seed_days(ledger, 1)
    ritual = _ritual(ledger, tmp_path, ground, provider=None)
    ritual.learning_pass()
    with pytest.raises(ValueError):                       # counts-only: no claim
        review_day(ledger, "2026-07-10", "yes", "alex")
    with pytest.raises(ValueError):
        review_day(ledger, "2026-07-10", "maybe", "alex")
