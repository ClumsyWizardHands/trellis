"""runner.py — the local always-on runner. (DECISIONS.md D37)

"trellis has a current system where it's not a server, but it's always on… as long
as my computer is on. If my computer turns off, then trellis turns off." — Alex,
2026-07-21.

Not a hosted daemon: a TICK the OS/login can drive (a launchd/login item that runs
`trellis tick`), plus an in-process loop (`trellis run`) that sleeps then ticks while
the machine is up. Everything is reconstructed from the ledger each tick, so a crash
loses nothing — the scheduler is ledger-backed (scheduler.py), the outbox is
ledger-backed (stage.py), and this runner adds two more crash-safe pieces:

  * ORPHAN SWEEP — a loop_run_start with no loop_run_end is a prior hard-kill; the
    finally block that writes the outcome never ran. At startup the runner sweeps
    those and records a PROTOCOL_VIOLATION end, so no-silent-failure covers process
    death, not just a graceful exit (loops.LoopRegistry.sweep_orphans).

  * WINDOWED LEDGER-DERIVED BUDGET — a daily spend cap summed from `charge` records
    on the ledger. Deriving it from the ledger avoids both failure modes: a
    fresh-per-tick counter has NO cap across ticks (the "$300 in two days"), and a
    shared in-memory counter never resets after a restart (permanent lockout). The
    cap is enforced PROSPECTIVELY — once the window's spend reaches it, the runner
    starts no new work until the window rolls over.

Stdlib only. The model is a seat behind a provider; this file wires none — handlers
are passed in (a MOCK in tests, the real Witness cycle in production).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .clock import TimeGround
from .ledger import Ledger
from .loops import LoopRegistry
from .scheduler import LedgerScheduler

CHARGE_KIND = "charge"
TICK_SKIPPED_KIND = "tick_skipped"


def default_cadence() -> timedelta:
    """The in-process loop's sleep-then-tick interval. Configurable so a machine
    can dial cost/latency (TRELLIS_TICK_SECONDS); default 15 minutes — cheap enough
    to leave on, frequent enough to feel present."""
    raw = os.environ.get("TRELLIS_TICK_SECONDS", "").strip()
    if raw:
        try:
            secs = float(raw)
            if secs > 0:
                return timedelta(seconds=secs)
        except ValueError:
            pass
    return timedelta(minutes=15)


class DayBudget:
    """A daily spend cap DERIVED FROM THE LEDGER (D37).

    Spend is the sum of `charge` records inside the current window (a calendar day
    by default), so it (a) survives a restart — the ledger is the truth, not a
    process-local counter — and (b) RESETS when the window rolls over, so a spent
    day never becomes a permanent lockout. The cap is enforced prospectively: once
    the window's spend reaches it, no new work should start.
    """

    def __init__(self, ledger: Ledger, cap: float, ground: Optional[TimeGround] = None,
                 unit: str = "usd"):
        self.ledger = ledger
        self.cap = float(cap)
        self.ground = ground or ledger.ground
        self.unit = unit

    def window_start(self, now: Optional[datetime] = None) -> datetime:
        now = now or self.ground.now()
        tz = now.tzinfo or timezone.utc
        return datetime(now.year, now.month, now.day, tzinfo=tz)

    def spent(self, now: Optional[datetime] = None) -> float:
        now = now or self.ground.now()
        start = self.window_start(now)
        total = 0.0
        for e in self.ledger.entries():
            if e.kind != CHARGE_KIND:
                continue
            if e.stamp.event_time < start:
                continue
            try:
                total += float(e.body.get("amount", 0) or 0)
            except (TypeError, ValueError):
                continue
        return total

    def remaining(self, now: Optional[datetime] = None) -> float:
        return self.cap - self.spent(now)

    def would_block(self, now: Optional[datetime] = None, cost: float = 0.0) -> bool:
        """PROSPECTIVE gate: True when the window's spend has reached the cap (or the
        next unit of work — `cost` — would cross it). Default cost 0 means 'is there
        any headroom left this window?' — the runner refuses to start new work once
        the day's cap is spent, rather than discovering it one expensive call later."""
        return self.spent(now) + max(0.0, cost) >= self.cap

    def charge(self, amount: float, author: str, reason: str = "",
               now: Optional[datetime] = None):
        """Append a charge to the ledger — the single, restart-durable record of
        spend. Handlers (the Witness cycle, the reflection ritual) call this after
        real model work; the sum is what the cap is enforced against."""
        return self.ledger.append(
            kind=CHARGE_KIND, author=author,
            body={"amount": float(amount), "unit": self.unit, "reason": reason},
            event_time=now, tags=("budget", "charge"))


def budget_from_env(ledger: Ledger, ground: Optional[TimeGround] = None
                    ) -> Optional[DayBudget]:
    """A DayBudget from TRELLIS_DAILY_BUDGET (in `unit`), or a conservative default
    so an unconfigured always-on process is never UNBOUNDED — the "$300 in two days"
    is what happens when a personal agent runs with no cap. Set the var to raise or
    lower it; there is deliberately no way to disable the cap from the runner."""
    raw = os.environ.get("TRELLIS_DAILY_BUDGET", "").strip()
    cap = 5.0
    if raw:
        try:
            cap = float(raw)
        except ValueError:
            pass
    unit = os.environ.get("TRELLIS_BUDGET_UNIT", "usd").strip() or "usd"
    return DayBudget(ledger, cap=cap, ground=ground, unit=unit)


class Runner:
    """Constructs the ledger-backed scheduler + loop registry, registers the standing
    schedules if unregistered, and runs one pass (`tick`) or an always-on loop
    (`run`). Holds no durable state of its own — every tick reconstructs from the
    ledger, so a fresh process is indistinguishable from a resumed one."""

    #: (name, cadence, purpose). The witness cycle is the always-on read; reflection
    #: and harvest are the daily rituals. Registered on first tick if absent.
    DEFAULT_SCHEDULES: tuple = (
        ("witness.cycle", timedelta(minutes=15), "the contextual witness read pass"),
        ("witness.reflect", timedelta(hours=24), "the daily reflection ritual"),
        ("witness.harvest", timedelta(hours=24), "the daily confusion/burn harvest"),
    )

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None,
                 budget: Optional[DayBudget] = None, author: str = "trellis-runner"):
        self.ledger = ledger
        self.ground = ground or ledger.ground
        self.scheduler = LedgerScheduler(ledger, self.ground)
        self.registry = LoopRegistry(ledger, self.ground)
        self.budget = budget
        self.author = author
        self._swept = False   # the orphan sweep is a startup act — once per process

    def ensure_schedules(self, specs: Optional[tuple] = None) -> None:
        specs = specs or self.DEFAULT_SCHEDULES
        registered = self.scheduler.registered()
        for name, interval, purpose in specs:
            if name not in registered:
                self.scheduler.register(name, interval, self.author, purpose=purpose)

    def sweep_orphans(self) -> list:
        return self.registry.sweep_orphans(self.author)

    def tick(self, handlers: Optional["dict[str, Callable[[], object]]"] = None,
             now: Optional[datetime] = None, specs: Optional[tuple] = None) -> dict:
        """One pass: sweep orphans (startup only), register standing schedules if
        absent, enforce the budget prospectively, then run the due schedules. Returns
        a report a runner/CLI/portal can print. Safe to call from an OS timer or the
        in-process loop; idempotent registration and cadence gating make repeated
        ticks cheap."""
        handlers = handlers or {}
        report: dict = {"swept": [], "budget_blocked": False, "fired": []}
        # STARTUP: a prior process's hard-kill is discovered here, on a fresh start.
        if not self._swept:
            report["swept"] = self.sweep_orphans()
            self._swept = True
        self.ensure_schedules(specs)
        # PROSPECTIVE budget gate: once the window's spend hits the cap, start no new
        # work (a witness cycle is a fresh session that costs money the moment it runs).
        if self.budget is not None and self.budget.would_block(now):
            report["budget_blocked"] = True
            self.ledger.append(
                kind=TICK_SKIPPED_KIND, author=self.author,
                body={"reason": "daily budget cap reached — no new work started",
                      "spent": round(self.budget.spent(now), 4), "cap": self.budget.cap,
                      "unit": self.budget.unit},
                event_time=now, tags=("runner", "budget"))
            return report
        report["fired"] = self.scheduler.run_due(handlers, self.author, now=now)
        return report

    def health(self, now: Optional[datetime] = None) -> dict:
        """What the portal/CLI surfaces so SILENCE is visible: any orphaned starts,
        and per-schedule verify (did it run on its cadence, or has it gone quiet?).
        A schedule registered-but-never-fired and a schedule silent past its cadence
        both read as `ok: False` with a reason — 'is it actually scheduled?' is a
        query, never a hope (Sarah, 2026-07-01)."""
        h: dict = {
            "orphan_starts": self.registry.orphan_starts(),
            "schedules": {name: self.scheduler.verify(name, now=now)
                          for name in self.scheduler.registered()},
            "loops": self.registry.health_report(),
        }
        if self.budget is not None:
            h["budget"] = {"spent": round(self.budget.spent(now), 4),
                           "cap": self.budget.cap, "unit": self.budget.unit,
                           "remaining": round(self.budget.remaining(now), 4)}
        return h

    def run(self, handlers: Optional["dict[str, Callable[[], object]]"] = None,
            cadence: Optional[timedelta] = None,
            stop: Optional[Callable[[], bool]] = None) -> None:  # pragma: no cover
        """The always-on loop: sleep then tick, while the machine is up. Meant to run
        under a launchd/login item — NOT a hosted daemon. Crash-safe by construction:
        each tick reconstructs state from the ledger, so a restart resumes cleanly."""
        import time
        cadence = cadence or default_cadence()
        while not (stop and stop()):
            self.tick(handlers)
            time.sleep(cadence.total_seconds())
