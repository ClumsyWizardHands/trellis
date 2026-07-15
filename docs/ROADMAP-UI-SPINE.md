# Roadmap — the UI spine (a later-version vision, NOT built in v0.1)

> Status: **vision doc, deliberately not implemented.** v0.1 (trellis) is the
> backend spine — the ledger, the refusals, the loops, the verification. This
> document captures where the *interface* goes, so the backend built today keeps
> the door open for it. Grounded in the July-2026 agent-UI research
> (`docs/` research notes) and the team's own words (Discord + DAPs, harvested
> 2026-07-15). Nothing here is a v0.1 commitment.

---

## The one principle: legible, not just transparent

Alex's insight, verbatim in spirit: *what works about existing agent UIs is you
can see inside the agent and verify things; what doesn't work is that people
like us don't know what it means.* This is the whole design brief.

The market has solved **transparency** for engineers. Every observability tool
(LangSmith, Langfuse, Arize, AgentOps) renders an agent run as *traces and
spans* — the APM debugging paradigm borrowed wholesale. It is genuinely a
verification substrate: you can open it and check. But it is **request-centric,
not story-centric**, it surfaces *implementation* not *intent*, and it forces a
lay viewer to reconstruct meaning bottom-up from spans. As one 2026 survey put
it, these tools are "oriented toward technical practitioners familiar with trace
terminology." Honeycomb's own critique: "an agent conversation isn't a single
request and response. It's a story, and your tools only show you fragments."

trellis's UI is not another trace viewer. It is a **comprehension surface** for
a person — with the trace/ledger drill-down underneath, for verification, never
as the front door. Two tiers:

1. **Verify tier** (exists in v0.1, as data): the append-only ledger — every
   decision, pass, loop run, verdict, staged action, bitemporally stamped and
   attributed. This is the "see inside and check" layer. It's already there.
2. **Comprehend tier** (the UI to build): the story of what the agent did, why,
   what it considered, and *how it is changing over time* — in the operator's
   goal-language, not spans.

The team already named this need. Sarah's recurring question — *"how do you
know? how is it visible to you?"* — and her "Marauder's Map / verifier agent"
idea are exactly a request for the comprehend tier. Clare's game board — *"the
game board tells the story; if it's blank, the story didn't happen"* — is the
same instinct: a surface where the work is legible or it didn't count. Brett's
mobile endgame — *"do I like what is being shown to me on my phone is an
expression of 00-grade"* — sets the bar: the surface itself must be 00-grade.

---

## trellis's angle: plain-language backend loops

The differentiator is not the dashboard — dashboards exist. It's that the
**backend processes are set up in plain language**, and the UI is how you author
and watch them. Alex's example is the template:

> "I want to do end-of-day with learnings and do self-skilling on what you've
> learned today, and set that up."

That sentence should *become* a registered trellis loop. The UX (proven by
Zapier Agents and Hermes Agent's natural-language cron, per the research):

1. The operator writes the routine in prose.
2. A model **compiles** it into a `LoopSpec` + a `Schedule` (heartbeat or cron)
   + the skills/tools it may touch — all v0.1 primitives (`loops.py`,
   `clock.py`).
3. The UI shows a **dry-run preview** before it goes live (stage-don't-fire
   applies to *creating automations*, not just outbound actions).
4. The prose stays the source of truth; the compiled spec is a generated
   artifact the operator can edit.

This connects directly to the team's existing work: the `self-learning` skill
(harvest golden paths into reusable skills), the DAILY-EMPIRE-PROTOCOL's
end-of-day close with "future memory," and Brett's "compounding skills-
performance verification." The end-of-day-harvest loop is the canonical first
routine — and every routine it creates is verified (a harvested skill is a
completion claim; the panel checks it before it's trusted).

---

## The spine — components (later versions, in rough priority)

Adopt the *structure* the field converged on (the "Tailscale + kanban + logs"
mental model), and upgrade its *legibility*.

1. **Agent roster** (the Tailscale-like view). Every agent this operator runs,
   its EMP name, whether it's active/dormant/triage, last activity, trust
   ratio. At a glance: who's alive and how much you trust each.
2. **Work kanban.** The loops and passes as cards moving through states
   (v0.1 already has the state machines: `LoopState`, `PassStatus`). Claw
   Control / Hermes-kanban is the reference; the data model already exists.
3. **The inbox (stage-don't-fire, done right).** The single most important
   panel. Every `StagedAction` awaiting approval, rendered with **scoped
   clarity** (exactly which channel/target), the **full payload**, the risk
   class, and a **timeout default** — never a bare rubber-stamp button (the
   named anti-pattern). This is `stage.py` given a face. The LangChain "Agent
   Inbox" (Notify / Question / Review) is the model.
4. **Decision timeline.** The Y/N/T decisions with lineage — walk any decision
   back to its EMP node ("the breadcrumbs upstream"). Unresolved Ts past their
   revisit date glow red (hidden nos). This is `decisions.py` as a narrative,
   and it's the "Elise, one month in, can read why we decided what we decided"
   surface Brett described.
5. **The read / memory browser.** The agent's current read, its epitaphs, its
   workspace map — *titles first, drill to content* (the "memory is navigation"
   principle rendered).
6. **Loop health + verification panel.** Every loop's last outcome and state;
   every completion claim and its panel verdict (per-lens: correctness /
   freshness / attribution / reproduce). Sarah's requirement — verification
   "visible and accessible to each agent, both human and AI" — met literally.

Tech reality (from the research, for a small team): **FastAPI + HTMX + SSE over
the JSONL ledger.** The ledger *is* the event store — tail it, push new lines
over Server-Sent Events, swap HTML fragments; load into SQLite for query. No
message broker, no JS build required, all in Python next to the harness.
Optionally emit the AG-UI event protocol so off-the-shelf components drop in
later. This is buildable by one person.

---

## The self-image glyph — and how it stays honest

Alex's idea, and it's a good one: *at the center of the UI, a little
represented animal the agent creates for itself — an image it reflects on and
decides "this is what I look like," and as it learns, that look changes. You
watch the agent grow not just with memory and infrastructure, but with how it
sees itself.*

This lands **right on the boundary** of trellis's founding refusal — no soul, no
hallucinated body, no "I see / I feel." So the reconciliation matters, and it's
what makes the idea coherent rather than a betrayal of the whole thing:

**The animal is not the agent claiming a self. It is the EMP made visible — an
honest data-visualization that happens to wear a face.**

The no-soul rule forbids the agent *hallucinating* a body or *pretending* felt
experience. The glyph does neither. Here's the honest mechanism (the discipline
comes straight from the Tamagotchi-3.0 pattern the research found — separate the
*evaluation* from the *rendering* so the picture stays true):

- Every visual property is a **deterministic function of a real ledger value** —
  skills accrued, decisions made, verification pass-rate, memory growth, uptime,
  Ts resolved vs. left hanging. The animal is a *sparkline in the shape of a
  creature*.
- At end-of-day, the agent's role is bounded and honest: it emits a **structured
  self-description derived from observable behavior** — its EMP's *Observable*
  layer plus the day's real deltas ("today I recorded 6 decisions, 2 verified,
  1 T still open; I learned one skill and it passed the panel"). It is *not*
  saying "I see myself" with eyes, or "I feel changed." It is authoring a true
  summary of what its state now is — which is *exactly* the EMP philosophy:
  identity grounded in observable behavior, not a soul.
- An image model renders that summary. The animal changes because the
  underlying state changed. So watching it evolve is watching **real growth,
  not theater** — the opposite of a static SOUL.md fiction.

Framed this way, the glyph doesn't violate the no-soul principle — it is its
*fullest expression*. Where a soul.md is a self-concept an agent lies to itself
about and never updates, the trellis glyph is a self-concept that is recomputed
every day from the record, that cannot drift from the truth (it's a function of
the ledger), and that a human can audit ("why does it look more confident? —
because its verification pass-rate rose 12% this week"). It is the anti-soul: a
face on honest data.

The market has *verification* (traces) and *control* (inboxes) for engineers.
Nobody has fused the **honest data-viz avatar** with the **agent control-plane**.
That's the unoccupied space, and it's ours to take — later.

---

## What v0.1 already does to make this buildable

Nothing above requires re-architecting the backend, because the spine was built
for it:

- the **ledger is the event store** the UI tails (no new persistence);
- **decisions carry EMP lineage** (the timeline already has its edges);
- **loops and passes are state machines** (the kanban columns already exist);
- **staged actions** are the inbox's rows;
- **panel verdicts** are the verification panel's cells;
- the **EMP + ledger deltas** are the honest inputs the glyph renders from.

When it's time, the UI is a *read-mostly view over data that already exists*,
plus one compile-prose-to-loop authoring flow. That is the reward for building
the backend honestly first.

---

*Not in v0.1. A later version. But the backend shipped today keeps every door
above open — that was the point of building the spine before the skin.*
