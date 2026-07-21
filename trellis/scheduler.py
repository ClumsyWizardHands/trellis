"""scheduler.py — scheduling as VERIFIABLE STATE, on the ledger. (Codex High 11)

"we never verified whether the cron jobs were actually scheduled. They were not."
— Sarah, 2026-07-01

`clock.Schedule` had the cadence arithmetic but kept registrations and firings in
an in-memory list — so a restart reported "never fired" and "is this actually
scheduled?" was unanswerable across processes. This makes both the registration and
every firing an APPENDED LEDGER EVENT, so:

  * a fresh process reconstructs what is scheduled and when it last fired;
  * `verify(name)` answers "did it run on cadence?" from the record, not a hope;
  * `run_due(handlers)` is the tick — it fires the schedules that are due, records
    each firing, and is called by a runner (an in-process loop via `serve()`, or an
    external cron / systemd timer that runs `run_due` — the deployment's choice).

The reflection ritual and the improvement loop become schedules that actually run.
Stdlib only.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from .clock import ScheduleKind, TimeGround
from .ledger import Ledger

SPEC_KIND = "schedule_spec"
FIRING_KIND = "schedule_firing"


class LedgerScheduler:
    """Schedules and their firings live on the ledger — reconstructable, verifiable,
    greppable. No in-memory truth that a restart can lose."""

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground

    # ----- registration (an appended fact, latest-wins per name) -------------

    def register(self, name: str, interval: timedelta, author: str,
                 kind: ScheduleKind = ScheduleKind.CRON,
                 active_hours: Optional[tuple] = None, purpose: str = "") -> None:
        if not name or interval.total_seconds() <= 0:
            raise ValueError("a schedule needs a name and a positive interval")
        self.ledger.append(
            kind=SPEC_KIND, author=author,
            body={"name": name, "interval_seconds": interval.total_seconds(),
                  "schedule_kind": kind.value,
                  "active_hours": list(active_hours) if active_hours else None,
                  "purpose": purpose},
            tags=("schedule", name))

    def registered(self) -> dict:
        """name → the latest spec, from the active schedule_spec entries."""
        out: dict = {}
        for e in self.ledger.entries():
            if e.kind == SPEC_KIND and e.body.get("name"):
                out[e.body["name"]] = e.body     # later entries overwrite (latest wins)
        return out

    # ----- firing history (on the ledger, survives restart) ------------------

    def record_firing(self, name: str, author: str, outcome: str = "ok",
                      detail: str = "") -> None:
        self.ledger.append(
            kind=FIRING_KIND, author=author,
            body={"name": name, "outcome": outcome, "detail": detail},
            tags=("schedule", name, "fired"))

    def last_fired(self, name: str) -> Optional[datetime]:
        times = [e.stamp.event_time for e in self.ledger.entries()
                 if e.kind == FIRING_KIND and e.body.get("name") == name]
        return max(times) if times else None

    # ----- is it due? (cadence + active-hours, from the ledger) --------------

    def is_due(self, name: str, now: Optional[datetime] = None) -> bool:
        spec = self.registered().get(name)
        if spec is None:
            return False
        now = now or self.ground.now()
        ah = spec.get("active_hours")
        if ah is not None:
            lo, hi = ah
            h = now.hour
            # a window may WRAP midnight, e.g. (22, 6); the old `lo<=h<hi` made
            # every wrapping window empty (the adversary's #7).
            in_window = (lo <= h < hi) if lo <= hi else (h >= lo or h < hi)
            if not in_window:
                return False
        last = self.last_fired(name)
        if last is None:
            return True
        return (now - last) >= timedelta(seconds=spec["interval_seconds"])

    def due_now(self, now: Optional[datetime] = None) -> list:
        return [name for name in self.registered() if self.is_due(name, now)]

    def verify(self, name: str, tolerance: float = 2.0,
               now: Optional[datetime] = None) -> dict:
        """Did this schedule actually run on cadence? Answerable from the LEDGER,
        so it survives a restart — 'the cron jobs were not actually scheduled'
        becomes a query. Returns evidence, never a bare boolean."""
        spec = self.registered().get(name)
        if spec is None:
            return {"ok": False, "reason": "not registered"}
        now = now or self.ground.now()
        last = self.last_fired(name)
        if last is None:
            return {"ok": False, "reason": "registered but never fired",
                    "expected_every_s": spec["interval_seconds"]}
        gap = (now - last).total_seconds()
        ok = gap <= spec["interval_seconds"] * tolerance
        return {"ok": ok, "last_fired": last.isoformat(), "gap_s": round(gap, 1),
                "expected_every_s": spec["interval_seconds"],
                "reason": "on cadence" if ok else f"silent for {round(gap)}s (> {tolerance}x)"}

    # ----- the tick (a runner / cron calls this) -----------------------------

    def run_due(self, handlers: "dict[str, Callable[[], object]]", author: str,
                now: Optional[datetime] = None) -> list:
        """Fire every due schedule via its handler, recording each firing on the
        ledger (a firing is recorded even if the handler raises — a schedule that
        errored still RAN, and the outcome is on the record, never silent). Returns
        [(name, outcome)]. Call this from `serve()` or an external cron."""
        results = []
        for name in self.due_now(now):
            handler = handlers.get(name)
            if handler is None:
                continue
            try:
                handler()
                self.record_firing(name, author, outcome="ok")
                results.append((name, "ok"))
            except BaseException as ex:  # a schedule that errored still ran — record it
                self.record_firing(name, author, outcome="failed", detail=repr(ex)[:300])
                results.append((name, "failed"))
        return results

    def serve(self, handlers: "dict[str, Callable[[], object]]", author: str,
              tick: timedelta = timedelta(minutes=1), stop: Optional[Callable[[], bool]] = None
              ) -> None:  # pragma: no cover - a blocking loop
        """A simple in-process runner: every `tick`, fire what's due. For a personal
        agent this is enough; a production deployment points an external cron /
        systemd timer at `run_due` instead (same ledger, same verifiability)."""
        import time
        while not (stop and stop()):
            self.run_due(handlers, author)
            time.sleep(tick.total_seconds())
