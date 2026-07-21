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
class Budget:
    """A real resource bound on actual model work (Codex High 10): `max_turns`
    counts harness ticks, not provider turns, tokens, wall-clock, or dollars — a
    Witness can call an adapter twice and each invocation burn many nested SDK
    turns. A Budget bounds what actually costs money: wall-clock, provider calls,
    and tokens (estimated when the provider doesn't report usage). Shared across a
    run; a bound is a principle for a personal agent ("$300 in two days" — OpenClaw),
    not a nicety."""
    max_wall_seconds: Optional[float] = None
    max_provider_calls: Optional[int] = None
    max_tokens: Optional[int] = None            # input + output, estimated if unreported
    spent_provider_calls: int = 0
    spent_tokens: int = 0

    def charge(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.spent_provider_calls += 1
        self.spent_tokens += max(0, input_tokens) + max(0, output_tokens)

    def exceeded(self, elapsed_seconds: float = 0.0) -> Optional[str]:
        if self.max_wall_seconds is not None and elapsed_seconds > self.max_wall_seconds:
            return f"wall-clock {elapsed_seconds:.0f}s > {self.max_wall_seconds:.0f}s"
        # PROSPECTIVE bound (Codex #12): a run is exhausted the moment it has spent
        # its allotment, not one call past it. `>=` here means max_provider_calls=1
        # permits exactly one call — with `>` a second call slipped through when
        # spent == max. The limit is a ceiling on calls made, not on the overage.
        if self.max_provider_calls is not None and self.spent_provider_calls >= self.max_provider_calls:
            return f"provider calls {self.spent_provider_calls} >= {self.max_provider_calls}"
        if self.max_tokens is not None and self.spent_tokens > self.max_tokens:
            return f"tokens {self.spent_tokens} > {self.max_tokens}"
        return None


class OutcomePersistenceError(Exception):
    """The loop finished but its outcome could not be written to the ledger. We
    refuse to report success on an unrecorded run — silence is the cardinal sin,
    even (especially) when the store itself is down (Codex High 5)."""


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

    def __init__(self, spec: LoopSpec, registry: "LoopRegistry", actor: str,
                 budget: Optional[Budget] = None):
        self.spec = spec
        self.registry = registry
        self.actor = actor
        self.ground = registry.ground
        self.budget = budget                 # optional real resource bound (High 10)
        self._started_at = self.ground.now()
        self.run_id = uuid.uuid4().hex[:12]
        self.turns = 0
        self.tool_calls = 0
        self._outcome: Optional[Outcome] = None
        self._detail: dict = {}

    # ----- budget ----------------------------------------------------------

    def _elapsed(self) -> float:
        return (self.ground.now() - self._started_at).total_seconds()

    def tick(self) -> bool:
        if self._outcome is not None:
            return False
        if self.turns >= self.spec.max_turns:
            self._set(Outcome.BUDGET_EXCEEDED,
                      {"reason": f"max_turns {self.spec.max_turns} reached"})
            return False
        # a REAL resource bound, not just a tick count (High 10): wall-clock,
        # provider calls, and tokens actually spent.
        if self.budget is not None:
            over = self.budget.exceeded(self._elapsed())
            if over:
                self._set(Outcome.BUDGET_EXCEEDED, {"reason": f"budget: {over}"})
                return False
        self.turns += 1
        return True

    def charge(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """Record a provider call's cost against the run's Budget (the Witness calls
        this after each model turn). Charging accrues the cost; it does NOT itself
        end the run. The budget is enforced PROSPECTIVELY by tick(): once the
        allotment is spent, the NEXT tick() refuses an ADDITIONAL provider call and
        ends the run BUDGET_EXCEEDED. Nested model work stays bounded — the cap
        blocks the next call, it does not reach back and invalidate the call that
        just succeeded.

        Codex#12 residual: charge() USED to mark BUDGET_EXCEEDED the instant it
        spent the last allowed call. That retroactively relabeled a cycle whose
        VALID opinion had already been recorded in budget — suppressing run.ok() and
        skipping the cost-free RuleVerifier, so the recorded decision was left
        UNVERIFIED. "We just spent our last allowed provider call" must not suppress
        the free verification of work already completed; BUDGET_EXCEEDED is for a
        call that is actually BLOCKED with no result (tick() returning False), never
        for the last allowed call that succeeded."""
        if self.budget is not None:
            self.budget.charge(input_tokens, output_tokens)

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
                # repr(exc) and format_exception can THEMSELVES raise (an
                # exception whose __repr__ throws — round 4 #42). Capturing the
                # detail must never be what stops the outcome from being written.
                try:
                    exc_repr = repr(exc)
                except BaseException:
                    exc_repr = f"<unreprable {exc_type.__name__ if exc_type else '?'}>"
                try:
                    tb_text = "".join(traceback.format_exception(exc_type, exc, tb))[-2000:]
                except BaseException:
                    tb_text = "<traceback unavailable>"
                self._set(Outcome.PROTOCOL_VIOLATION, {
                    "reason": "run raised without reporting an outcome",
                    "exception": exc_repr, "traceback": tb_text,
                })
            else:
                self._set(Outcome.PROTOCOL_VIOLATION, {
                    "reason": "run exited without reporting an outcome — a loop "
                              "that says nothing is a loop that failed silently",
                })
        # last resort: even record_end must not be able to swallow the write.
        persisted = True
        try:
            self.registry.record_end(self, self._outcome, self._detail)
        except BaseException:
            try:
                self.registry.record_end(self, Outcome.PROTOCOL_VIOLATION,
                                         {"reason": "record_end degraded"})
            except BaseException:
                # BOTH writes failed — the audit record could not be persisted.
                # Codex High 5: the old code `pass`ed here and returned normally,
                # so a loop that finished would report SUCCESS with no durable
                # outcome — a silent unrecorded completion, the exact cardinal sin.
                # Never return success when the record could not be written: emit
                # to an independent emergency sink, then FAIL LOUD.
                persisted = False
                self._emergency_sink()
        # If we could not persist AND the body did not already raise, raise a
        # dedicated fatal error so the caller becomes unhealthy instead of
        # believing it succeeded. If the body DID raise, let that propagate
        # (return False) — we've already emitted the outcome to the sink.
        if not persisted and exc is None:
            raise OutcomePersistenceError(
                f"loop {self.spec.name} run {self.run_id} finished as "
                f"{(self._outcome.value if self._outcome else '?')} but its outcome "
                "could not be written to the ledger — refusing to report success on "
                "an unrecorded run (see the .emergency sink)")
        return False  # never swallow the exception; loud beats tidy

    def _emergency_sink(self) -> None:
        """When the ledger is unwritable, do not lose the outcome silently: append
        it to a sidecar `<ledger>.emergency` file and shout on stderr. Best-effort
        and defensive — even this must never raise and mask the real failure."""
        import json
        import sys
        rec = {"run_id": self.run_id, "loop": self.spec.name,
               "outcome": self._outcome.value if self._outcome else "unknown",
               "detail": {k: str(v)[:500] for k, v in (self._detail or {}).items()},
               "note": "LEDGER UNWRITABLE — outcome persisted to emergency sink"}
        line = json.dumps(rec, default=str)
        try:
            print("TRELLIS OUTCOME PERSISTENCE FAILURE:", line, file=sys.stderr, flush=True)
        except BaseException:
            pass
        try:
            path = getattr(self.registry.ledger, "path", None)
            if path is not None:
                with open(str(path) + ".emergency", "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except BaseException:
            pass  # we tried every independent way to be loud; never mask the original


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

    def orphan_starts(self) -> list[dict]:
        """loop_run_start entries with no matching loop_run_end — a process that
        died mid-run (a hard kill / power loss), so the finally block that writes
        the outcome never ran. Silent death made visible: these are exactly the
        runs the no-silent-failure contract cannot see until they are swept."""
        ended = {e.body.get("run_id") for e in self.ledger.entries()
                 if e.kind == "loop_run_end"}
        return [e.body for e in self.ledger.entries()
                if e.kind == "loop_run_start" and e.body.get("run_id") not in ended]

    def sweep_orphans(self, author: str) -> list[str]:
        """Record a PROTOCOL_VIOLATION end for every orphaned start, so a hard kill
        is covered by the same 'a run always ends in a typed outcome' guarantee the
        finally block gives a live process. Idempotent: a swept orphan now has an
        end and is skipped next time. Returns the run_ids swept. Called by the runner
        at STARTUP (a fresh process is where a prior process's death is discovered)."""
        swept = []
        for body in self.orphan_starts():
            rid = body.get("run_id")
            self.ledger.append(
                kind="loop_run_end", author=author,
                body={"run_id": rid, "loop": body.get("loop"),
                      "surface_key": body.get("surface_key"),
                      "outcome": Outcome.PROTOCOL_VIOLATION.value,
                      "reason": "orphaned loop_run_start — the process died without "
                                "recording an outcome (hard kill); swept at startup",
                      "swept": True},
                tags=("loop", body.get("loop") or "?", Outcome.PROTOCOL_VIOLATION.value))
            swept.append(rid)
        return swept

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
        # same-dependency stall: >=3 blocks in the window on the SAME `on` means
        # the dependency never cleared, even if the loop did unrelated side-work
        # in between (round 4 #44). Side-work oks are not resolution of the block.
        ends = [e for e in self.ledger.entries()
                if e.kind == "loop_run_end" and e.body.get("loop") == loop_name]
        recent_ends = ends[-5:]
        ons = [e.body.get("on") for e in recent_ends
               if e.body.get("outcome") == Outcome.BLOCKED.value and e.body.get("on")]
        if ons:
            top = max(ons.count(o) for o in set(ons))
            if top >= 3:
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
