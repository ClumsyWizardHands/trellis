> **RATIFIED 2026-07-21.** All eight were decided by Alex and are now recorded in
> `DECISIONS.md` (D31–D38) — the canonical entries capture his answers, including the
> three that modified the recommendation below (D32: DMs are IN with session-tracking;
> D33: less gating — the agent may change its own mind, logged, escalating only sometimes;
> D38: ship everything at once to a private server). This memo is kept as the reasoning
> record. One flag remains open: whether outbound sends stay human-approved (default) or
> go autonomous — see D38.

# Decision memo — D31–D38 (the go-live blockers only Alex can decide)

**From:** Fable (lead auditor)
**Date:** 2026-07-21
**Companion to:** [FABLE-ARCHITECTURE-AUDIT-2026-07-21.md](FABLE-ARCHITECTURE-AUDIT-2026-07-21.md), [CODE-SANITY-AUDIT-2026-07-21.md](CODE-SANITY-AUDIT-2026-07-21.md)

Both audits agree: the intended function is coherent and mostly built as *stations*, but there
is no conveyor between them and no driver underneath. The Phase-1 hardening fleet is fixing the
19 confirmed runtime defects in parallel — none of those need you. **These eight do.** Each
blocks a downstream build; none can be resolved from the code or doctrine alone (I checked — where
a decision record already answers it, I did not raise it here). Format matches DECISIONS.md so a
ratified answer drops straight in as D31–D38.

For each: the question, the options, **my recommendation (first, marked)**, and what it unblocks.
Answer Y/N/T in your own idiom — a T with a named missing piece is a fine answer and several of
these deserve one.

---

## D31 — The canonical Discord ingestion spine

**The question.** Two ingestion pipelines exist and disagree, and the repo's own documents route
Discord to different ones. `trellis/ingest.py` (`ingest_discord` / `ingest_scoped_discord`) is
attributed, surface-keyed, and isolation-gated — but has **no dedup, no markers, no provenance**.
`trellis/sources.py` (`Ingestor`) has the full D19 idempotency contract (identity-key dedup,
content-hash corrections, two-phase started/complete markers, retire-and-reharvest on edits) —
but **no allowlist gate**, and Discord never touches it. `DECISIONS.md` D19 says Discord rides the
Ingestor; `docs/SETUP-ISOLATED-DISCORD.md` wires the live poller to `ingest_scoped_discord`. There
is no `DiscordMessage → RawItem` bridge; the two records of one message share no join key even in
the end-state.

**Why it can't be auto-decided.** Following SETUP exactly double-writes the ledger on poll #2
(reproduced: duplicate statements make `position_history` render a false "view shifted"). But D19
was ratified for *Atlas dumps*, and whether live Discord is "another source through the Ingestor"
or "a first-class surface with its own gated path" is a genuine architecture call about where the
isolation boundary and the idempotency boundary compose.

**Options.**
- **(A) ✅ Recommended — Bridge Discord onto the Ingestor.** Build `DiscordMessage → RawItem`
  with `item_id = message_id`, carrying `ConversationKey` + the isolation allowlist through the
  Ingestor's front door. One idempotency contract, one provenance model, D19 honored, isolation
  preserved. Cost: one adapter + threading the allowlist into `Ingestor.discover()`.
- **(B) Port the markers into `ingest_discord`.** Give the Discord path its own dedup + two-phase
  markers. Keeps the gated path primary; duplicates the D19 machinery (drift risk — the thing D19
  exists to prevent).
- **(C) Keep both, define the join key.** Explicitly a two-record model with a documented shared
  key. Most work, least benefit; I don't recommend it.

**Unblocks:** the entire ingestion build (Phase 2), the poller (Phase 3), and closes cross-lane
disagreement #1 and #9 (per-source attribution rules). **Recommend A.**

---

## D32 — Does an allowlisted channel imply its threads? And is DM in scope for v1?

**The question.** `_discord_surface()` files a message under `thread_id or channel`
(`isolation.py:136-139`); thread ids are minted dynamically by Discord and cannot be pre-listed in
`TRELLIS_READ_SURFACES`; there is no parent-channel fallback, and `filter_readable` drops
non-allowlisted messages **silently**. So the canonical input — *a human message in a thread under
the one allowlisted channel* — vanishes without trace on the first live test. DM channel ids share
the dynamic-id problem, and DM privacy (rank 3, the most private surface) is the highest-stakes
leak class.

**Options (two coupled sub-questions).**

*Threads:*
- **(A) ✅ Recommended — an allowlisted channel implies its threads.** Add a parent-channel
  fallback in the surface resolver: a threaded message is readable if its `parent_channel` is
  allowlisted. Matches how humans read Discord (a thread belongs to its channel). Add a
  dropped-per-surface **counter** (never silent) and a regression test.
- **(B) Threads must be explicitly allowlisted.** Safer-narrowest, but unusable — you can't list
  ids that don't exist yet; effectively disables threads.

*DMs for v1:*
- **(A) ✅ Recommended — DMs OUT for the first live phase.** Launch reads one channel + its
  threads only. DM ingestion waits until the privacy-flow wiring (D36) is live, because a DM is the
  one surface whose leakage the system currently cannot prevent.
- **(B) DMs in, relying on the human gate.** Not recommended before D36.

**Unblocks:** the isolation build and the read-only live milestone. Also decide **backfill depth**
on first connect (how far back the poller reads) and **edit/delete mapping** (edit → D19 correction
via retire+reharvest? is a Discord delete reflected at all, given append-only?). **Recommend
threads-A, DMs-out, backfill = a bounded window (e.g. 7 days) you name, edits → corrections,
deletes → a tombstone event not a real deletion.**

---

## D33 — The Witness collision policy: what happens when it would repeat or change its mind

**The question.** `witness_cycle` records opinions via a bare `DecisionLog.record()`
(`agent.py:160`). An **identically-worded** repeat opinion raises `CollidingDecisionError` that
escapes the cycle and **crashes the driver process**; a **reworded** repeat silently mints a second
live head (the question-key is a folded free-text slug). The designed remedy —
`Navigator.decide/reopen/resolve` — has zero production callers, so the agent can currently never
legally change its own mind. The Phase-1 fleet is making the process **not crash** (catch per-opinion,
record a typed "skipped: reopen required" outcome) as a fail-closed stopgap — but the real semantics
are yours to set.

**Options.**
- **(A) ✅ Recommended — Escalate, don't auto-reopen.** On a collision with a live head, the Witness
  records that it *would* revise and stages a reopen for the human/next-cycle, rather than
  re-litigating a settled question every cycle. Preserves the trust posture (settled things stay
  settled unless deliberately reopened) and avoids opinion churn. Route recording through
  `Navigator.decide()` with an explicit `ReopenRequiredError` path.
- **(B) Auto-reopen on new evidence.** The Witness reopens and supersedes when its opinion changes.
  More autonomous, but re-litigates continuously and risks flip-flopping on ambiguous input — more
  dangerous for an unattended run.
- **(C) Idempotent-skip.** A repeat opinion is simply a no-op. Simplest, but then the agent's
  *changed* mind is silently lost — violates the "gets more trustworthy" thesis.

**Unblocks:** any sustained run at all (this is the day-one crash), and the write half of the
navigation grammar. **Recommend A.**

---

## D34 — The verifier seat and the independence bar

**The question.** The verification doctrine (D4 maker≠verifier, D25 outcome-not-existence, the
refute-by-default panel) is built and tested but **instantiated nowhere outside tests**. The factory
exposes exactly one model seat; there is no `TRELLIS_VERIFIER_*` config; wiring the panel in crashes
(a type bug the Phase-1 fleet is fixing). Before the model goes on, three things need your ruling:

1. **Is same-model-different-id ever "independent"?** Today independence is an id-string check. If
   Haiku verifies Claude, the independence is: different weights, fresh context, different prompt,
   refute-oriented — but same vendor. Is that structural enough, or do you require a *different
   provider/family* for the verifier seat?
2. **Panel or single verifier**, and **when does it convene** — every claim, only self-changes,
   or above a stakes threshold?
3. **May a model-only judgment ever return VERIFIED**, or does VERIFIED always require the
   deterministic outcome predicate to have held (D25), with the model able only to *refute* or add
   confidence? (Note: D25 already rules that existence ≠ VERIFIED; the Phase-1 fix makes the code
   obey it. This sub-question is the *next* layer — whether a model's "yes" can ever be an outcome.)

**Options for the seat.**
- **(A) ✅ Recommended — separate cheap verifier seat, different family preferred, refute-only.**
  Add `TRELLIS_VERIFIER_PROVIDER/MODEL`; the factory refuses loud if it equals the maker seat.
  Convene the panel on **self-changes and staged actions** (the high-stakes set), not every routine
  opinion (cost/latency). Model verifiers may **refute or add confidence but never mint VERIFIED** —
  the deterministic predicate remains the only path to VERIFIED. Independence bar: prefer a different
  family; allow same-family-different-id with a recorded warning, so you can start on one vendor and
  tighten later.
- **(B) Single ModelVerifier, every claim.** Simpler wiring, higher cost, weaker diversity.
- **(C) Deterministic floor only for now; model verifier deferred.** Cheapest, but then "independent
  verification" is not yet real — acceptable only for the model-free read-only phase.

**Unblocks:** the model-on phase, and makes the trust thesis's central mechanism real rather than a
seam. **Recommend A, running as C during the read-only phase.** Closes cross-lane disagreements #2,
#3, #4, #5.

---

## D35 — What REFUTED and INSUFFICIENT actually trigger

**The question.** On the only live path, a REFUTED verdict **retracts nothing** — the refuted
decisions stay active, the refuted read stays current, the run stays OK. Verdicts gate nothing. For
the thesis to hold ("independent verification earns trust"), a bad verdict must *do* something.

**Options (choose a behavior per status).**
- **(A) ✅ Recommended — REFUTED pauses + escalates; INSUFFICIENT flags; both feed the burn.**
  A REFUTED claim marks its decision/read `contested` (not deleted — append a contest event),
  removes it from the trusted read the next cycle compiles, and raises it to the human via the
  portal rail. A persistent INSUFFICIENT is recorded as a capability gap (evidence the agent
  couldn't get), not a silent pass. Both become harvested confusion ("burns") that ride the next
  prompt. Nothing auto-deletes; the human sees contested items.
- **(B) REFUTED just records, human decides everything.** Safer-passive, but then trust is
  display-only forever (make the docstrings say so — see disagreement #2).
- **(C) REFUTED auto-retracts.** Too aggressive for an unattended agent acting on model verdicts.

**Also decide:** the **one canonical trust formula** (four divergent ones exist across verify.py,
reflect.py, and two web views — the Phase-1 fleet is collapsing web to `verify.trust_record()`;
confirm that's the canonical one), and the standing question of whether **trust ever gates behavior**
or is comprehension-only. **Recommend A, canonical = `verify.trust_record()`, trust gates only the
three-bucket routing you already sketched (human-decides / agent-helps / agent-does), nothing
finer.**

---

## D36 — Where privacy flow (D7) is enforced

**The question.** `can_flow` / `guard_flow` / `declassify` (the DM > FILE > THREAD > CHANNEL lattice)
have **zero production call sites**. The context compiler's privacy filter is dead at three ends
(no caller passes `surface_scope`, no writer records a `scope` field, unscoped entries fail **open**).
Derived observation/opinion nodes carry no surface key at all. Staged actions carry no durable
source/destination. So today nothing stops a DM-sourced fact from surfacing in a channel-scoped
context or a public post — the machinery to prevent it exists but is wired to nothing.

**Options — where do the checkpoints live?** (not mutually exclusive; pick the set)
- **(A) ✅ Recommended — all four: write, compile, stage, fire.** Scope is recorded on **every
  memory write** (default-closed — an unscoped write is treated as most-private, not least); the
  compiler **excludes** more-private scopes from a less-private packet (default-closed on unknown);
  `guard_flow` runs at **stage** and again at **fire** with source+destination keys persisted on the
  staged action; the portal is itself treated as a private surface. Belt-and-suspenders, matching the
  "gets more trustworthy" posture.
- **(B) Fire-time only.** Cheapest; a single chokepoint before the world. But leaks can still pool in
  context and memory, and the compiler laundering path stays open.
- **(C) Compile + fire.** Middle ground.

**Sub-decisions only you can make:** the **scope taxonomy** for memory writes; whether **derived
nodes inherit** the source `ConversationKey`; and whether **content-provenance leaks** (a human
quoting a DM into a channel, paraphrase) are accepted as the *human's* responsibility rather than the
harness's — say so in writing either way, because the system cannot catch all of them. **Recommend A,
derived nodes inherit source scope, content-provenance is the human's responsibility (stated).**
This is the precondition for admitting DMs (D32).

---

## D37 — The runner: what ticks it, how often, supervised how, and the spend cap

**The question.** There is **no daemon**. `serve()` / `run_due()` have zero non-test callers; the CLI
offers only `init/doctor/demo/web`. `Budget` is per-run, never constructed in production, with no
reset window (fresh-per-tick = no daily cap → the cited "$300 in two days" failure; shared = permanent
lockout). A hard kill leaves an orphaned `loop_run_start` that **nothing reads** — the flagship
no-silent-failure refusal doesn't cover process death. `scheduler.verify()` has zero consumers,
including the portal, so detected silence isn't even pull-visible.

**Options — runner shape.**
- **(A) ✅ Recommended — external cron/launchd calls `trellis tick`; in-process `serve` for dev.**
  A `trellis tick` entrypoint runs one due-schedule pass and exits; a launchd/systemd timer owns the
  cadence and restart. Survives crashes (the OS restarts the timer), matches D6's "the deployment's
  choice," and keeps trellis stdlib-simple. `serve()` stays for local dev.
- **(B) Long-lived `serve()` daemon under a supervisor.** One process, simpler mental model, but you
  own crash-restart and it holds more state across ticks.

**Sub-decisions:** **cadence** (every N minutes? only during active hours?); the **daily spend cap +
reset window** (derived from ledger charge records, so it survives restart) and whether **verification
spend shares** the run budget; the **alert channel** for harness health — and specifically **whether a
health alert may bypass stage-don't-fire** (I lean yes: a "your agent died" ping is not an agent action
and shouldn't wait behind an approval). **Recommend A, cadence every ~15 min during active hours you
set, a ledger-derived daily cap you name, verification spend counted against it, health alerts allowed
to bypass the gate because they are the harness speaking, not the agent acting.**

---

## D38 — The formal launch posture, in writing

**The question.** `doctor` warns if `TRELLIS_ACT_SURFACES` is armed, which *implies* a
read-and-stage-only launch — but this is **stated nowhere as a ratified posture**. The executor
(send path) is deliberately unbuilt (D30's own sequencing). This should be an explicit decision so the
staged rollout is a commitment, not an accident of what happens to be built.

**Options.**
- **(A) ✅ Recommended — ratify the three-phase posture explicitly.** *Phase 1:* read-and-stage-only,
  model-free, one channel + its threads, no DMs, no executor — run for a named number of boring,
  verifiable weeks. *Phase 2:* model on (D34), still stage-only, trust display appears. *Phase 3:*
  executor built, `guard_act`/`guard_flow` composed at fire, posting spec defined, apply-bridge for
  ratified proposals. Each phase gate is "the prior phase produced a clean verified record for N
  weeks." Write it into DECISIONS.md so no one (including a future you, or the agent proposing its own
  acceleration) can skip a phase.
- **(B) Leave it implicit.** Not recommended — the whole thesis is that the record, not intention,
  governs; the launch posture should live in the record too.

**Unblocks:** nothing technically, but it's the frame that keeps D30's sequencing honest and gives the
Phase-5 executor work a gate. **Recommend A.**

---

## Summary — the smallest set, in order

| # | Decision | My rec | Unblocks |
|---|----------|--------|----------|
| D31 | Canonical ingestion spine | Bridge onto Ingestor (A) | all of ingestion |
| D32 | Channel⇒threads; DMs out for v1 | A / out | read-only live milestone |
| D33 | Collision policy | Escalate, don't auto-reopen (A) | any sustained run (day-one crash) |
| D34 | Verifier seat + independence bar | Separate refute-only seat; run floor-only first | model-on phase |
| D35 | What REFUTED/INSUFFICIENT do | Pause+escalate+burn; one trust formula | trust becomes real |
| D36 | Privacy-flow checkpoints | All four, default-closed | admitting DMs |
| D37 | Runner shape + budget + alerts | cron `tick`; ledger-derived cap; alerts bypass gate | the unattended run |
| D38 | Launch posture in writing | Ratify the three-phase gate | keeps the sequencing honest |

**Only D31, D32, and D33 block the very next build** (a survivable read-only live test). D34–D37 block
the model-on and acting phases. D38 is the frame. If you answer just the first three, the Phase-2/3
builds can start immediately; the rest can follow as those phases approach.
