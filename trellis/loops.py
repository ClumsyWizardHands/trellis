"""loops.py — bounded, named, and always ending in an outcome. (DECISIONS.md D9, D4)

Failure record this answers:
  * "Claude failed silently and has been spinning for four hours." — Clare,
    2026-06-11
  * max_turns=None across the whole Atlas gateway — no iteration or cost cap
    anywhere (loop-provenance audit, 2026-06-10)
  * "scheduling cron jobs… only last for 3 days for some reason… it just like
    fails silently." — Clare, 2026-06-17
  * "$300 in two days on basic tasks" — OpenClaw field report, 2026 (a personal
    agent's budget is a principle, not a nicety)

The contract, borrowed from the strongest production pattern found (Hermes
kanban, July 2026) and hardened:

  * every run ends in a TYPED outcome — written in a finally block, so a run
    that dies without one is recorded as PROTOCOL_VIOLATION by the harness,
    not forgotten
  * blocked is typed (dependency / needs_input / capability / transient) —
    "blocked" without a kind is just silence with paperwork
  * block-loop breaker: two consecutive blocks → the loop goes to TRIAGE
    instead of thrashing
  * nothing-new is a legitimate, loud outcome: a loop must be able to report
    that there was nothing to report ("an all-green morning is itself
    suspicious" — DAILY-EMPIRE-PROTOCOL, 2026-07-15)
  * two consecutive nothing-new runs → DORMANT (stop burning money on quiet)
"""

from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Optional

from .clock import TimeGround
from .ledger import Ledger


class Outcome(str, Enum):
    OK = "ok"
    NOTHING_NEW = "nothing_new"
    FAILED = "failed"
    BLOCKED = "blocked"
    BUDGET_EXCEEDED = "budget_exceeded"
    PROTOCOL_VIOLATION = "protocol_violation"  # died without reporting — the harness says so


class BlockKind(str, Enum):
    DEPENDENCY = "dependency"
    NEEDS_INPUT = "needs_input"
    CAPABILITY = "capability"
    TRANSIENT = "transient"


class LoopState(str, Enum):
    ACTIVE = "active"
    TRIAGE = "triage"     # re-blocked twice: needs a human look, stop thrashing
    DORMANT = "dormant"   # nothing new twice: stop spending until re-woken


class LoopBudgetExceeded(Exception):
    pass


@dataclass
class LoopSpec:
    name: str
    purpose: str                       # one plain sentence; register-mixing resisted
    surface_key: str                   # ConversationKey.storage_key() it operates on
    max_turns: int = 12                # NEVER None. The audit found None everywhere.
    max_tool_calls: int = 40
    stop_condition: str = ""           # plain-language description of "done"
    cadence: Optional[timedelta] = None

    def __post_init__(self):
        if self.max_turns is None or self.max_turns <= 0:  # type: ignore[comparison-overlap]
            raise ValueError("max_turns must be a positive integer — unbounded "
                             "loops are how four silent hours happen")
        if not self.stop_condition.strip():
            raise ValueError("a loop needs a plain-language stop condition")


class LoopRun:
    """Context manager that makes silent failure structurally impossible.

    Usage:
        with LoopRun(spec, registry, actor="witness-a") as run:
            while run.tick():           # False once budget is spent
                ...work...
                if done: run.ok("read is current", evidence=[...])
        # on exit, SOME outcome exists — reported by you, or PROTOCOL_VIOLATION
        # written by the harness with the traceback attached.
    """

    def __init__(self, spec: LoopSpec, registry: "LoopRegistry", actor: str):
        self.spec = spec
        self.registry = registry
        self.actor = actor
        self.ground = registry.ground
        self.run_id = uuid.uuid4().hex[:12]
        self.turns = 0
        self.tool_calls = 0
        self._outcome: Optional[Outcome] = None
        self._detail: dict = {}

    # ----- budget ----------------------------------------------------------

    def tick(self) -> bool:
        if self._outcome is not None:
            return False
        if self.turns >= self.spec.max_turns:
            self._set(Outcome.BUDGET_EXCEEDED,
                      {"reason": f"max_turns {self.spec.max_turns} reached"})
            return False
        self.turns += 1
        return True

    def count_tool_call(self) -> None:
        self.tool_calls += 1
        if self.tool_calls > self.spec.max_tool_calls and self._outcome is None:
            self._set(Outcome.BUDGET_EXCEEDED,
                      {"reason": f"max_tool_calls {self.spec.max_tool_calls} exceeded"})
            raise LoopBudgetExceeded(self.spec.name)

    # ----- typed outcomes ---------------------------------------------------

    def ok(self, summary: str, evidence: Optional[list[str]] = None) -> None:
        """Note: ok() is a CLAIM, not a verdict. Completion claims get checked
        by a verifier that is not the maker — see verify.py."""
        self._set(Outcome.OK, {"summary": summary, "evidence": evidence or [],
                               "verified": False})

    def nothing_new(self, checked: list[str]) -> None:
        self._set(Outcome.NOTHING_NEW, {"checked": checked})

    def failed(self, reason: str) -> None:
        self._set(Outcome.FAILED, {"reason": reason})

    def blocked(self, kind: BlockKind, on: str) -> None:
        self._set(Outcome.BLOCKED, {"block_kind": kind.value, "on": on})

    def _set(self, outcome: Outcome, detail: dict) -> None:
        if self._outcome is not None:
            return  # first outcome wins; later ones don't rewrite it
        self._outcome = outcome
        self._detail = detail

    # ----- the guarantee ----------------------------------------------------

    def __enter__(self) -> "LoopRun":
        # single-use: re-entering a finished run used to emit duplicate
        # loop_run_end records with the same run_id (found by the adversary, #45).
        if getattr(self, "_used", False):
            raise RuntimeError(
                f"LoopRun {self.run_id} is single-use — a run is one bounded "
                "attempt; start a new LoopRun for another attempt")
        self._used = True
        self.registry.record_start(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # ended-once guard: calling __exit__ again (directly, or via a second
        # with-block) must NOT emit a duplicate loop_run_end (the #45 re-attack
        # found the guard was only on __enter__).
        if getattr(self, "_ended", False):
            return False
        self._ended = True
        if self._outcome is None:
            if exc is not None:
                self._set(Outcome.PROTOCOL_VIOLATION, {
                    "reason": "run raised without reporting an outcome",
                    "exception": repr(exc),
                    "traceback": "".join(traceback.format_exception(exc_type, exc, tb))[-2000:],
                })
            else:
                self._set(Outcome.PROTOCOL_VIOLATION, {
                    "reason": "run exited without reporting an outcome — a loop "
                              "that says nothing is a loop that failed silently",
                })
        self.registry.record_end(self, self._outcome, self._detail)
        return False  # never swallow the exception; loud beats tidy


class LoopRegistry:
    """Loops are registered state in the ledger — which means 'are the loops
    actually scheduled/running?' is a query, not a hope."""

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground

    def register(self, spec: LoopSpec, author: str) -> None:
        self.ledger.append(
            kind="loop_spec", author=author,
            body={"name": spec.name, "purpose": spec.purpose,
                  "surface_key": spec.surface_key, "max_turns": spec.max_turns,
                  "max_tool_calls": spec.max_tool_calls,
                  "stop_condition": spec.stop_condition,
                  "cadence_seconds": spec.cadence.total_seconds() if spec.cadence else None},
            tags=("loop", spec.name),
        )

    def record_start(self, run: LoopRun) -> None:
        self.ledger.append(
            kind="loop_run_start", author=run.actor,
            body={"run_id": run.run_id, "loop": run.spec.name,
                  "surface_key": run.spec.surface_key},
            tags=("loop", run.spec.name),
        )

    def record_end(self, run: LoopRun, outcome: Outcome, detail: dict) -> None:
        self.ledger.append(
            kind="loop_run_end", author=run.actor,
            body={"run_id": run.run_id, "loop": run.spec.name,
                  "outcome": outcome.value, "turns": run.turns,
                  "tool_calls": run.tool_calls, **detail},
            tags=("loop", run.spec.name, outcome.value),
        )

    # ----- health ----------------------------------------------------------

    def recent_outcomes(self, loop_name: str, n: int = 5) -> list[str]:
        ends = [e for e in self.ledger.entries()
                if e.kind == "loop_run_end" and e.body.get("loop") == loop_name]
        return [e.body["outcome"] for e in ends[-n:]]

    def state(self, loop_name: str) -> LoopState:
        recent2 = self.recent_outcomes(loop_name, n=2)
        if len(recent2) == 2 and all(o == Outcome.BLOCKED.value for o in recent2):
            return LoopState.TRIAGE        # two consecutive blocks
        # rolling breaker: a loop blocking a majority of a recent window is
        # thrashing even if it sneaks an ok() between blocks (#44). BUT only if
        # it is STILL blocked now — a loop that recovered (last outcome not a
        # block) is healthy and must not be triaged (the #44 re-attack: a
        # false triage of a recovered loop).
        window = self.recent_outcomes(loop_name, n=5)
        # recovery requires at least TWO trailing non-blocked runs. A loop that
        # blocked 4 of 5 with a single trailing (and unverified) ok() has not
        # recovered — it is thrashing (the #44 round-3 vector). One clean run
        # after a wall of blocks is not enough to clear TRIAGE.
        trailing_clean = 0
        for o in reversed(window):
            if o == Outcome.BLOCKED.value:
                break
            trailing_clean += 1
        blocked = sum(o == Outcome.BLOCKED.value for o in window)
        if blocked >= 3 and trailing_clean < 2:
            return LoopState.TRIAGE
        if len(recent2) == 2 and all(o == Outcome.NOTHING_NEW.value for o in recent2):
            return LoopState.DORMANT       # stop burning budget on quiet
        return LoopState.ACTIVE

    def health_report(self) -> list[dict]:
        """The morning-surface rail: every loop, its last outcome, its state.
        A loop with no runs is itself a finding — 'the infrastructure is empty
        in the week you analyzed missing infrastructure' (Clare, 2026-03-27)."""
        specs = self.ledger.current("loop_spec")
        report = []
        for s in specs:
            name = s.body["name"]
            recent = self.recent_outcomes(name, 1)
            report.append({
                "loop": name,
                "state": self.state(name).value,
                "last_outcome": recent[0] if recent else "NEVER RAN",
                "purpose": s.body.get("purpose", ""),
            })
        return report
