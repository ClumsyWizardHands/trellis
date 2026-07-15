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

## ⏳ Watch list (decisions deliberately NOT taken)

- **W1 — No skill marketplace / no auto-installed skills.** [OPENCLAW] supply-chain
  record (824+ malicious skills) + Brett's "don't trust AI to write skills" (07-11).
  Skills are local files reviewed by a human. Revisit when the team's verification
  stack matures.
- **W2 — No A2A protocol integration.** A2A v1.0 is enterprise interop; the team's
  real bus is Discord + files. Revisit if an external ally demands it. [FIELD]
- **W3 — No autonomous outbound.** Standing "proposed no" (Clare, 2026-06-16: "before
  we send swarms out into the internet"). Stage-don't-fire until the team ratifies
  otherwise.
- **W4 — Memory-on-agent (Clare's mount-everything direction) not adopted.** The
  Brett/Clare fork is live; trellis takes Brett's side (memories beside, agent dies)
  because [MEM]+[FIELD]+[AUDIT] all point that way — but the fork is named in the
  companion doc as an open team decision. If the team ratifies the other direction,
  D5 gets superseded, not edited.
