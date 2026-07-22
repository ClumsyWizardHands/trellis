"""test_d44_witness.py — D44 (Clare's sketch, ratified 2026-07-22): the Witness
cycle seated under the runner's standing schedules.

Pins: the handler factory builds a real Witness over the configured EMP; a
cycle consumes only events SINCE the last firing (write-time cursor via the
scheduler's ledger record); a quiet tick spends NOTHING on the model; missing
EMP or model seat degrades to ({}, honest note) — never a silent half-wire;
the runner fires it end-to-end and opinions land as decisions.
"""

from __future__ import annotations

import json
from datetime import timedelta

from trellis.cli import _DEMO_EMP, _witness_handlers
from trellis.ingest import DiscordMessage
from trellis.isolation import (AgentIdentity, Isolation, SurfaceAllowlist,
                               ingest_scoped_discord_idempotent)
from trellis.ledger import Ledger
from trellis.providers.mock import MockProvider
from trellis.registry import IdentityRegistry
from trellis.runner import Runner

CHAN = "chan-w"


def _iso():
    return Isolation(identity=AgentIdentity(name="trellis"),
                     allow=SurfaceAllowlist(read=frozenset((CHAN,)),
                                            act=frozenset()))


def _seed(ledger, ground, texts, start_id=1000):
    msgs = [DiscordMessage(author="brett", content=t,
                           posted_at=ground.now(), channel=CHAN,
                           channel_name="w", message_id=str(start_id + i),
                           author_id="u-brett")
            for i, t in enumerate(texts)]
    ingest_scoped_discord_idempotent(ledger, msgs, _iso(),
                                     IdentityRegistry(ledger))


def _env(monkeypatch, tmp_path):
    emp = tmp_path / "emp.md"
    emp.write_text(_DEMO_EMP, encoding="utf-8")
    monkeypatch.setenv("TRELLIS_EMP_PATH", str(emp))
    monkeypatch.setenv("TRELLIS_VAULT_PATH", str(tmp_path / "ws"))
    monkeypatch.setenv("TRELLIS_LEDGER", str(tmp_path / "l.jsonl"))


def _opinion():
    return json.dumps([{
        "subject": "the July framing supersedes April",
        "verdict": "Y",
        "rationale": "newer supersedes older and says so",
        "emp_lineage": "EMP:principles[0]",
    }])


def test_witness_seated_and_opinions_land(monkeypatch, tmp_path, ground):
    _env(monkeypatch, tmp_path)
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    _seed(ledger, ground, ["time blindness might be an asset"])
    maker = MockProvider(id="mock:sonnet")
    maker.enqueue_text(_opinion())
    handlers, notes = _witness_handlers(ledger, provider=maker,
                                        verifier=None)
    assert "witness.cycle" in handlers
    assert any("witness seated" in n for n in notes)

    runner = Runner(ledger, ground)
    report = runner.tick(handlers=handlers)
    fired = dict(report["fired"])
    assert fired.get("witness.cycle") == "ok"
    decisions = ledger.active("decision")
    assert any("July framing" in e.body.get("subject", "") for e in decisions)
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert ends and ends[-1].body["outcome"] == "ok"


def test_quiet_cycle_spends_nothing_on_the_model(monkeypatch, tmp_path,
                                                 ground, clock):
    _env(monkeypatch, tmp_path)
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    _seed(ledger, ground, ["one event"])
    maker = MockProvider(id="mock:sonnet")
    maker.enqueue_text(_opinion())
    handlers, _ = _witness_handlers(ledger, provider=maker, verifier=None)
    runner = Runner(ledger, ground)
    runner.tick(handlers=handlers)
    calls_after_first = len(maker.calls)
    assert calls_after_first >= 1

    # nothing new arrived; the next due cycle returns without a model call
    clock.advance(minutes=20)
    report = runner.tick(handlers=handlers)
    assert dict(report["fired"]).get("witness.cycle") == "ok"
    assert len(maker.calls) == calls_after_first        # zero spend on quiet

    # a NEW message (after the last firing) is consumed by the next cycle
    clock.advance(minutes=20)
    _seed(ledger, ground, ["a genuinely new statement"], start_id=2000)
    maker.enqueue_text(_opinion().replace("July framing", "new statement claim"))
    runner.tick(handlers=handlers)
    assert len(maker.calls) == calls_after_first + 1


def test_missing_emp_or_seat_degrades_honestly(monkeypatch, tmp_path, ground):
    monkeypatch.setenv("TRELLIS_EMP_PATH", str(tmp_path / "absent.md"))
    monkeypatch.setenv("TRELLIS_LEDGER", str(tmp_path / "l.jsonl"))
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    handlers, notes = _witness_handlers(ledger, provider=MockProvider())
    assert handlers == {}
    assert notes and "no EMP" in notes[0]

    _env(monkeypatch, tmp_path)
    for var in ("TRELLIS_PROVIDER",):
        monkeypatch.delenv(var, raising=False)
    handlers2, notes2 = _witness_handlers(ledger)       # no seat configured
    assert handlers2 == {}
    assert notes2 and "model seat unavailable" in notes2[0]


def test_shipped_chief_of_staff_emp_seats(monkeypatch, tmp_path, ground):
    """The merged EoC EMP (PR #1) actually loads through the D44 path."""
    from pathlib import Path
    emp = Path(__file__).resolve().parents[1] / "examples" / "chief-of-staff-emp.md"
    monkeypatch.setenv("TRELLIS_EMP_PATH", str(emp))
    monkeypatch.setenv("TRELLIS_VAULT_PATH", str(tmp_path / "ws"))
    monkeypatch.setenv("TRELLIS_LEDGER", str(tmp_path / "l.jsonl"))
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    handlers, notes = _witness_handlers(ledger, provider=MockProvider(id="mock:x"),
                                        verifier=None)
    assert "witness.cycle" in handlers
    assert any("Chief of Staff" in n for n in notes)
