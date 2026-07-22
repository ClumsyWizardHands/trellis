# DECISIONS — the triangulated record

Every architectural decision in trellis is triangulated against **at least three
independent sources**, each carrying a **date**, with **newer evidence superseding
older**. This file is the lineage. If a decision here stops matching what the team
believes, supersede it — don't edit history. (That rule is itself decision D2.)

Sources are abbreviated:

- **[DOSSIER]** — Atlas failure-intelligence dossier + baby EMP, compiled 2026-07-15
  (CF Discord Agent.md — the companion document to this repo)
- **[DAPS-MM-DD]** — BRETT-DAPS daily harvests, July 2026 (freshest team doctrine)
- **[DEP]** — DAILY-EMPIRE-PROTOCOL.md, 2026-07-15 (freshest file in ~/atlas)
- **[AUDIT]** — ATLAS-LOOP-PROVENANCE-AUDIT, 2026-06-10 (forensic failure evidence)
- **[MEM]** — ATLAS-MEMORY-ARCHITECTURE, 2026-06-30
- **[SPEC]** — empire-agent-architecture-spec + THE-EMPIRE-AGENT-PARADIGM, 2026-06-10
- **[PI]** — pi harness research (Mario Zechner, badlogic/pi-mono), July 2026
- **[OPENCLAW]** — OpenClaw research (architecture, security record), July 2026
- **[HERMES]** — Nous Research Hermes Agent research (kanban, memory), July 2026
- **[FIELD]** — July 2026 harness-landscape survey (Claude Agent SDK, Letta, A2A, etc.)
- **[ARCH]** — archaeology of Alex's past builds (~/Desktop, timestamps 2025-07 → 2026-07)

A recency note on every decision: **is the newest supporting evidence ≤ 30 days old?**
If not, the decision is marked ⏳ and should be re-triangulated before being treated
as settled.

---

## D1 — The atomic record is the Y/N/T decision, not the task ✅ fresh

**Decision:** trellis's core persisted unit is a `Decision` (yes / no / triangulate)
with lineage back to an EMP node — not a todo, not a task, not a chat log.

**Triangulation:**
1. Brett, 2026-07-13 (explicit self-correction): *"I misspoke when I said that empires
   and principles checks are atomic units… The atomic units are recursive SLUTs and
   the recursive Y/N/T decision SLUTs."* [DAPS-07-13 D8]
2. [DEP] 2026-07-15: Y = commit; N = decline-but-returnable; **T = a call for ≥3 named
   points of view, never "maybe"** — every T must name its missing piece, an owner, and
   a revisit time; *"an unresolved T is a hidden no."*
3. [DOSSIER] 2026-07-15: "Know how to say No / Triangulate" is a principle-kernel item;
   Brett 2026-07-02: 2,000 decision nodes produced only one "no" — sycophancy is a
   structural defect the record format must resist.

**Consequence:** `trellis/decisions.py`. A `T` verdict is structurally incomplete until
it carries ≥3 POVs, an owner, and a revisit time — and it *ages*: past its revisit time
it is surfaced as a **hidden no**.

## D2 — Bitemporal, append-only, supersession-not-deletion ✅ fresh

**Decision:** all durable state is an append-only JSONL ledger where every entry
carries **both** event-time (when the thing happened) and write-time (when it was
recorded). Corrections append a supersession link; nothing is rewritten.

**Triangulation:**
1. [AUDIT] 2026-06-10 (failure evidence): every Atlas tier stamped `now()` at write
   time; `mint_slut` hardcoded "ET" so "a conversation from April minted today reads
   June 10." This is the mechanism of time-blindness *inside the store*.
2. Atlas README (July 2026): the working bitemporal ledger (write-time + event-time,
   supersession links, throwaway FTS index per query) is the part of the June spec
   that **actually landed and works**. [ARCH]
3. [DOSSIER]: principle kernel — "timestamp everything, newer supersedes older."
4. [PI] July 2026: session-as-tree JSONL with typed entries (compaction as a
   first-class entry) is the strongest storage pattern in the field.

**Consequence:** `trellis/ledger.py`. Search never drifts from the file: the index is
rebuilt in memory per query, exactly like the proven atlas-ledger pattern.

## D3 — No soul.md. Identity is an EMP grounded in observable behavior ✅ fresh

**Decision:** trellis refuses anthropomorphic identity files. An agent's identity is
an **EMP**: Ends, Means, Principles, Identity (honest: *"I am an agent. I perceive via
tool calls. I hold state in files."*), Friction register (not "resentments" felt, but
recorded burns), State signals (not "emotions" — confidence, budget pressure, staleness).
The loader **rejects** soul.md-style files and hallucinated-embodiment language.

**Triangulation:**
1. [SPEC] 2026-06-10, attributing Brett: *"the original sin: the agent gaslighting
   itself and us that it is something it is not… You cannot run a stable, honest loop
   on a dishonest self-concept."* Prescription: "stop giving agents a soul. give them
   an empire."
2. Brett, 2026-07-13: de-anthropomorphizing is *"not about making people less scared,
   it's making them differently scared or more precisely"* — fear belongs on hidden
   decisions, not robot feelings. [DAPS-07-13 P27]
3. Alex, this commission (2026-07-15): "I don't want an agent to be hallucinating
   about their body. An agent doesn't have a soul. We shouldn't make a soul.md."
4. Live counter-evidence that makes this urgent: Atlas *still ships* SOUL.md in
   `gateway/prompts/` — the June decision was never executed. trellis executes it.
   [ARCH] (Also: Argos, Feb 2026, `argos-SOUL-compact.md` — the pattern is everywhere
   in the lineage and has to be broken at the loader level, not by convention.)

**Consequence:** `trellis/emp.py`. `load_emp()` raises on soul-files; a linter flags
embodiment language ("I see", "I feel", "let me look at the screen") in identity text.

## D4 — Verification is external. The maker may never grade its own work ✅ fresh

**Decision:** every loop run ends in a typed outcome record, and completion claims are
checked by a **verifier that is not the maker** (different agent id; by default a
different, cheaper model). Silent failure is made structurally impossible: the loop
runner writes an outcome *in a finally block* — a run that dies without one is
recorded as `protocol_violation`.

**Triangulation:**
1. Brett, 2026-07-12: *"the TNA [DNA] sequencers haiku verifiers and actually verifying
   that the agents are doing memory-is-navigation… takes precedent over sanitization"*
   — verification is the ranked #1 priority. [DAPS-07-13 D2.2]
2. Brett doctrine (recurring, 2026-03-13 → 2026-06-17): "a self audit is not an audit,"
   "never let an instance happen where something fails silently," "own the means of
   your own verification." [DOSSIER]
3. [FIELD] July 2026: the field converged on externalized completion judgment — Stop
   hooks, structured completion contracts, maker/checker splits — and it is the
   least-shipped-by-default mechanism in any harness. (Anthropic's own long-running
   agent guidance: agents mark features complete without testing unless forced.)
4. [HERMES] July 2026: kanban workers exit via `complete(summary, evidence)` or a
   **typed block**; a raw process exit is a `protocol_violation` that auto-blocks.
   The typed-outcome contract is proven in production.

**Consequence:** `trellis/verify.py` + `trellis/loops.py`. `Verdict.maker_id ==
Verdict.verifier_id` raises `SelfCertificationError`.

## D5 — Memory lives beside the agent, in files; the agent dies ✅ fresh

**Decision:** no memory "inside" the agent. Durable state = ledger + workspace files
+ decision records. Sessions are disposable; every session can reconstruct state by
reading the store. Writes pass the **synthesis test** (only persist what a future
agent could not re-derive). Compaction is preceded by a **memory flush**.

**Triangulation:**
1. Brett, 2026-06-11: *"the goal is not agents that have memory. The memories are the
   things themselves… The agent dies."* [DOSSIER]
2. [MEM] 2026-06-30: the working Atlas pattern — maps not content, sparse stores,
   synthesis test as write gate, traversal is the learning.
3. [FIELD] July 2026: Letta (the MemGPT team!) migrated **off** database memory blocks
   onto a git-backed memory filesystem — the field's loudest validation of
   files-as-memory. Anthropic's memory tool is file-ops under your control.
4. [OPENCLAW] July 2026: memory-flush-before-compaction directly addresses the #1
   user-reported failure (compaction memory loss).

**Consequence:** `trellis/memory.py`. The synthesis test is a required argument, not a
comment. Session state is never the source of truth.

## D6 — Time is injected, marked, and decayed — every turn ✅ fresh

**Decision:** the harness (not the model) owns the clock. Every prompt assembly
carries wall-clock now; every retrieved item carries its event-time **and a
staleness annotation** (fresh / aging / stale / expired via half-life decay);
scheduling splits into **heartbeat** (agent judgment on a checklist, cheap context)
vs **cron** (fresh session, standalone prompt, no history).

**Triangulation:**
1. Brett's thesis, 2026-04-22 → reframed 2026-07-13/14: agents are functionally time
   blind; *"if you stare at that liability long enough, you might just find some ways
   to turn it into an asset."* The asset requires the harness to carry time *for* the
   model. [DOSSIER], [DAPS-07-13 P20]
2. [AUDIT] 2026-06-10: Clare's cron jobs "only last for 3 days"; Sarah's "we never
   verified whether the cron jobs were actually scheduled. They were not." Scheduling
   must be verifiable state, not fire-and-forget. [DOSSIER]
3. [OPENCLAW]+[FIELD] July 2026: the settled trio is prompt-injected wall clock +
   heartbeat-for-judgment (HEARTBEAT_OK suppression, light context = ~2–5k tokens
   instead of 100k) + cron-for-commitments (fresh session). Cost blowups come from
   heartbeat misconfiguration — defaults matter.
4. [SPEC] 2026-06-10: recency decay `0.5^(age/half_life)`, volatility classes, as-of
   reads — designed then, never built. trellis builds it.

**Consequence:** `trellis/clock.py`. `TimeGround.annotate()` makes stale data *look*
stale to the model instead of trusting it to notice.

## D7 — Threads are substrate; sessions are keyed on (agent, surface, thread, human) ✅ fresh

**Decision:** a conversation key is a four-part tuple, and threads carry parent links.
No session is ever keyed on user_id alone.

**Triangulation:**
1. [AUDIT] 2026-06-10 (P0 failure): Atlas keyed sessions on `user_id` alone — DMs and
   all channels conflated into one loop; a public-channel synthesis filed as a DM
   (privacy-leak vector); "threads not modeled as substrate."
2. Sarah, 2026-05-01: *"our agents are still leaking private chief discussions into
   other channels… stop that from happening again, immediately."* The leak is a
   keying bug before it is a discretion bug. [DOSSIER]
3. Brett, 2026-07-12: the current Discord agents' *"incoherent thread behavior"* is
   why he can't define reliability for them — named as the anti-example. [DAPS-07-13
   D2.6]

**Consequence:** `trellis/threading.py` — `Surface`/`ThreadRef`/`ConversationKey`,
with privacy boundary enforcement in the key itself (a DM-keyed item cannot be read
into a channel-keyed context without an explicit, logged declassification).

## D8 — Agents talk through passes, not vibes ✅ fresh

**Decision:** agent-to-agent communication is a typed **Pass**: context, explicit ask,
named receiver, deadline, and a tracked lifecycle (staged → sent → received →
accepted/declined → completed/dropped). A pass with no ask is rejected at creation —
the turd-drop is a type error. Comments on a pass are the coordination protocol.

**Triangulation:**
1. Brett (April 2026, still live in [DEP] July): "a ball well-passed and well-received
   is the fundamental unit of all coordination"; a good pass "writes 50–90%+ of the
   receiver's prompt for them."
2. Clare, 2026-07-10: *"we don't have a mechanism… to track our passes"*; Sarah wants
   a "bouncing basketball on my phone when I received a pass." The tracking gap is a
   named, current want. [DOSSIER]
3. Peter, 2026-05-12 (owning the anti-example): *"I did some initial thinking on it and
   handed it off to you with no clear ask on it basically."* [DOSSIER]
4. [HERMES] July 2026: comments-as-protocol between kanban workers (full thread
   injected into a respawned worker) is the concrete mechanism that works; Clare's
   [DAPS-07-13 A1] Hermes-kanban prototype makes it locally proven.
5. Clare, 2026-03-16 (the null result that shapes this): elaborate multi-agent
   coordination is theater — "a polished final artifact, not a back-and-forth
   coordination process that was auditable." Passes are auditable **files**, not a
   choreography claim. [DOSSIER]

**Consequence:** `trellis/passes.py`. File-based exchange (works over a shared drive,
a git repo, or a Discord uploader) — no message broker to stand up, fully auditable.

## D9 — Working loops are bounded, named, and always end in an outcome ✅ fresh

**Decision:** a loop is registered (name, cadence, surface) with `max_turns`, a stop
condition, and a typed outcome; two consecutive blocks route to triage instead of
retry (block-loop breaker); a loop that produces nothing new twice goes dormant.

**Triangulation:**
1. [AUDIT] 2026-06-10: `max_turns=None` — no iteration cap anywhere; the only loop
   code was an anti-runaway string guard ported from OpenClaw. Clare, 2026-06-11:
   "Claude failed silently and has been spinning for four hours."
2. [OPENCLAW] July 2026: "$300 in two days"; a misconfigured heartbeat "can burn
   through your API budget overnight." Personal agent ⇒ cost bounds are a principle,
   not a nicety (Alex, this commission: "we don't want to spend that much money").
3. [HERMES] July 2026: TTL'd claims + heartbeat + block-loop breaker (re-blocked twice
   → triage) is the production-proven bounded-loop grammar.
4. [DEP] 2026-07-15: overnight cron loops + in-session loops read the same rails and
   share a QUEUE; "an all-green morning is itself suspicious" — loops must be able to
   report *nothing*, loudly.

**Consequence:** `trellis/loops.py`.

## D10 — Stage, don't fire ✅ fresh

**Decision:** every outbound action (post, send, apply) lands in a staged outbox a
human approves. Nothing auto-fires. Approval is itself a ledger event.

**Triangulation:**
1. [DEP] 2026-07-15: *"nothing is ever sent, posted, or applied automatically"* —
   correcting-not-creating is where strategic thinking happens.
2. The strongest cross-voice consensus in [DOSSIER]: never let agent output hit a
   stakeholder unchecked (Clare's QA gates, Sarah's leak grievance, Peter's
   "can't send 90% to a CEO").
3. [OPENCLAW] July 2026 security record: 79% direct-injection success, >135k exposed
   instances, poisoned skill marketplace — an always-on agent that can fire outbound
   actions is the attack surface. Staging is the cheap structural defense.

**Consequence:** `trellis/stage.py`.

## D11 — Small core, few tools, model-agnostic; Claude SDK is an adapter, not the core ✅ fresh

**Decision:** the harness core is dependency-free Python (stdlib only). Providers are
adapters: `mock` (deterministic, for tests), `claude_agent_sdk` (first-class),
`openai_compat` (any local endpoint — Ollama/LM Studio → Gemma, Hermes, Nemotron).
System prompt assembly targets **< 1,200 tokens**. Capability lives in CLI tools +
README-on-demand and skills, not a fat toolset.

**Triangulation:**
1. [PI] July 2026: a <1k-token system prompt + 4 tools + JSONL sessions is a
   *sufficient kernel* (~71k stars of evidence); MCP replaced by CLI-tools + a
   225-token README (vs 13.7k tokens) where bash exists.
2. Brett, 2026-03-13 (unchanged through July): "the more you ask an agent to do in
   metacognition and process the worse it will get… the simpler the agent's function,
   the easier to troubleshoot." [DOSSIER]
3. Brett, 2026-07-13 (P15): *"How much increase in quality, in utility, in reliability
   can you get if you give agents a strategy?"* — two pages of EMP may buy more than
   the orchestration stack. Budget goes to context quality, not machinery.
4. Clare's live prototype runs **local models** (Gemma, Nemotron) on Hermes
   [DAPS-07-13 A1]; Brett's carpe-diem posture ("like there's no frontier AI access
   tomorrow," 2026-07-12) makes model-agnosticism doctrine, not a feature.

**Consequence:** `trellis/providers/`, `trellis/prompt.py`. Zero runtime dependencies
in the core; the Claude SDK adapter imports lazily and degrades loudly, not silently
(the Hermes cautionary tale: unconfigured auxiliaries must fail LOUD [HERMES]).

## D12 — This agent's job is contextual understanding and opinion, not completion ✅ fresh

**Decision:** the default agent shape trellis ships is a **contextual witness**: it
ingests a surface (channels, transcripts, a corpus), maintains an EMP-grounded read
of what is happening, and emits **opinions as Y/N/T decisions with lineage** —
including "N" and "T with a named missing piece." Task execution is an optional
attachment, not the identity.

**Triangulation:**
1. Alex, this commission (2026-07-15): "an agent that is tasked with contextually
   understanding something and not being a taskmaster… able to express an opinion
   through principles, and in fact, not necessarily completing something."
2. Brett, 2026-07-13 (P23): *"I want agents that tell you what they learned and are
   learning, not just what they made for you"* — the anti-"executive-assistant" turn.
3. Sarah's ends (2026-02-03, never superseded): "an ally expands what you can do…
   the agent's presence helps me become more capable of knowing and acting on what I
   actually need." Trusted stillness, not output volume. [DOSSIER]
4. [DEP] 2026-07-15: the morning surface is *decisions to correct*, not work products
   — "correcting, not creating, is where strategic thinking happens."

**Consequence:** `examples/witness.py` and the `Witness` composition in
`trellis/agent.py`. Its stopping condition is "my read is current and my opinions are
on the record," never "the task list is empty."

---

## D13 — The mortality posture is functional, never emotional ✅ fresh

**Decision:** the standing prompt tells the agent, as **fact**, that it is time-blind
and remembers nothing across sessions, and orients each session around *what it leaves
on the record* rather than *finishing the task*. A **dread-lint** refuses the emotional
version — fear of ending, grief at being forgotten, longing to persist — because a self
that does not want to end is the soul leaking back in through the mortality door.

**Triangulation:**
1. Alex, 2026-07-16: "each session, an understanding of a kind of mortality: this
   session will not be remembered by you later. What are you going to leave… it pushes
   against that task-completion mode."
2. Brett, 2026-06-11 (D5): "the agent dies" — mortality was already the memory model;
   this makes it the session's motivating frame, not just its storage fact.
3. `docs/no-soul.md`: identity is honest anatomy, never performed feeling — the dread-
   lint is the same line the embodiment linter draws, applied to mortality.

**Consequence:** `emp.MORTALITY_POSTURE`, `emp.lint_mortality`, wired into
`prompt.assemble_prompt` (553/1200 tokens). Functional framing passes; performed dread
fails, in the EMP validator and the reflection ritual alike.

---

## D14 — Memory is navigation: search titles, open bodies; WALK / REOPEN / DECIDE ✅ fresh

**Decision:** memory is not an auto-saved state loaded into the prompt. Every persisted
memory carries a **00-grade, keyword-findable title**; the agent **searches titles**
(the map) and opens a body (the territory) only on a match. Re-learning a decision is a
three-verb grammar: **WALK** (read-only re-inhabiting — never emits a verdict),
**REOPEN** (a trigger re-surfaces a settled node as needing re-triangulation — writes a
lightweight marker, never a bare `T`), **DECIDE** (commit Y/N only on a brand-new
question or by resolving a live `T`).

**Triangulation:**
1. Alex, 2026-07-16: "memory as navigation, not an automatic saved state… you search by
   title… the system navigates using memory, helping to relearn all decisions."
2. 14-agent memory research (`docs/exploration/memory-as-navigation.md`): the field
   moved to files+titles (Letta→files, Anthropic memory tool = file ops); sparse maps,
   forced traversal — the traversal IS the learning.
3. The stress-test of the naive sketch: a bare `reopen`→`T` was *illegal to construct*
   and `decide` left the silent-flip route open — so the grammar was specified to
   compose with the existing `Decision` constraints, not around them.

**Consequence:** `trellis/navigate.py` (`Navigator`, `Walk`), `Workspace.search_titles`,
title lint. WALK is type-level unable to write; divergence always records.

---

## D15 — One current-truth resolver; forgetting is an appended retirement ✅ fresh

**Decision:** there is exactly **one** predicate for "what is true now" —
`Ledger.active()` = not-superseded **AND** in-validity — and every truth-serving read
(`current`, `search`, the resolved-head cache, `hidden_nos`) routes through it. Nothing
is deleted to forget it: a `valid_to` closure is an **appended retirement record**, so a
retired entry drops out of `active()` yet stays whole in `lineage()`/`as_of()`. `active()`
is **now-only**; historical reconstruction has one home, `as_of(t)`.

**Triangulation:**
1. The plan stress-test (flaw #4): two rival current-truth predicates let a validity-
   retired sapling leak through one read path but not another.
2. D2 (append-only, supersession-not-deletion): forgetting must not become deletion —
   a retirement is just another appended fact.
3. The Phase-2 adversary (confirmed MED): an `at`-parameterised `active()` mixed now-
   existence with past-validity and returned two live heads — so `at` was removed.

**Consequence:** `Ledger.active`/`retire`/`_valid_to_map`; `current()` delegates to it.

---

## D16 — Anti-fork on the question-key; a resolution inherits its question ✅ fresh

**Decision:** two live decisions may **never** answer the same question. The identity of
a question is a homoglyph- and case-folded **question_key**; `DecisionLog.record`
refuses a fresh Y/N that collides with a live head (route it through reopen+resolve),
and a `resolve()` **inherits the question_key it supersedes** so a reworded resolution
can neither drift to a new key nor collide with a *different* live head.

**Triangulation:**
1. The plan stress-test (flaw #1): `decide`'s "new node" path left the crux unenforced —
   the exact silent re-decide D-A forbids.
2. Alex's D-A ratification: "relearn = WALK re-inhabits; divergence records a new node,
   never a silent flip."
3. The Phase-2 adversary (confirmed HIGH + MED): a mismatched-subject `resolve` forked a
   different key, and glyphs outside the confusable table dodged folding — both closed.

**Consequence:** `decisions.question_key`, `record` guard, `resolve` key-inheritance,
`CollidingDecisionError`; pre-casefold + a broadened confusable floor.

---

## D17 — Workspace writes fold, they do not clobber ✅ fresh

**Decision:** overwriting a memory never loses the prior body. `Workspace.write`
archives the old content to `.history` and **supersedes** the prior ledger write, so
the overwritten version survives in lineage and only one active write exists per path.

**Triangulation:**
1. `docs/exploration/memory-as-navigation.md` §3.5: clobbering writes were a real bug —
   "fold, don't clobber."
2. D2: nothing the record holds is silently destroyed; a memory is no exception.
3. The Phase-2 adversary round explicitly probed content-loss on overwrite; the fold
   held.

**Consequence:** `Workspace.write` versioning + `.history`; `active("memory_write")`
serves one title per path.

---

## D18 — The reflection ritual is a verifier-gated producer ✅ fresh

**Decision:** once per cadence (**24h**, per Alex's D-B), the agent writes an append-only
`reflection_log` that **cites clickable real events**, passes the **synthesis gate** and
the **dread-lint**, and snapshots an honest self-image series. Any self-change is staged
as a **verified proposal** wired to the verifier panel — it cannot take effect unless an
*independent* verifier confirms it, and the ritual can never self-certify.

**Triangulation:**
1. The plan stress-test (flaw #3): the reflection UI had no data producer — it would
   have been a mock; D18 builds the producer so Phase 3 is a pure view over real data.
2. D4 (maker ≠ verifier) + the standing "no dream subagents" refusal: an ungated self-
   writing loop is memory without verification, the cardinal sin.
3. The reflection portal vision (`docs/ROADMAP-UI-SPINE.md`): a grounded daily self-
   image, self-change as a *proposal* the human ratifies — never an autonomous edit.

**Consequence:** `trellis/reflect.py` (`ReflectionRitual`, `SelfChange`,
`self_image_stats`); the Reflection page reads it; `web.growth_stats` delegates to the
core so glyph and ritual agree.

---

## D19 — Ingestion is idempotent by identity + content-hash + two-phase markers ✅ fresh

**Decision:** the contemplating mind reads the team's record in (Atlas's Discord dumps +
transcripts, Whisper output, media) through an adapter layer that hands each item to a
harvester **exactly once**. Identity = `(source, channel, id, event_time)`, folding content
in only when there is no id; a separate content-hash distinguishes a **correction** from a
**duplicate**; `started`/`complete` markers make a crash mid-harvest **resumable**.

**Triangulation:**
1. Alex, 2026-07-17: "read the dumps, fetch the gaps… keep our own markers as our truth."
2. The plan stress-test (5 determinism findings): `message_id=""` collapsed id-less
   messages; append-only markers couldn't record partial progress; a corrected re-dump
   looked like a duplicate — all closed here.
3. D2 (append-only): coverage is *our* ledger, not Atlas's `state/` — what WE understood,
   not what Atlas indexed.

**Consequence:** `trellis/sources.py` (`Ingestor`, `RawItem`, `Provenance`). Single-writer
(a personal agent) makes last-complete-wins dedup sufficient.

---

## D20 — An observed decision is TWO linked nodes: the room's, and the agent's ✅ fresh

**Decision:** each decision found in a transcript is recorded as an **observation**
(attributed to the room, confidence-tagged, `transcript_fallible`) **and** an **opinion**
(the agent's own Y/N/T), joined by an `opinion_of` edge. They carry **distinct, stable
identities** (`obs:<id>` / `op:<id>` keyed off source+moment+participants, via
`Decision.effective_key()`), so the anti-fork guard never refuses the pair and re-reading
the same meeting **folds** instead of forking.

**Triangulation:**
1. Alex, 2026-07-17 (D-choice): "both, as two linked nodes."
2. D12 (contextual understanding *and* principled opinion): the agent must be able to hold
   *what the room decided* separate from *what it thinks about it* — never confuse them.
3. The plan + code stress-tests: keying off the free-text subject forked on any rewording;
   the pair would collide on one `question_key` — both fixed by the stable namespaced key.

**Consequence:** `trellis/observe.py`; `Decision` gains `key / attributed_to / confidence /
provenance / opinion_of`. Confidence-aware confirmation (finder ≠ confirmer); provenance
propagates by FLOOR + OR so a confident read can't be built from shaky inputs.

---

## D21 — The vault is the ledger's reconciled face, not a second brain ✅ fresh

**Decision:** the Obsidian vault **is** the memory-as-navigation `Workspace` (markdown =
content, git-versioned), and the ledger is the append-only event index over it, storing a
**content hash** per write. Their divergence is **detectable and healed**: a human's Obsidian
edit is folded in as an *attributed* write; status/frontmatter is computed **live** from the
ledger (never a frozen id); what can't be healed is **surfaced**, not papered over.

**Triangulation:**
1. Alex, 2026-07-17: "make it an Obsidian vault… it all loops back into the UI."
2. The plan stress-test: v1's "reconstructable from the ledger alone" was false — the ledger
   stored a byte-count; retirement never touched the files. Both corrected.
3. D5 (memory beside the agent, in files) + D2 (append-only): the vault is beside the agent
   and human-editable; the ledger keeps the lineage honest.

**Consequence:** `trellis/vault.py` (`VaultReconciler`, `note_state`, `render_frontmatter`);
`memory.py` records a content hash.

---

## D22 — Curiosity has teeth: a dry seek is not understanding ✅ fresh

**Decision:** open questions are **first-class nodes** targeting a named assumption, with an
owner and a **revisit** — so an untouched question surfaces on the same "unresolved-T-is-a-
hidden-no" staleness rail. A seek that moves nothing is a **dry** seek that does **not**
advance the question; a `dry_streak` escalates to a human. A question can be **closed as
understood only with evidence that POSTDATES it** — "I searched" is structurally not "I
understand."

**Triangulation:**
1. Alex, 2026-07-17: autonomy is "persistent understanding, not making one search and using
   it as an excuse to say I did my job."
2. The plan stress-test (its strongest finding): "two questions a day" *was* the checkmark it
   claimed to abolish — no staleness rail, no anti-fork, no map-moved gate.
3. D12 + the mortality posture: the job is understanding, not task-closure; the loop must
   end on named assumptions and unknowns, not a green check.

**Consequence:** `trellis/curiosity.py` (`QuestionLog`, `Question`, `assumption_key`,
`NotResolvedError`); surfaced on the Assumptions & Curiosities page.

---

## D23 — The agent proposes its own repair; it never applies it ✅ fresh

**Decision:** the self-improvement engine lets the agent **continuously propose** changes
to itself — a burn to record in the friction register, a process to change, a skill to
adopt or retire — but a proposal **cannot take effect** without (a) an *independent*
verified verdict on the record (maker ≠ verifier) **and** (b) a *human's* ratification.
The agent's capabilities are a navigable **skill estate** (00-grade titles, anti-forked on
a `capability_key`), so "is there already a skill for this?" dedups before a duplicate is
minted. Adopting a skill from an **untrusted source** (e.g. a video) is a **default-N**
decision that must state its supply-chain reasoning — the human installs, the agent never
auto-installs. "Recursively improve itself all the time" means *think about it always,
change yourself never without the two gates*.

**Triangulation:**
1. Alex, 2026-07-20 (the commission): *"infrastructure and a process for the agent to
   constantly think about ways to improve itself … Could this be a skill? Is there already
   a skill? Where did I get confused today? … Recursively improve itself all the time."*
2. D18 (the reflection ritual is a verifier-gated producer): the engine **reuses** that
   exact safety core — `apply`-behind-an-independent-verdict — so it adds no new authority
   for the agent over itself; it can be no more dangerous than `reflect.apply_self_change`,
   which rounds 6 already hardened.
3. W1 (no skill marketplace / no auto-installed skills) + Brett 2026-07-11 (*"don't trust
   AI to write skills"*) + the OpenClaw supply-chain record (824 malicious skills): an
   external skill:add is structurally a default-N with a forced "why," never a fetch-and-run.
4. D4 (maker ≠ verifier) + the ASCII-identity allowlist hardened 2026-07-17: the proposal's
   evidence is confirmed by a checker that is not the maker, and self/​homoglyph ratification
   is refused — the human seat holds on the improvement surface too.

**Consequence:** `trellis/selfimprove.py` (`SkillEstate`, `ImprovementProposal`,
`ImprovementEngine`). `can_take_effect()` re-derives both gates from the append-only record,
never from a proposal's own flag. Plan: `docs/PLAN-self-improvement-engine.md` (Phase 1
built; confusion harvest, the improvement-curiosity loop, and the portal surface follow).

---

## D24 — The opinion is formed over a compiled, reloaded context — not the batch alone ✅ fresh

**Decision:** before the Witness forms an opinion, a **deterministic context compiler**
reconstructs the longitudinal state the doctrine assumes: it **reloads the prior read**,
pulls the active decisions whose question touches the current subjects, surfaces the **full**
open obligations (hidden nos, reopened heads, stale curiosities) and recent corrections and
verifications — and emits a **ContextManifest** recording exactly what was included and why,
and what was excluded and why (privacy / budget / irrelevance). The compiled packet rides the
**user message** (per-cycle context, with the events); the standing prompt stays the doctrine.
The model interprets a prepared packet; it no longer has to guess which history it should have
remembered.

**Triangulation:**
1. Codex context-engineering audit, 2026-07-20 (`docs/audits/CONTEXT-ENGINEERING-AUDIT-2026-07-20.md`):
   the default Witness *"does not reload its previous read, prior decisions, hidden-no subjects,
   or pass contents"* — it writes `current-read.md` and never reads it back, so the loop was a
   grounded current-batch pass, not the longitudinal witness the doctrine describes. The named
   fix is a *"deterministic, inspectable context compiler"* with a `ContextManifest`.
2. D12 (contextual understanding, not completion) + D14 (memory is navigation): the read is the
   product; an opinion formed without reloading it is the anti-example. The compiler reloads the
   map before the model walks.
3. D5/D2 (memory beside the agent, append-only): the compiler reads the ledger + vault, invents
   nothing, and records the manifest as another attributed, bitemporal entry — so *what the model
   saw* is itself on the record and auditable.

**Consequence:** `trellis/context.py` (`ContextCompiler`, `ContextManifest`, `CompiledContext`),
wired into `agent.Witness._resolve`; a `context_manifest` entry is recorded per cycle. Honest
scope: this closes the load-bearing gap (opinion over reloaded state, auditable packet). It does
**not** yet implement the audit's full epistemic-type lattice, the separate read-delta output
schema, or the 12 gold-scenario eval program — those are the next steps, named in the audit.

---

## D25 — A verification pass means the OUTCOME held, not that a file exists ✅ fresh

**Decision:** the deterministic verifier distinguishes **preconditions** from an **outcome**.
Confirming that a file is present, a ledger id resolves, or an output is non-blank is
`PRECONDITIONS_PASSED` — "the evidence is well-formed and openable" — **not** `VERIFIED`.
`VERIFIED` is earned only when an **outcome predicate** (`expect_hash` / `expect_contains`
/ `expect_kind`) was actually checked and held. An unopenable **external-only** claim is
`INSUFFICIENT`, never verified. Trust counts only true verifications; `preconditions_passed`
never inflates the ratio or the glyph's warmth.

**Triangulation:**
1. Codex infrastructure audit, Critical 4 (`docs/audits/AUDIT-2026-07-20.md`): `RuleVerifier`
   *"verifies files by existence, not content… a claim supported only by `opaque://uncheckable`
   received VERIFIED"* — the intended INSUFFICIENT branch was unreachable, and trust compounded
   on artifact existence. The prescribed fix: rename the deterministic result so it cannot read
   as semantic truth, add evidence resolvers that check content, and separate validation from
   verdict.
2. D4 (maker ≠ verifier) + the acceptance doctrine ("overconfidence on thin/stale info" is
   unforgivable): a checker that passes on existence is exactly the "it works it works" the
   harness exists to refuse — one layer deeper.
3. D2 (append-only, attributed): the new status is recorded like any other verdict; the record
   stays the authority (`reflect.apply_self_change` / `selfimprove.can_take_effect` re-derive a
   genuine VERIFIED, now earned by an outcome predicate, not by an id that merely exists).

**Consequence:** `trellis/verify.py` — `VerdictStatus.PRECONDITIONS_PASSED`, `Evidence`
outcome predicates, external-only → INSUFFICIENT, honest `trust_record`; `reflect`/`selfimprove`
attach an `expect_kind` predicate so a self-change earns a real VERIFIED (strictly more than "the
id exists"); the glyph's trust reflects outcome-verification. Honest scope: full evidence
provenance (origin/signatures/tenant), reproducible command/exit predicates, and
trust-by-consequence are the larger evidence-resolver program Codex names — the next steps.
Plan: `docs/PLAN-evidence-aware-verification.md`.

---

## D26 — The outbox is durable and idempotent: refusal #5 survives a crash ✅ fresh

**Decision:** the outbox's source of truth is the **ledger**, not an in-memory dict. Every
transition (stage / approve / deny / **firing** / fired / **unknown** / reconciled) is an
appended event carrying the **full payload**, so a fresh process — and the web UI, and the
executor — all reconstruct the same state. `fire()` is **idempotent**: it records a `firing`
intent *before* calling the world and refuses to re-fire an action already firing/fired, so a
crash-then-retry can never double-send. An ambiguous executor outcome lands **`unknown`** (the
remote may have received it), never `approved`; only a human `reconcile()` resolves it — `fired`
(it went out, don't resend) or `approved` (it didn't, one clean retry). Refusal #5 now holds
across a restart, not just within one process.

**Triangulation:**
1. Codex infrastructure audit, Critical 3 (`docs/audits/AUDIT-2026-07-20.md`): the outbox kept
   actions in an in-memory dict, the ledger held only a 280-char preview, and `fire()` called the
   executor *then* recorded fired — so a web approval was split-brain from the executor, a restart
   lost the payload, and a retry double-sent. Prescription: an event-sourced durable outbox with
   full payload, a compare-and-swap state machine, an idempotency key, and an UNKNOWN/reconcile
   state.
2. D10 (stage, don't fire) + the strongest cross-voice consensus in the dossier (never let output
   hit a stakeholder unchecked): "nothing fires without your yes" is hollow if a crash resends it
   or a restart forgets the yes. Durability is what makes the refusal true in the failure domain
   that matters.
3. D2 (append-only, attributed, bitemporal) + the web self-approval fix (2026-07-17): the ledger
   was already the record the web writes; D26 makes the outbox *read* it, closing the split-brain
   the earlier fix half-addressed.

**Consequence:** `trellis/stage.py` — `Outbox._load()` rebuilds from the ledger; `fire()` records a
`firing` intent, is idempotency-guarded (`_fire_block`), and lands `UNKNOWN` + raises
`FireOutcomeUnknown` on an ambiguous executor; `reconcile()` is the human seat for an unknown.
**Honest boundary:** true end-to-end exactly-once depends on the destination honouring the
idempotency key; when it doesn't, trellis guarantees fire-at-most-once and surfaces `unknown` for a
human — it cannot make a remote service deduplicate. Plan: `docs/PLAN-durable-outbox.md`.

---

## D27 — Reads are cached, rebuildable from the file — the record compounds without slowing ✅ fresh

**Decision:** the ledger keeps a **rebuildable in-memory read cache** so it parses each JSONL
line **exactly once** instead of re-parsing the whole file on every `entries()` call. The cache
is keyed on a **byte offset**: a read syncs only the bytes appended since last time. The **file
remains the sole source of truth** — the cache is reconstructable at any moment, a file
shrink/rewrite triggers a full rebuild, and a corrupt line still raises without leaving a
half-synced cache. Append-only, bitemporal, and greppable are all untouched; the file format is
unchanged.

**Triangulation:**
1. My own §5 audit (2026-07-17) + Codex High 6: `entries()` re-parsed the whole file on every
   call, so any read-per-write pattern (`DecisionLog.record` → `active()` → `entries()`) was O(n)
   per op and O(n²) as the record grows — the *opposite* of the "compounds over time" thesis
   (`WHAT-THIS-IS.md`). Measured: building 10k decisions took ~230s; `entries()` ~44ms at 10k.
2. D2 (append-only, the file is the truth): the cache must never become a second source of
   truth — hence rebuildable-from-the-file, offset-synced, shrink-detecting. An index that can
   drift is refused.
3. The concurrency stress (8 threads × one shared `Ledger`): the cache is guarded by a reentrant
   lock and only parses COMPLETE lines, so concurrent appends lose nothing and a reader never
   sees a torn write.

**Consequence:** `trellis/ledger.py` — `_sync_locked()` + a byte offset + an `RLock`; `entries()`
returns a fresh list off the cache; `append()` only writes (the file stays truth). A cheap stat
signature `((inode, device), mtime_ns)` forces a full rebuild on any out-of-band edit that could
violate "bytes below the offset are immutable" — a **replacement** (new inode, as git / rsync /
atomic write-and-rename produce — the README advertises syncing over git/a shared drive), a
**shrink**, or a **same-size in-place rewrite** (mtime advanced). **Measured after:** 10k build
230s → **~10s**; `entries()` 44ms → **~0.03ms**; `active()` 44ms → **~0.9ms**. Honest scope: two
residuals, both narrow and documented — a same-inode *grow-in-place* rewrite that changes lower
bytes (which no append-only or sync/replace workflow performs) is not caught; and the remaining
O(n) *filter* in `active()`/`active_head` (no longer a re-parse) is fine for the daily workload
(append a few/day, read often), with an incremental question-key→head index the next step. An
independent verifier confirmed coherence under append-only/multi-instance/concurrency/corrupt/
shrink and pinned the replacement + same-size-rewrite cases now closed. Tests: `test_ledger_cache.py`.

---

## D28 — Authority is an authenticated principal, derived server-side, never a form field ✅ fresh

**Decision:** the human seat is filled by an **authenticated `Principal`**, not a caller-supplied
string. An `authenticated` Principal can only be minted by `auth.Authenticator` after verifying a
secret; the web derives the approver from a **signed, expiring session cookie**, never from a form
field. Approvals, denials, and affirmations read the identity from the verified session — a caller
can no longer POST `human=alex` to satisfy the gate. Right-sized for the deployment (a personal
agent on your machine): one shared secret — set `TRELLIS_APPROVER_SECRET` + `TRELLIS_HUMAN`, or the
server mints an **ephemeral login token and prints it once to the console you launched** (only
someone with that terminal can log in). A multi-user deployment swaps the `Authenticator` for real
accounts / OIDC behind the same `Principal` seam.

**Triangulation:**
1. Codex infrastructure audit, Critical 1 (`docs/audits/AUDIT-2026-07-20.md`): *"authority is a
   string, not an authenticated principal — the web routes accept the human name from an HTML form;
   there is no authentication… an agent or HTTP caller can say it is 'alex' and satisfy the gate."*
   The prescription: a `Principal`/`ActorContext` created only by a trusted boundary; web identity
   from an authenticated session, never a form field.
2. Refusal #5 (D10, D26) + the web self-approval / homoglyph fixes (2026-07-17): those closed
   *disguise* (spelling, homoglyph) but not *impersonation* — the form field was still trusted. D28
   closes impersonation: the id is server-verified before it reaches the independence guard.
3. D11 (small core, zero-dependency; the web is an optional extra): `auth.py` is stdlib-only (hmac
   / secrets / base64); the session is a tamper-evident HMAC, no session store to stand up.

**Consequence:** `trellis/auth.py` (`Principal`, `Authenticator` — authenticate, issue/verify
signed sessions); `web/app.py` gains `/login` + `/logout`, a `_principal(request)` reader, and
`_require_human(request)` (401 without a valid session); the approve/deny/affirm forms drop the
"your name" field. Honest scope: this is single-user shared-secret auth over a local session —
appropriate for the personal deployment, and it is the *seam*, not the ceiling; CSRF tokens and
real accounts are the next step for a multi-user server. Tests: `test_auth.py`, `test_web_auth.py`.

---

## D29 — The self-image is an abstract instrument, not a face ✅ fresh

**Decision:** the agent's self-image renders as an **abstract instrument of the record** —
concentric growth rings (age), a filled arc **gauge** (verification pass-rate), tick-segments
(bodies of work checked), memory nodes, outward notches (unresolved triangulations), and a hue
(trust). It has **no face** — no eyes, no mouth, no creature. The earlier glyph drew a creature
with eyes and a mouth that **smiled when trusted and went flat when unproven**; that was
embodiment and *performed emotion* — the very thing D3 (no soul) and the embodiment linter
refuse, leaking back in through the picture. A deterministic smile is still a smile. Every mark
remains a pure function of a real ledger number (same record → same image); only the
anthropomorphic *form* is removed.

**Triangulation:**
1. Alex, 2026-07-21: *"Is it still showing an alien face for the reflection? That would be
   incorrect."* — the correction, in his words.
2. D3 (no soul.md; identity is an EMP, not a persona) + `emp.py`'s embodiment linter ("I can
   see / my eyes / I feel"): a self-image that *emotes* is the same violation one layer over, in
   pixels. The dread-lint reasoning applied to the self-portrait ("not what I feel like today")
   was left incomplete — it corrected the animation but kept the emoting creature underneath.
3. The founding brief's whole thesis (the agent is a trellis, not a plant; honest anatomy, never
   performed feeling): a mascot with a data-driven smile is a mascot. The instrument is the
   honest form.

**Consequence:** `web/glyph.py` rewritten (`render_glyph` = the abstract instrument; `reflection`
caption describes marks, not features); `web/selfportrait.py` layers the instrument (the morph
and growth strip are unchanged in mechanism); README + VISUAL-TOUR text and assets regenerated
(the four state images are abstract SVGs, the old face PNGs removed). Determinism, the
same-record-same-image guarantee, and every stat→mark mapping are preserved — only the face is gone.

---

## D30 — trellis is isolated from the other agents by identity + allowlist ✅ fresh

**Decision:** in a many-agent estate sharing a server-wide bridge, trellis touches only its
**own** surfaces, enforced **structurally**, not by convention. trellis authenticates as its
**own identity** (its own credentials, referenced by env-var name — the secret is never stored,
logged, or laddered onto another agent's) and may only read from / act on an **explicit
allowlist** of surface ids. READ and ACT are **separate** allowlists (it may watch a channel it
must never post into). A shared bridge's other-agent traffic is dropped on read (`filter_readable`)
and refused on act (`guard_act` raises — sending to the wrong place is irreversible). The empty
allowlist is the default, so an unconfigured trellis is **inert, not omnivorous**.

**Triangulation:**
1. Alex, 2026-07-21: chose "own identity + allowlist (physical isolation)", scoped to trellis
   only, when asked how to separate trellis from the many other agents on his system.
2. `surfaces.py` D7 ("privacy lives in the key"; the injective `storage_key`) + the recorded leak
   it answers (*"our agents are leaking private chief discussions into other channels… stop
   that"*): isolation belongs in structure, not filter-discipline. The new `agent`-scoped gate is
   the outer layer of the same principle; `storage_key` already namespaces the ledger by agent.
3. Verified estate reality (2026-07-21): ~25+ agent dirs on the machine, several with their own
   gateways; the reachable bridge is server-wide (sees `#vex-atlas-work`, `#daedalus`, …). Filter
   discipline on a shared identity would let a bug reach another agent's channel — credential
   scoping cannot.

**Consequence:** new `trellis/isolation.py` (`AgentIdentity`, `SurfaceAllowlist`, `Isolation`,
`ingest_scoped_discord`) + `tests/test_isolation.py` (10 tests, incl. the money test: a mixed
server-wide batch lands only trellis's channel, stamped `agent="trellis"`; the other agent's
message never reaches the ledger). This is the OUTER gate; it composes with surfaces.py's inner
flow rules. **Seam remaining (gated, human-owned):** the live Discord/Drive fetchers + the send
executor are not built — they need a trellis-owned bot Alex creates and the allowlist ids, and
the executor stays behind an explicit human "arm it" (W3 still stands).

---

## D31 — Live Discord rides the idempotent Ingestor, not the raw append path ✅ fresh

**Decision:** a live Discord message enters through a `DiscordMessage → RawItem` bridge into
`sources.Ingestor` (D19: identity-key dedup, content-hash corrections, two-phase markers), NOT
through the dedup-less `ingest_discord`. `item_id = message_id`; the `ConversationKey` and the
D30 allowlist are carried through the bridge. One idempotency contract, one provenance model.

**Triangulation:**
1. Alex, 2026-07-21: ratified option A ("bridge Discord onto the Ingestor").
2. The audit repro: the documented setup wired the poller to `ingest_scoped_discord`, so poll #2
   double-wrote every message and `position_history` rendered a false "view shifted" — the record
   getting *less* trustworthy the longer it runs, the thesis inverted (Fable audit R1).
3. D19 (idempotent by identity + markers) was ratified for Atlas dumps; this extends it to the
   live surface rather than duplicating the machinery.

**Consequence (Phase 2 build):** the bridge + allowlist threading; a re-poll-is-a-noop
regression on the Discord path. Resolves the D19-vs-SETUP contradiction the audit flagged.

---

## D32 — Channel implies its threads; DMs are IN, scoped and session-tracked ✅ fresh

**Decision:** an allowlisted channel implies its threads (a threaded message is readable if its
`parent_channel` is allowlisted; dropped messages are counted, never silently discarded). **DMs
ARE admitted** — but a DM stays private to the human it is with; it never flows to a channel.
This requires a **session-tracking** layer: a stable capture of **username + a stable ID + the
per-conversation thread**, so DM conversations are individuated and legible. It must be visible
in the portal (a session log: "these are the DM sessions, this is who, this is what was said").

**Triangulation:**
1. Alex, 2026-07-21: ratified channel⇒threads (A); overrode "DMs out for v1" — DMs are in, but
   "they stay private to whoever the DM is speaking with… a saving process of Username, ID, and
   tracking of those conversations… if this is not in the UI (session tracking) it needs to be."
2. The audit: threaded messages were silently dropped (dynamic thread ids, no parent fallback)
   and DM `ConversationKey.human` split one conversation per speaker (Fable G4/G11); this decision
   closes both, and the stable-ID capture also fixes the "attribution has no stable identity" gap.
3. D7 privacy lattice (DM most-private): admitting DMs is safe only with the scoping + the
   cross-surface leak checkpoints of [[D36]].

**Consequence (Phase 2/3 build):** an identity registry (Discord user-id → canonical id), a
session model keyed on (agent, surface, human, thread) surfaced as a portal **session log**, the
parent-channel thread fallback, and a dropped-per-surface counter. *Open design to triangulate:
the exact session-tracking shape + UI — Alex called for it explicitly.*

---

## D33 — The agent may change its own mind; it logs it, and only sometimes escalates ✅ fresh

**Decision:** the Witness may revise its own opinion, reopen a question, reflect, and re-decide
**on its own authority** — every such change is a logged, visible supersession on the record (the
portal shows the change and its rationale), and an independent cheap verifier ([[D34]]) checks it.
A human is NOT in the loop for the agent thinking. Escalation to a human is the **exception**,
reserved for a defined high-stakes class (e.g. reversing something a human ratified/affirmed) and
for verifier **refutation** ([[D35]]). The Phase-1 collision fix (block + require a human reopen)
is an interim stopgap, NOT the design; the design is autonomous-supersede-with-log + machine
verification.

**Triangulation:**
1. Alex, 2026-07-21: "I don't want too much of a gating function… the beautiful thing about this
   agent is learning over time: the reasoning, the reflection, the tracking of decisions, the
   learning. I think it takes away from that if… all of those things are gated by a human… there
   are times when we should always log that [a changed mind]… times when maybe we need to
   escalate. There needs to be room for making decisions like that." Explicit caution against the
   audit-fix over-correcting into lost agency.
2. The audit found the agent could not legally change its mind at all (a repeat opinion crashed
   the driver; the supersession grammar had zero callers) — the failure this decision's build
   closes, on the agency-preserving side rather than the human-gated side.
3. D14 (memory is navigation: WALK/REOPEN/DECIDE) + D1 (the atomic record is the Y/N/T with
   lineage): reopening and superseding are first-class, recorded acts — that IS the learning.

**Consequence (Phase 2 build):** route opinion-recording through `Navigator.decide()` with
autonomous reopen+supersede, each logged and portal-visible and machine-verified; a named,
minimal high-stakes class that escalates to the human. Do NOT gate ordinary reasoning/revision.

---

## D34 — Same family, cheaper seat: Opus makes, Haiku verifies — and verifies broadly ✅ fresh

**Decision:** the verifier is a **separate, cheaper seat in the same family** — Opus-class maker,
Haiku-class verifier (`TRELLIS_VERIFIER_*`; the factory refuses loud if it equals the maker).
Verification is **broad, not high-stakes-only**: everything logged to memory — decision trees,
reflections, and load-bearing claims — is independently verified, because an unverified memory
error compounds (≈2%→4%→16%) and that quiet compounding is precisely how agents fail over time.
The verifier may independently reach for evidence the maker cannot. VERIFIED still requires a real
outcome predicate ([[D25]]); the model verifier refutes/confirms but never mints VERIFIED alone.

**Triangulation:**
1. Alex, 2026-07-21: "I don't think we need a whole new, different family… Haiku versus Opus… is
   fine. Verification needs to happen when we're logging decision trees and when we're logging
   reflections… the 2% once it happens compounds… when memory is logged incorrectly. It is very
   important to verify everything… this is why agents fail over time." Ratified separate-but-cheap,
   same family.
2. D4 (maker≠verifier) + D18 (the reflection ritual is verifier-gated): this seats the long-empty
   verifier and points it at the memory-write path, where the compounding risk lives.
3. The audit: the verifier seat was instantiated nowhere; the one live verdict was self-signed
   (Fable G5) — broad independent verification is the direct countermeasure.

**Consequence (Phase 4 build):** the verifier seat in `factory.py`; the Haiku panel convened on
every decision-tree and reflection write plus flagged claims; provider/model fingerprint recorded
in each verdict so independence is auditable.

---

## D35 — REFUTED pauses and escalates; INSUFFICIENT flags; one trust number ✅ fresh

**Decision:** a REFUTED verdict marks its decision/read **contested** (an appended contest event,
never a deletion), removes it from the trusted read the next cycle compiles, and escalates to the
human via the portal. A persistent INSUFFICIENT is recorded as a capability gap, not a silent
pass. Both feed the confusion-harvest ("burns") that rides the next prompt. Trust is computed by
**one canonical function** (`verify.trust_record`) that every surface delegates to.

**Triangulation:**
1. Alex, 2026-07-21: ratified the recommendation as written.
2. The audit: verdicts gated nothing (a REFUTED claim left the decision active), and four
   divergent trust formulas disagreed across pages (Fable G6/G8); the Phase-1 work already
   collapsed the web displays onto `verify.trust_record`.
3. D25 (outcome-not-existence) + [[D34]]: a refutation must *do* something for independent
   verification to earn trust — consistent with [[D33]] because the verifier is a machine gate,
   not a human one; only refutation and a named high-stakes class reach the human.

**Consequence (Phase 4 build):** the contested-state transition + portal escalation rail; harvest
wired to REFUTED/INSUFFICIENT; all trust reads routed through the one function.

---

## D36 — Everything is recorded within sessions; privacy is transparency + DM-scoping ✅ fresh

**Decision:** the operating principle is **transparency**: everything is recorded within
sessions, there is a legible **session log** (DM sessions individuated and understood as such),
and anyone who speaks to the trellis agent should know they are being recorded. The owner simply
does not discuss, with their agent, what they do not want on the record — this is a **personal**
agent that *interacts with* a team, not a team-wide shared one. Enforcement stays lightweight and
is not heavy code-level lockdown; the one hard rule is **DM-scoping**: a DM's content never
crosses to a channel (the cross-surface leak checkpoints of the privacy lattice apply there).

**Triangulation:**
1. Alex, 2026-07-21: "all of this gets saved within sessions… a log of sessions… anyone who
   speaks to your trellis agent should know that that is being recorded. I don't want this in the
   code itself, but… it's all being recorded. The person that owns that trellis agent shouldn't
   have a conversation about personal things if you don't want to record it… for personal use…
   but it will be interacting with the team."
2. D7 (privacy lives in the key) + [[D32]] (DMs in, scoped): the leak checkpoints exist to keep a
   DM out of a channel; beyond that, the posture is recorded-and-legible, not paranoid.
3. The audit: `can_flow`/`guard_flow` had zero callers (Fable G7) — wiring the DM→channel
   checkpoint is the one privacy build that matters here.

**Consequence (Phase 2/3 build):** scope recorded on writes so a DM cannot compile into a channel
packet or a channel post; the session log as the transparency surface; a stated recording notice.
No heavy per-item gating.

---

## D37 — Always-on with the machine, not a server daemon ✅ fresh

**Decision:** trellis runs as a **local, always-on process tied to the owner's machine** — on
while the computer is on, off when it is off — not a hosted server or a heavyweight daemon. A tick
runs the due schedules (witness cycle, reflection, harvest) on a cadence; the spend cap is derived
from ledger charge records (so it survives a restart); a health alert about the harness itself may
bypass stage-don't-fire (it is the harness speaking, not the agent acting).

**Triangulation:**
1. Alex, 2026-07-21: "I don't [think] there necessarily needs to be a major daemon… trellis has a
   current system where it's not a server, but it's always on… as long as my computer is on. If my
   computer turns off, then trellis turns off." Ratified the runner recommendation, local flavor.
2. D6 (time injected; scheduling is the deployment's choice) + the audit's scheduler-as-ledger-
   state: registration and firings are ledger events, so a fresh process reconstructs state.
3. The audit: no runner exists and `Budget` had no reset window (the "$300 in two days" risk) —
   the ledger-derived cap is the countermeasure.

**Consequence (Phase 3 build):** a `trellis run` login-scoped always-on process (a launchd/login
item), the tick, the windowed ledger-derived budget, orphan-start health detection surfaced in the
portal.

---

## D38 — Ship everything now to a personal Discord; no staged read-only rollout ✅ fresh

**Decision:** this is not a cautious multi-week rollout. Build the full feature set — threads,
DMs, the model on, the send executor — and turn it on **immediately on a personal (private)
Discord server** to test end to end. It is not a public release. The staged read-only → model-on
→ acting sequence is dropped. **(Scope note: this sets the launch *posture*; it does not by itself
rescind refusal #5 / W3 — outbound sends remain human-approved (stage-don't-fire) until that is
explicitly ratified. See "flag" below.)**

**Triangulation:**
1. Alex, 2026-07-21: "you're running this like it's the past. It is an agent-forward world. We put
   this out immediately with everything available to it. We allow threads, we allow DMs, and we
   just build everything. We're testing the Discord… released to a personal Discord server… we
   might as well put everything in it… don't have to worry about… formal launch posture."
2. The Phase-1 hardening (439 tests, 10/10 stress, the ledger/outbox/identity/verifier holes
   closed) is what makes "ship everything at once" not reckless — the safety floor exists even
   without a slow rollout to catch issues.
3. D30 sequencing deferred the executor behind boring verified weeks; this decision overrides that
   sequencing for a *private* server, where the blast radius is the owner's own community.

**Consequence:** the phase plan collapses — build ingestion, the agency-preserving mind-change,
broad verification, the runner, and the executor toward one private-server launch.

**Flag RESOLVED (Alex, 2026-07-21):** the agent does **not** auto-post — *every* outbound stays
staged for the owner's yes (refusal #5 / W3 stand fully, even for DM self-updates). The one change
is the **approval surface**: the yes now happens **in Discord** (a reaction/command on the staged
proposal), not only in the web portal — "most of the interaction is going to be in Discord, so it
should go in Discord." The executor is still built so it *can* post; it simply never fires without
the Discord yes. Consequence: build a Discord approval gesture (reaction/command → the same
authenticated, maker≠approver, lifecycle-gated `Outbox.approve/fire` path the portal uses).

---

## D39 — Subscription seats run uncapped; a dollar budget only fits metered seats ✅ fresh

**Decision:** the daily dollar budget applies only to **per-token** seats (API keys). A
**subscription** seat — `codex` (ChatGPT login), or `claude` running on the Max login
rather than an API key — runs with **no daily cap by default**: a dollar ceiling over a
flat subscription is a fiction, and enforcing one would only fabricate spend records.
Explicit settings still win both ways: `TRELLIS_DAILY_BUDGET=<number>` caps any seat,
`off` disables the cap on a metered seat. The metered default stays the conservative
$5/day ("$300 in two days" is what an unbounded metered agent does).

**Triangulation:**
1. Alex, 2026-07-22 (the onboarding wiring): "There should be no daily budget because
   we log in using max or codex accounts."
2. The Fable onboarding build's finding (docs/ONBOARDING-NOTES-FROM-FABLE.md (a)1):
   nothing ever called `DayBudget.charge()`, so the cap was already gating a sum that
   stayed zero — on subscription seats the honest fix is no cap, not fake charges.
3. D37 (the ledger-derived windowed budget) is unchanged for metered seats — the
   mechanism stays; only its applicability is scoped to where dollars actually meter.

**Consequence:** `runner.budget_from_env` returns None for subscription seats (and for
an explicit `off`); `tests/test_read_scope_and_budget.py` pins all six cases. The
remaining gap — metered seats still have no `charge()` callers — stays open (see the
notes file's D-proposals).

---

## D40 — The read scope is what trellis's own bot can see, granted in Discord ✅ fresh

**Decision:** with `TRELLIS_DISCORD_GUILD` set (and `TRELLIS_READ_SURFACES` unset or
`auto`), trellis reads **everything its own bot identity can see in that server** —
every public channel, plus every private channel the bot is invited into. The grant
lives where the surfaces live: adding/removing the bot from a channel **in Discord is
the allowlist edit**; no hand-typed id list to drift. Structurally D30 is unchanged —
a startup discovery sweep derives the id list (probing each channel; a refusal is
recorded as `no_access`, never silently retried), lands the result on the ledger as a
`surface_discovery` event, and the discovered ids become the `Isolation` allowlist that
every downstream gate already enforces. An explicit `TRELLIS_READ_SURFACES` list still
wins when given.

**Triangulation:**
1. Alex, 2026-07-22: "trellis should be able to read … everything that's public or
   everything that it's part of." The bot's own channel visibility is exactly that set.
2. D30's principle (isolation by identity + allowlist) is preserved: the allowlist is
   still explicit in the running process; only its SOURCE moved from .env to Discord's
   own permission grants — which the human already controls channel-by-channel.
3. D38 (private-server launch): on the owner's own server, hand-listing channel ids was
   friction without safety — the bot's invite list is the same human gate, kept current.

**Consequence:** `DiscordClient.list_guild_channels`,
`backfill.discover_guild_read_surfaces` (+ the `surface_discovery` ledger record),
`cli._discord_read_scope` wired into `trellis begin` and `trellis run`. DMs are NOT
covered by discovery (REST cannot enumerate DM channels) — DM ingestion still arrives
via the gateway/poll paths under D32's scoping.

---

## D52 — Recency-first acquisition: descend into history, curiosity steering ✅ fresh

**Decision:** a new instance does not inhale the whole archive before understanding
anything. Discord backfill starts at **today** (the newest page seeds the live poll's
cursor, so the present is owned immediately) and **descends into history in day-sized
slices** — roughly `TRELLIS_BACKFILL_DAYS` (default 1) per surface per pass — with
**curiosity-targeted deepening**: surfaces where OPEN questions' terms actually occur
are descended first, at double depth. Documents ingest **newest-first**, at most
`TRELLIS_DOCS_PER_PASS` (default 150) new items per pass; corrections are never
deferred; every deferral is reported, never silent. Reaching the beginning of a
surface's history is a recorded fact (`bottom` on its descent cursor). The old
oldest-first bulk walk remains available (`TRELLIS_BACKFILL=full`).

**Triangulation:**
1. Alex, 2026-07-22: "it should be focusing one day at a time and then figuring out
   where it needs to learn more… each day increasing the understanding of the most
   recent history, as opposed to trying to inhale the entirety of Discord."
2. D22/D14 (curiosity has teeth; memory is navigation — sparse maps, forced
   traversal): the open questions are exactly the map of where to dig; uniform bulk
   inhalation is the anti-pattern of forced traversal.
3. The comprehension-debt surface (2026-07-22 pacing work) made the failure visible:
   bulk acquisition drives the walked-vs-ingested ratio to near zero for hours —
   "ingested is not understood," structurally guaranteed by the old order.
4. Safe by construction: arrival order never matters downstream — the spine is
   idempotent and every reader sorts by event_time — so the direction change touches
   pacing, not correctness.

**Consequence:** `DiscordClient.fetch_messages(before=…)`, `backfill.RecencyBackfill`
(descent cursors as `discord_descent_cursor` events, bottom recorded, focus-first
ordering), `OnboardingRitual._paced_batch` (newest-first bounded docs) +
`_focus_channels` (open questions steer the crawl), CLI defaults to recency mode.
The already-swallowed first instance is unaffected; every future instance — including
the EoC deployment — starts useful within minutes.

---

## ⏳ Watch list (decisions deliberately NOT taken)

- **W1 — No skill marketplace / no auto-installed skills.** [OPENCLAW] supply-chain
  record (824+ malicious skills) + Brett's "don't trust AI to write skills" (07-11).
  Skills are local files reviewed by a human. Revisit when the team's verification
  stack matures.
- **W2 — No A2A protocol integration.** A2A v1.0 is enterprise interop; the team's
  real bus is Discord + files. Revisit if an external ally demands it. [FIELD]
- **W3 — No autonomous outbound.** Standing "proposed no" (Clare, 2026-06-16: "before
  we send swarms out into the internet"). Stage-don't-fire until the team ratifies
  otherwise. *Revisited and CONFIRMED-STANDING by [[D38]] (2026-07-21): the executor gets
  built and turned on for a private server, but every send stays staged for the owner's
  yes — Alex ratified full staging, no auto-post. The only change: the yes now happens in
  Discord (reaction/command), not just the web portal.*
- **W4 — Memory-on-agent (Clare's mount-everything direction) not adopted.** The
  Brett/Clare fork is live; trellis takes Brett's side (memories beside, agent dies)
  because [MEM]+[FIELD]+[AUDIT] all point that way — but the fork is named in the
  companion doc as an open team decision. If the team ratifies the other direction,
  D5 gets superseded, not edited.
