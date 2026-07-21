"""Ledger-backed scheduler (Codex High 11): scheduling is verifiable state that
survives a restart — not an in-memory list that a fresh process forgets."""

from datetime import timedelta

from trellis.clock import ScheduleKind, TimeGround
from trellis.ledger import Ledger
from trellis.scheduler import LedgerScheduler


def test_registration_and_firing_survive_a_restart(tmp_path, clock, ground):
    path = tmp_path / "l.jsonl"
    s = LedgerScheduler(Ledger(path, ground), ground)
    s.register("witness.reflect", timedelta(hours=24), "alex", purpose="daily reflection")
    s.record_firing("witness.reflect", "witness")
    # DROP the process — a fresh scheduler reconstructs from the ledger alone
    s2 = LedgerScheduler(Ledger(path, ground), ground)
    assert "witness.reflect" in s2.registered()
    assert s2.last_fired("witness.reflect") is not None
    v = s2.verify("witness.reflect")
    assert v["ok"] is True                            # NOT "never fired" (the old bug)


def test_a_registered_but_never_fired_schedule_is_flagged(tmp_path, ground):
    s = LedgerScheduler(Ledger(tmp_path / "l.jsonl", ground), ground)
    s.register("ghost.cron", timedelta(hours=1), "alex")
    v = s.verify("ghost.cron")
    assert v["ok"] is False and "never fired" in v["reason"]


def test_is_due_respects_cadence(tmp_path, clock, ground):
    s = LedgerScheduler(Ledger(tmp_path / "l.jsonl", ground), ground)
    s.register("x", timedelta(hours=6), "alex")
    assert s.is_due("x")                              # never fired → due
    s.record_firing("x", "witness")
    assert not s.is_due("x")                          # just fired → not due
    clock.advance(hours=7)
    assert s.is_due("x")                              # past the interval → due again


def test_active_hours_window_wraps_midnight(tmp_path, ground):
    from trellis.clock import TimeGround as TG
    from datetime import datetime, timezone
    def at(h):
        return TG(now_fn=lambda: datetime(2026, 7, 21, h, 0, tzinfo=timezone.utc))
    for h, expect in [(23, True), (3, True), (12, False)]:
        g = at(h)
        s = LedgerScheduler(Ledger(tmp_path / f"l{h}.jsonl", g), g)
        s.register("night", timedelta(hours=1), "alex", active_hours=(22, 6))
        assert s.is_due("night") is expect            # (22,6) wraps midnight


def test_run_due_fires_handlers_and_records_even_on_error(tmp_path, clock, ground):
    s = LedgerScheduler(Ledger(tmp_path / "l.jsonl", ground), ground)
    s.register("good", timedelta(hours=1), "alex")
    s.register("bad", timedelta(hours=1), "alex")
    ran = []
    def boom(): raise RuntimeError("handler failed")
    results = s.run_due({"good": lambda: ran.append("good"), "bad": boom}, "witness")
    assert ("good", "ok") in results and ("bad", "failed") in results
    assert ran == ["good"]
    # both firings are on the record (a schedule that errored still RAN — not silent)
    assert s.last_fired("good") is not None and s.last_fired("bad") is not None
    assert s.verify("bad")["ok"] is True              # it fired (outcome failed, but it ran)
    # after firing, not due until the interval passes
    assert s.due_now() == []
