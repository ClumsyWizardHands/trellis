"""The local always-on runner (D37): a tick the OS/login can drive, an in-process
loop while the machine is up. Crash-safe — state is the ledger, reconstructed each
tick. Tests drive tick() directly; no real sleeping, no real model.

Pins:
  * a tick registers the standing schedules if unregistered, runs the due ones, and
    records each firing;
  * an orphaned loop_run_start (a prior hard-kill) is detected and recorded on the
    next startup — no-silent-failure covers process death;
  * the daily budget is LEDGER-DERIVED: it blocks a tick that would exceed the cap
    and resets in a new window (survives a restart; never a permanent lockout);
  * health surfaces orphan-starts + scheduler.verify (silence is visible).
"""

import argparse
from datetime import timedelta

from trellis import cli
from trellis.loops import LoopRegistry, Outcome
from trellis.runner import DayBudget, Runner


def test_tick_registers_standing_schedules_and_records_firings(ledger, ground):
    r = Runner(ledger, ground)
    assert r.scheduler.registered() == {}          # nothing registered yet
    ran = []
    handlers = {name: (lambda n=name: ran.append(n))
                for name, _i, _p in Runner.DEFAULT_SCHEDULES}
    report = r.tick(handlers)
    # the standing schedules were registered by the tick, then fired (never fired → due)
    names = {n for n, _i, _p in Runner.DEFAULT_SCHEDULES}
    assert set(r.scheduler.registered()) == names
    assert {n for n, _o in report["fired"]} == names
    assert set(ran) == names
    for n in names:
        assert r.scheduler.last_fired(n) is not None   # firing is on the record


def test_tick_does_not_reregister_or_refire_before_cadence(ledger, ground, clock):
    r = Runner(ledger, ground)
    handlers = {name: (lambda: None) for name, _i, _p in Runner.DEFAULT_SCHEDULES}
    r.tick(handlers)
    specs_after_1 = len([e for e in ledger.entries() if e.kind == "schedule_spec"])
    # a second, immediate tick re-registers nothing and fires nothing (cadence not elapsed)
    report2 = r.tick(handlers)
    specs_after_2 = len([e for e in ledger.entries() if e.kind == "schedule_spec"])
    assert specs_after_2 == specs_after_1            # idempotent registration
    assert report2["fired"] == []


def test_orphaned_loop_run_start_is_recorded_on_next_startup(ledger, ground):
    # a prior process wrote a loop_run_start and was hard-killed before its finally
    # block could write the loop_run_end
    ledger.append(kind="loop_run_start", author="witness",
                  body={"run_id": "deadbeef1234", "loop": "witness.cycle",
                        "surface_key": "witness:witness/channel/c/"},
                  tags=("loop", "witness.cycle"))
    reg = LoopRegistry(ledger, ground)
    assert [b["run_id"] for b in reg.orphan_starts()] == ["deadbeef1234"]
    # a FRESH runner's first tick sweeps the orphan and records an end for it
    r = Runner(ledger, ground)
    report = r.tick(handlers={})
    assert "deadbeef1234" in report["swept"]
    ends = [e for e in ledger.entries()
            if e.kind == "loop_run_end" and e.body.get("run_id") == "deadbeef1234"]
    assert len(ends) == 1
    assert ends[0].body["outcome"] == Outcome.PROTOCOL_VIOLATION.value
    assert ends[0].body.get("swept") is True
    assert reg.orphan_starts() == []                 # no longer orphaned
    # the sweep is once-per-process: a second tick does not re-record it
    r.tick(handlers={})
    ends2 = [e for e in ledger.entries()
             if e.kind == "loop_run_end" and e.body.get("run_id") == "deadbeef1234"]
    assert len(ends2) == 1


def test_daily_budget_blocks_a_tick_over_cap_and_resets_next_window(ledger, ground, clock):
    budget = DayBudget(ledger, cap=1.00, ground=ground)
    r = Runner(ledger, ground, budget=budget)
    fired = []
    handlers = {name: (lambda n=name: fired.append(n))
                for name, _i, _p in Runner.DEFAULT_SCHEDULES}
    # spend the day's cap (as ledger charge records — survives a restart)
    budget.charge(0.60, author="witness", reason="cycle")
    budget.charge(0.45, author="witness", reason="cycle")   # total 1.05 >= 1.00
    assert budget.spent() >= budget.cap
    report = r.tick(handlers)
    assert report["budget_blocked"] is True
    assert report["fired"] == [] and fired == []            # nothing ran
    # a NEW window: yesterday's charges fall out of today's spend → not locked out
    clock.advance(days=1)
    assert budget.spent() == 0.0
    report2 = r.tick(handlers)
    assert report2["budget_blocked"] is False
    assert fired                                            # work resumed


def test_budget_is_derived_from_the_ledger_and_survives_a_restart(tmp_path, ground):
    from trellis.ledger import Ledger
    path = tmp_path / "l.jsonl"
    b1 = DayBudget(Ledger(path, ground), cap=2.0, ground=ground)
    b1.charge(0.75, author="witness")
    # DROP the process — a fresh budget over the same ledger reconstructs the spend
    b2 = DayBudget(Ledger(path, ground), cap=2.0, ground=ground)
    assert b2.spent() == 0.75
    assert b2.remaining() == 1.25


def test_health_surfaces_orphans_and_a_missed_cadence(ledger, ground, clock):
    r = Runner(ledger, ground)
    r.scheduler.register("witness.reflect", timedelta(hours=24), "alex",
                         purpose="daily reflection")
    r.scheduler.record_firing("witness.reflect", "witness")
    # it fired once, then went silent well past its cadence
    clock.advance(days=3)
    h = r.health()
    v = h["schedules"]["witness.reflect"]
    assert v["ok"] is False and "silent" in v["reason"]
    # an unresolved orphan also shows in health (before any sweep)
    ledger.append(kind="loop_run_start", author="witness",
                  body={"run_id": "orphan99", "loop": "x"}, tags=("loop", "x"))
    h2 = r.health()
    assert any(b["run_id"] == "orphan99" for b in h2["orphan_starts"])


def test_cli_tick_runs_offline_and_registers_schedules(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    for k in ("TRELLIS_PROVIDER", "TRELLIS_DAILY_BUDGET", "TRELLIS_TICK_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TRELLIS_LEDGER", str(tmp_path / "state/ledger.jsonl"))
    rc = cli.cmd_tick(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    assert "schedule witness.cycle" in out          # standing schedules registered + surfaced
    from trellis.ledger import Ledger
    specs = [e for e in Ledger(tmp_path / "state/ledger.jsonl").entries()
             if e.kind == "schedule_spec"]
    assert {"witness.cycle", "witness.reflect", "witness.harvest"} <= {s.body["name"] for s in specs}
