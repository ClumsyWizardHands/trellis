"""Real resource bounds (Codex High 10): max_turns counts harness ticks, not the
model work that costs money. A Budget bounds wall-clock, provider calls, and tokens,
and ends the run BUDGET_EXCEEDED when spent — nested model work is bounded, not just
the outer loop."""

from datetime import timedelta

import pytest

from trellis.loops import Budget, LoopRegistry, LoopRun, LoopSpec, Outcome


def _spec():
    return LoopSpec("x", "p", "k", max_turns=100, stop_condition="done")


def test_budget_exceeded_logic():
    # provider-call headroom (10) so this case exercises the WALL and TOKEN bounds;
    # the provider-call bound is now PROSPECTIVE (>=), tested on its own below.
    b = Budget(max_wall_seconds=10, max_provider_calls=10, max_tokens=100)
    assert b.exceeded(0) is None
    assert "wall-clock" in b.exceeded(11)
    b.charge(40, 40); assert b.exceeded(0) is None
    b.charge(30, 30); assert "tokens" in b.exceeded(0)          # 140 > 100
    # PROSPECTIVE provider-call bound (Codex #12): spending the last allowed call
    # marks the budget exhausted immediately (>=), not one call past it.
    b2 = Budget(max_provider_calls=1); b2.charge()
    assert "provider calls" in b2.exceeded(0)


def test_provider_call_budget_ends_the_run(ledger, ground):
    reg = LoopRegistry(ledger, ground)
    budget = Budget(max_provider_calls=2)
    with LoopRun(_spec(), reg, actor="w", budget=budget) as run:
        n = 0
        while run.tick():          # tick checks the budget each iteration
            run.charge(input_tokens=10, output_tokens=5)   # simulate a provider call
            n += 1
            if n > 50: break       # safety
    assert reg.recent_outcomes("x", 1)[0] == Outcome.BUDGET_EXCEEDED.value
    assert budget.spent_provider_calls >= 2


def test_token_budget_ends_the_run(ledger, ground):
    reg = LoopRegistry(ledger, ground)
    budget = Budget(max_tokens=100)
    with LoopRun(_spec(), reg, actor="w", budget=budget) as run:
        while run.tick():
            run.charge(input_tokens=60, output_tokens=0)
    assert reg.recent_outcomes("x", 1)[0] == Outcome.BUDGET_EXCEEDED.value


def test_wall_clock_budget_ends_the_run(ledger, ground, clock):
    reg = LoopRegistry(ledger, ground)
    budget = Budget(max_wall_seconds=60)
    with LoopRun(_spec(), reg, actor="w", budget=budget) as run:
        assert run.tick()          # t=0, fine
        clock.advance(seconds=120) # two minutes pass
        assert not run.tick()      # over the wall-clock budget
    assert reg.recent_outcomes("x", 1)[0] == Outcome.BUDGET_EXCEEDED.value


def test_no_budget_means_no_new_bound(ledger, ground):
    reg = LoopRegistry(ledger, ground)
    with LoopRun(_spec(), reg, actor="w") as run:     # budget=None
        run.tick(); run.charge(999999, 999999)         # charging a None budget is a no-op
        run.ok("done")
    assert reg.recent_outcomes("x", 1)[0] == Outcome.OK.value
