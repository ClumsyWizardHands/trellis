# Fable audit prompt — how the agent is *supposed to function*, end to end

> Paste everything below the line into Fable, run from the repo root. This is a deep
> architecture-and-behavior audit, not a bug hunt (Codex covers bugs). Fable should
> **orchestrate a large fleet of subagents** — one per lane, plus cross-cutting
> lifecycle tracers, adversarial verifiers, and a synthesizer. Go wide.

---

You are the lead auditor of `trellis`, an agent harness about to be wired to a live
Discord and a real model for the first time. Your mandate is to audit **how the agent
is supposed to function** — the intended behavior, end to end, subsystem by subsystem
and as a whole — and to report where that intended function is **coherent, incoherent,
underspecified, contradictory, or missing.** You have strong multi-agent orchestration
ability; use it. Spawn a large fleet: a subagent per lane below, cross-cutting agents
that trace end-to-end lifecycles across lanes, adversarial verifiers that try to break
each lane's conclusions, and a synthesizer. Bigger and more parallel is better —
saturate the problem.

## The thesis you are auditing against

trellis's core claim is unusual: **it is supposed to get MORE trustworthy the longer
it runs.** An append-only, bitemporal `ledger.jsonl` is the source of truth; the
"Witness" runs sense→resolve→act→verify→remember; trust is earned through provenance,
independent verification (maker≠verifier), and never acting without a human's yes.
Hold every subsystem to that thesis: *does its intended behavior actually make the
agent more trustworthy over time, or does it just look like it does?*

## Orient (have your fleet read this; divide it up)

- `README.md`, `DECISIONS.md` (D1–D30 — the reasoned choices), `ACCEPTANCE.md`
  (unforgivables→tests), `VERIFICATION.md`, `docs/VISUAL-TOUR.md`, everything in `docs/`.
- Module docstrings across `trellis/*.py` and `web/*.py` — they state intended behavior.
- A prior AI-written seam map: `docs/audits/WORKFLOW-MAP-2026-07-21.md`, and the
  standalone-install design docs. **These are prior-AI artifacts — verify them, do not
  trust them.** (The author of that map once invented a relationship between two
  systems that did not exist; assume nothing it asserts until you have re-derived it.)
- Run it to watch behavior, not just read it: `pip install -e '.[dev,web]'`,
  `python -m pytest`, `trellis demo`, `trellis web` (click through every page).

## Honesty discipline (non-negotiable)

Separate **verified** (you traced it in code/behavior — cite `file:line`) from
**inferred** (a plausible reading of intent). Never state an inferred link between two
components as if it were established. Where intended behavior is genuinely unspecified,
say "UNSPECIFIED — design decision needed," don't invent it. Distinguish three failure
kinds throughout: **design-gap** (the intended behavior itself is unclear/incoherent),
**build-gap** (intent is clear, code doesn't do it yet), **bug** (defer to the Codex
audit; note and move on).

## The current state you're auditing (verify this too)

Much of trellis is built and tested but **wired to nothing live** — no daemon runs the
cycle, only a mock model is instantiated, the model-verifier ("haiku") seat and the
reflection ritual exist but aren't in the live loop, and the send/executor path is
deliberately unbuilt. Install/config groundwork (`config.py`, `providers/factory.py`,
`cli.py`, isolation) just landed. So a large part of your audit is: **is the intended
function coherent enough that turning it on will behave as designed?**

---

## Audit lanes (one subagent team per lane — go deep on each)

For each lane, produce: the **intended-function spec** (how it's supposed to work, in
your words, cited), a **coherence verdict**, the **gaps** (design/build), and the
**go-live risks**. The specific questions are starting points — exceed them.

**L1 — The message lifecycle (Discord → ledger → portal).** Trace one human message in
a Discord thread all the way through: sensed → keyed by surface (`surfaces.py`
`ConversationKey`: DM/CHANNEL/THREAD/FILE) → ingested with attribution + event-time
(`ingest.py`) → filtered by the isolation allowlist (`isolation.py`) → observed into a
decision candidate → an observation+opinion node pair (`observe.py`) → verified →
remembered → surfaced on the portal. Where is each hop specified vs assumed? What
happens to messages that aren't decisions?

**L2 — Discord behavior & threading (Alex's explicit question).** *How is the agent
supposed to live in a Discord server?* Does it read per-channel, per-thread, per-DM?
Does it use **threads** — reply inside a thread, open new threads, keep a thread per
topic/decision? How does `ThreadRef(id, parent_channel, parent_message)` and the
privacy rank (DM>FILE>THREAD>CHANNEL, `can_flow`) shape intended behavior — e.g. can a
thread summary leak to a channel? Is the intended Discord UX actually designed, or only
the ingestion plumbing? What's the intended act-in-Discord behavior once the (gated)
send path exists?

**L3 — Verification & the "haiku agents" (Alex's explicit question).** The trust
thesis lives here. How is the agent supposed to use independent verifiers? Trace
`verify.py` (`RuleVerifier` = deterministic floor, actually live; `ModelVerifier` = the
cheap-model/Haiku seat) and `panel.py` (`VerifierPanel`, refute-by-default quorum,
`panel_as_subagent_specs`). *When* is a Haiku verifier supposed to be spawned, *how
many*, with *what independence*, and how does its verdict gate acting and remembering?
Is maker≠verifier actually enforceable when the verifier is another instance of the
same model family? Is the intended verifier-orchestration coherent — and is it wired,
or a seam? This is the heart of the audit; give it the most agents.

**L4 — Context engineering (Alex's explicit question).** How is the agent supposed to
build its working context each cycle? Trace the context compiler (`context.py`, D24 —
records a `context_manifest`), "reload-the-read" before forming an opinion
(`memory.py` `_update_read` → `read/current-read.md`), prompt fencing of untrusted
content (`prompt.py` `fence_untrusted` + standing rules), and the budget (`loops.py`).
Does the intended context discipline actually prevent the failure modes it claims
(goldfish context, prompt injection, stale reads, unbounded growth)? What decides what
gets loaded, compressed, or carried between cycles?

**L5 — Memory & pathways (Alex's explicit question).** How is memory *saved* and how
are "different pathways" saved and navigated? Reconcile the several stores: the ledger
(bitemporal truth, `ledger.py`), the Workspace "memory beside the agent" (`memory.py`,
with containment), the Obsidian vault reconciliation (`vault.py` — human edits folded
back as attributed writes, drift detection), navigation/anti-fork on question-key
(`navigate.py`), decisions as two linked nodes with provenance FLOOR+OR, and the
epitaph (agent dies, record survives). Is the intended memory model coherent across all
stores? Where could memory be lost, duplicated, mis-attributed, or cross a privacy
boundary? How does a "pathway" (a chain of linked decisions/opinions) actually persist
and get re-walked?

**L6 — Portal-to-portal (Alex's explicit question).** How is a human supposed to move
through the portal to comprehend and steer the agent? Walk every page (`web/app.py`,
`web/views.py`: overview, map, decisions, assumptions, ingestion, reflection,
improvement, loops, verification, agents, activity). Does each page's intended purpose
cohere into a single comprehension workflow? Does the portal faithfully reflect the
agent's real ledger state, or can they diverge? Is the human-in-the-loop approval flow
(stage → authenticated approve/deny) complete and legible?

**L7 — Self, reflection & self-improvement.** How is the agent supposed to reflect
(`reflect.py` `ReflectionRitual`, the daily abstract self-image D29), harvest its own
confusion into skills (`selfimprove.py` `ConfusionHarvest`, `ImprovementEngine`), and
change itself *without changing itself alone* (proposals a human ratifies + an
independent verdict)? Is the intended self-improvement loop coherent and safe, or can
it drift/self-approve? Is it wired into the live cycle or a seam?

**L8 — The unattended run (the biggest vision-vs-running gap).** How is the agent
*supposed* to run continuously? Trace the scheduler (`scheduler.py` `LedgerScheduler`,
`serve()`), intended cadence, budget/loop discipline (`loops.py`), and crash recovery
(durable outbox reconcile, ledger read-cache). There is currently **no daemon** — so
specify: what should the run loop look like, what ticks it, what's the intended
failure/restart behavior, and what must exist before "turn it on" is safe?

**L9 — The model topology.** How are the reasoning model and the verifier model
*supposed* to be arranged (`providers/`, `factory.py`)? Is the intended topology (a
capable model to resolve, a cheap independent Haiku to verify, optionally a local model
for privacy) coherent with maker≠verifier and with cost/latency? What's assumed vs
configured?

**L10 — Cross-cutting invariants under live conditions.** Do the five refusals, the
bitemporal/append-only guarantees, the isolation boundary (D30), and the privacy-flow
rules actually hold end-to-end when real, messy, adversarial input flows through — or
only in the unit tests? Design an adversarial scenario per invariant and reason it
through.

## Cross-lane lifecycle traces (assign dedicated agents)

Beyond per-lane audits, trace these **end-to-end lifecycles across lanes** and report
where they break down at the seams between subsystems:
1. **A decision's life:** raw message → candidate → observation+opinion → verification
   → memory → portal → (later) a human revisits/supersedes it. Does provenance and
   staleness survive every hop?
2. **A verification's life:** work produced → verifier(s) spawned → verdict →
   gating of act + remember → recorded so trust can be computed later.
3. **A day's life:** cycles run → reflection ritual → self-image update → confusion
   harvested → an improvement proposed → human ratifies → the agent is different
   tomorrow. Is "more trustworthy over time" actually produced?
4. **A crash's life:** mid-fire / mid-cycle crash → restart → reconcile → no double
   send, no lost yes, no corrupted ledger, no lost memory.

## Method

Fan out: a team per lane (L1–L10) in parallel, plus the four lifecycle-tracer agents,
running against both the code and the live `trellis demo`/portal. Then an adversarial
wave: for each lane's conclusions, a skeptic agent that tries to refute them (default
to "unproven" if it can't be confirmed). Then synthesize. Prefer many small, focused
agents over a few big ones. Where lanes disagree about intended behavior, that
disagreement IS a finding (the intent is underspecified).

## Output

1. **The intended-function map** — how the agent is supposed to work, subsystem by
   subsystem and as one whole, in clear prose + a diagram. This is the primary
   deliverable Alex wants: a coherent picture of the intended agent.
2. **Gap analysis** — every design-gap and build-gap, tagged, with the specific
   decision or build each implies. Rank by how much it blocks "turn it on and trust it."
3. **Go-live risk register** — ranked risks of wiring this to a real Discord now, each
   with the scenario, the affected lane(s), and a mitigation.
4. **Prioritized recommendations** — the smallest set of decisions + builds that make
   the intended function real and safe to test live, in order.

Keep verified separate from inferred throughout. Flag any place the intended behavior
is genuinely a design decision only Alex can make — don't resolve it for him.
