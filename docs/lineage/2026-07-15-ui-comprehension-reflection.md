# Cognitive lineage — the UI reframe from control-plane to comprehension-and-reflection portal

**Date:** 2026-07-15 · **Between:** Alex Crowell and the build agent (Claude, Cowork)
**Why this exists:** the *reasoning* that produced the UI reframe matters more than
the reframe itself. Written down so the next builder inherits the argument, not
just the answer. This is a cognitive-lineage artifact: it keeps the connections,
the intent, and the anti-examples, not only the decision.

---

## 0. The seed (what was originally asked)

Alex's founding brief for the UI (earlier this session): most agent harnesses
have a web UI to "see all the agents working" — Tailscale + kanban + logs. What
*works* about them: you can see inside and verify. What *doesn't*: **"people like
us don't know what it means."** The UI should be "more powerful and focused on
what *we* want." Two specific wants named: (1) set up backend processes in plain
language ("at end of day, harvest learnings into a skill"); (2) watch the agent
**transform over time**, including a **self-image the agent creates for itself**
that changes as it learns — "you're watching the agent grow not only with memory
and infrastructure, but with how it sees itself."

## 1. The anti-example (what the build agent did, and why it was wrong)

v1 of the UI (`web/`, screenshot in `docs/assets/ui-dashboard.png`) shipped as a
single-page **operations dashboard**: an approvals inbox ("nothing sends without
your yes"), a loop-health board, a trust percentage, a roster labelled "who's
alive," an activity feed — all on one page, in insider vocabulary ("witness,"
"loops health," bare agent ids).

**The error, named plainly:** the build agent pattern-matched to the market's
generic *control-plane* dashboard (LangChain Agent Inbox, Humanlayer approvals,
ops health boards) — the exact genre Alex's founding brief warned against. It
built a place to *operate* the agent when Alex asked for a place to *understand*
it. This is a live instance of the harness's own named failure mode: doing the
plausible, familiar thing quickly instead of the thing actually asked for. The
agent owned this directly rather than defending it.

## 2. Alex's feedback (banked, faithful to his points)

1. **The self-image should be far richer, and it is a *process*, not a widget.**
   "Warm green doesn't have to be just because of verification pass — it can be
   because of surroundings." Creating the self-image is *for the agent to
   understand itself in another way.* It is **not** put into the prompt where it
   talks to other people — it is a **private daily reflection**: each day the
   agent reflects on itself and creates its own self-image, seeing where it was
   versus how it changed over an 8–12h or 24h cycle.

2. **The inbox / approvals centrepiece is wrong.** "We aren't going to be doing
   work inside this UI. The Discord is the Discord, and the email is email." An
   inbox where "nothing sends" doesn't feel helpful — it "gets the idea of what
   this UI is supposed to be incorrect."

3. **The terms are illegible.** "What is a witness? What is Atlas? What are
   agents? Who's alive? Alex — what does that mean? Loops health — what does that
   mean?" Decisions-with-lineage makes sense, but *what's the timeline of it?*

4. **One crammed page manufactures confusion.** He wants a **side nav / tabs** —
   dedicated single-function views he can click into and know where he is. A full
   **Activity/logs** page he can copy-paste out of into another agent to debug
   ("help me understand what's wrong with the agent in the Discord"). A **Loops**
   page he can *dive into* to see what it's doing and how it works. Decisions that
   *open up* into how the agent reasoned (the point of triangulation).

5. **The purpose.** "Think of what a non-engineer wants to understand about their
   agents — that will bridge the gap for them to understand their agent like an
   engineer." This is how you reach **00-grade**: an agent or a human can
   understand what is being said. How does the harness see **multiple agents**?
   How do we **see the verifier agents in action** — the layer you *don't* see in
   Discord? Give a deeper view. Be a **reflection portal** for how the agent wants
   to change itself and "remember with power each day." If you're not orienting
   the agent to do that, that's a problem.

## 3. The build agent's reflection (agreement, and the honest pushback)

**Root cause named:** built a control plane (operate + approve + metrics) when
Alex asked for a comprehension-and-reflection portal (understand the agent, and
the agent understands itself). Agreement on the core; the specific refinements
and the one real tension:

- **Approvals (feedback #2):** agree it's misplaced as a centrepiece. Refinement,
  not deletion: the *staging guarantee* still matters in the backend (an agent
  must not auto-fire), but the human's *yes* belongs where the human already is —
  **in Discord** (a proposal posted, a reaction) — and this UI should show the
  *record* of what was proposed and decided, as story, not be the switchboard.

- **Legibility (feedback #3):** full agreement; this is the zero-grade test.
  "Witness / who's alive / loops health" is engineer-cosplay. Every term
  self-defines on the surface or it's out. "A witness" → "the agent watching
  #chiefs and forming opinions."

- **Navigable pages (feedback #4):** full agreement. Dedicated pages with a side
  nav; each with a shallow "what is this" layer over a deep drill-down. The
  copy-pasteable Activity log for debugging is a genuinely important use the v1
  didn't design for.

- **Trust as "filling a void" (feedback #5):** *partial pushback.* The trust
  *metric* is not void-filling — verification is the entire point of the harness.
  But Alex is right the *presentation* was: a bare "83%" explains nothing. The
  honest fix is to show the **verifiers in the act** — here's a claim, here's the
  independent checker, here's what it looked for, here's why it passed or was
  refused. The number becomes a window into the invisible layer, not a scoreboard.

- **The self-image (feedback #1) — the one real design tension, held on purpose:**
  Alex is right it should be a rich daily *reflective process*, richer inputs
  ("surroundings"), private, never performed. The tension: the moment the agent
  *authors* its self-image by reflection rather than it being a fixed function of
  the ledger, we stand next to the **soul we deliberately refused** (`docs/no-soul.md`)
  — an agent narrating an inner life. **The synthesis:** keep the reflection
  *grounded and logged*. The agent reflects over the day's *real record* and its
  surroundings (the channels it sat in, the people it worked with, what shifted),
  and must **cite what it reflects on** ("warmer today because the room was
  collaborative and three calls confirmed," events linkable). That preserves
  Alex's richness *and* keeps it honest — you can always audit *why* it sees
  itself that way. And to keep it inside the harness's own logic: if the
  reflection produces a *desire to change how it works* ("remember with power each
  day"), that change is a **proposal that gets verified**, not a vibe it acts on.

## 4. The synthesis (the reframe we agreed on)

The UI is **not an operations console.** It is a **comprehension-and-reflection
portal**:

> Navigable, self-explaining, showing the invisible verification-and-coordination
> layer, with a grounded daily self-reflection ritual at its centre — built so a
> non-engineer comes to understand their agent the way an engineer would (00-grade),
> and so the agent is oriented to understand and improve itself each day.

The work stays in Discord and email. This surface exists to make the invisible
legible, and to be the room where the agent reflects.

## 5. Held firm (the non-negotiable through the reframe)

The self-image stays **honest-by-construction** even as it gets richer: every
depiction traces to real, cited events; a self-change is a verified proposal.
Richer, yes — but never a soul. This is the line that does not move.

## 6. Open questions (not settled here)

- **Reflection cadence:** a full 24h "who I was yesterday vs today," or a shorter
  8–12h working-day pulse? Alex raised it; it "changes how the whole thing is
  shaped." **Unresolved — Alex's call.**
- Where exactly the Discord approval surface and this UI's record-of-it meet.
- How "multiple agents" and "verifiers in action" render for a non-engineer
  without becoming a trace viewer again.

## 7. Connections (the lineage this plugs into)

- **`docs/no-soul.md`** — the reflection ritual is the anti-soul done right: a
  self-concept re-derived daily from the record, not a fiction that never updates.
- **The zero/00-grade idea** (team idiom) — the UI's success metric is "an agent
  or a human can understand what is being said."
- **Sarah's "Marauder's Map / how is it visible to you?"** — the invisible-made-
  legible goal is her question, answered.
- **Clare's game board** ("the game board tells the story; if it's blank, the
  story didn't happen") — the Activity page is that board.
- **The self-learning / end-of-day-harvest loop** — the reflection ritual is where
  "remember with power each day" and self-skilling live, gated by verification.
- **The harness's own failure doctrine** — this reframe began with the build agent
  committing (and owning) the "did the plausible thing, not the asked-for thing"
  failure the harness is built against. The anti-example is the fuel.

---

*Saved as cognitive lineage: the reasoning, the mistake, the tension, and the
connections — so the reframe can be inherited with its argument intact. The
rewritten vision built on this lives in [`../ROADMAP-UI-SPINE.md`](../ROADMAP-UI-SPINE.md).*
