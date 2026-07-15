# trellis

**An agent harness that is a trellis, not a soul.**

A trellis is infrastructure a living thing grows on. It is not the plant, it does
not pretend to be the plant, and it holds shape when the plant fails. This is a
harness for agents whose job is **contextual understanding and principled
opinion** — not task completion — built from eleven months of recorded agent
failures and triangulated against the strongest harnesses in the field as of
July 2026 (pi, OpenClaw, Hermes, the Claude Agent SDK, Letta).

It is the executable companion to *CF Discord Agent.md* — the failure-intelligence
dossier and baby EMP compiled 2026-07-15. That document says what the team cannot
forgive an agent for getting wrong. This repository is those unforgivables turned
into type errors.

```
pip install -e .            # zero runtime dependencies in the core
python3 -m pytest           # 59 tests — the acceptance suite
python3 stress/stress_test.py   # 10 adversarial scenarios, evidence-logged
python3 examples/run_witness.py # a full witness cycle, offline, no API key
```

---

## The five refusals

Everything else in this repo is detail. These five are structural — the code
raises, it doesn't remind:

| # | Refusal | Where | The burn it answers |
|---|---------|-------|---------------------|
| 1 | **No silent failure.** Every loop run ends in a typed outcome, written in a `finally`. A run that says nothing is recorded as `protocol_violation` — by the harness, about the run. | `loops.py` | "Claude failed silently and has been spinning for four hours." — Clare, 2026-06-11 |
| 2 | **No self-certification.** A completion claim carries evidence a checker can open; the verifier must be a different identity, ideally a cheaper model with fresh context. Maker == verifier raises. | `verify.py` | "A self audit is not an audit." — Brett, 2026-03-13 |
| 3 | **No soul.md.** Identity is an EMP grounded in observable behavior. The loader refuses soul/persona/character files by name; an embodiment linter catches "I can see / I feel / my eyes." | `emp.py` | "The original sin: the agent gaslighting itself and us that it is something it is not." — the June 2026 paradigm doc |
| 4 | **No naked `now()`.** All state is bitemporal (event-time + write-time). Retrieved items are age-annotated so stale data *looks* stale. Naive timestamps are refused. Newer supersedes older, out loud. | `clock.py`, `ledger.py` | "A conversation from April minted today reads June 10." — loop-provenance audit, 2026-06-10 |
| 5 | **No auto-fire.** Every outbound action stages for a named human. The staging agent cannot approve itself. There is no bypass flag. | `stage.py` | "Nothing is ever sent, posted, or applied automatically." — DAILY-EMPIRE-PROTOCOL, 2026-07-15 |

## What lives here

```
trellis/
├── clock.py       time: bitemporal stamps, staleness decay, heartbeat-vs-cron,
│                  schedules you can VERIFY ran ("were the cron jobs actually
│                  scheduled?" is a query now)
├── ledger.py      the spine: append-only JSONL, event-time + write-time, author
│                  required, supersession-not-deletion, drift-proof search,
│                  as_of() time travel
├── emp.py         identity: EMP loader (Ends/Means/Principles/Identity/Friction/
│                  Signals/Observable), soul refusal, embodiment linter
├── decisions.py   the atomic record: Y/N/T decisions with EMP lineage.
│                  T requires ≥3 named POVs + owner + revisit time.
│                  Unresolved Ts surface as HIDDEN NOS.
├── surfaces.py    threads as substrate: (agent, surface, thread, human) keys;
│                  DM→channel flow raises without a human-logged declassification
├── passes.py      agent-to-agent: typed Pass files with a required ask
│                  (the turd-drop is a type error), tracked lifecycle,
│                  comments-as-protocol, overdue detection
├── loops.py       working loops: bounded (max_turns is never None), typed
│                  outcomes, block-loop breaker → triage, quiet loops → dormant
├── verify.py      the checker's seat: RuleVerifier (deterministic floor) +
│                  ModelVerifier (the haiku-verifier pattern, refute-oriented);
│                  verdicts compound into a trust record per maker
├── stage.py       the outbox: stage → human approves → fire. Nothing else.
├── memory.py      memory beside the agent: synthesis-test write gate,
│                  flush-before-compact, session epitaphs ("the agent dies;
│                  the record survives")
├── prompt.py      the standing prompt: <1,200 tokens, clock injected, maps not
│                  content, staleness legend, status rail
├── agent.py       the Witness: sense → resolve → act → verify → remember.
│                  Emits opinions as Y/N/T. [] is a legitimate answer.
└── providers/     model seats: mock (deterministic), claude_sdk (first-class,
                   optional), openai_compat (local models — Gemma/Hermes/
                   Nemotron via Ollama/LM Studio/vLLM, stdlib-only)
```

Companion documents:

- **DECISIONS.md** — every architectural decision, triangulated ≥3×, dated,
  recency-checked, superseded-not-edited. Start here to argue with the design.
- **LINEAGE.md** — the archaeology: eleven months of agent builds on this
  machine, what each one taught, and which lesson landed where in this code.
- **ACCEPTANCE.md** — the ten unforgivables from the dossier mapped to the
  tests that enforce them.
- **STRESS-REPORT.md** — evidence from the adversarial suite (regenerate with
  `python3 stress/stress_test.py`; deterministic seed, reproducible numbers).

## What kind of agent this is for

Not a taskmaster. The shipped shape is the **Witness** (`agent.py`): it ingests
a surface — channels, transcripts, a corpus — holds an EMP-grounded *read* of
what is happening, and puts **opinions on the record as Y/N/T decisions with
lineage**: including *No*, and including *Triangulate* with a named missing
piece, an owner, and a revisit date. Its stopping condition is "my read is
current and my opinions are on the record" — never "the task list is empty."
An empty opinion set is a loud `nothing_new`, not manufactured usefulness.

Task execution can be attached to a trellis. It just isn't the identity.

## Model seats

The core never imports a vendor SDK. Three seats ship:

```python
from trellis.providers.mock import MockProvider            # tests, dry runs
from trellis.providers.claude_sdk import ClaudeSDKProvider  # pip install claude-agent-sdk
from trellis.providers.openai_compat import OpenAICompatProvider
# local models — Clare's stack:
gemma = OpenAICompatProvider("http://localhost:11434/v1", "gemma3:12b")
```

Adapters fail **loud** (`ProviderUnavailable`), never silent — a degraded
auxiliary model that keeps nodding is a recorded failure mode, not a fallback
strategy. For running trellis's refusals inside a full Claude Agent SDK agent
(hooks at PreToolUse / Stop / SessionEnd), see `docs/claude-sdk.md`.

## Sixty seconds of taste

```python
from trellis import *
from trellis.clock import TimeGround
from trellis.ledger import Ledger

ground = TimeGround()
ledger = Ledger("state/ledger.jsonl", ground)

# time that cannot lie
stamp = ground.stamp()                       # event-time AND write-time
ground.annotate("Brett prefers X", april_dt, volatility="position")
                                             # "[expired · 84d ago · 2026-04-22] …"

# a decision that cannot be a disguised maybe
Decision(subject="memory on-agent vs beside", verdict=Verdict.T, ...)
# → IncompleteTriangulationError: T requires >=3 POVs, an owner, a revisit time

# a pass that cannot be a turd-drop
Pass(sender="peter", receiver="atlas", ask="thoughts?", context=...)
# → TurdDropError: state what the receiver should DO, by when, what done looks like

# a loop that cannot fail silently
with LoopRun(spec, registry, actor="witness:a") as run:
    ...                                      # crash, wander off, whatever —
                                             # an outcome is written regardless

# work that cannot grade itself
RuleVerifier("witness:a").verify(claim_by_witness_a)
# → SelfCertificationError: a self-audit is not an audit
```

## What this is not

- Not a chat gateway. It composes with one (the Discord adapter you already
  run, or any surface that can produce `Event`s and consume staged actions).
- Not a skill marketplace, not auto-installed anything (see DECISIONS.md W1 —
  the 2026 supply-chain record is why).
- Not autonomous outbound. Standing "proposed no" until the team ratifies
  otherwise (W3).
- Not a memory database. Files, beside the agent. The agent dies; the record
  survives.

---

*Built 2026-07-15 in a Cowork session, from the corpus in `~/atlas`, the builds
on `~/Desktop`, and the July 2026 harness field. 59 tests, 10 adversarial
scenarios, zero runtime dependencies.*
