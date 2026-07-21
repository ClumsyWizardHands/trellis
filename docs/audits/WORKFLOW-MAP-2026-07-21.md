# Full-workflow map — is trellis wired to the world? (2026-07-21)

**Question asked:** stop auditing the portal in isolation; map the *full* workflow the
way it's meant to run — trellis operating over Discord and a Google/transcript corpus,
with the UI used only when a human needs to inspect or approve.

**Method.** Three read-only subagents mapped one leg each (ingest / core cycle /
act+approval+UI) against trellis's own code. Every claim below is cited to `file:line`.

**Correction (this doc was rewritten after a bad assumption).** An earlier draft wove in a
*separate, unrelated* agent that happens to live on the same machine and Discord, and
invented a "trellis sits under it / doctrine collision" story out of that agent's private
files. That relationship was never established and is removed. This audit is only about
trellis's own code and trellis's own intended surfaces. What surfaces trellis should actually
connect to is an open question for Alex (§5), not an assumption here.

---

## 1. Live surfaces are reachable — but that's a capability check, not trellis's feed

trellis is *designed* to run over Discord + a transcript/Drive corpus (`ingest.py`,
`sources.py`). I confirmed such surfaces are reachable from this environment at all:

- A **Discord bridge is reachable** (messages carry `{role, content, timestamp}`; can read
  and send). NB: the bridge available here belongs to a *different* agent — so it proves a
  live Discord surface is wireable, it is **not** evidence about what trellis should ingest.
- **Google Drive is reachable** — a real corpus of dated meeting-transcript / 1-1 markdown
  files exists. Again: reachable ≠ "this is trellis's source." That's Alex's call.

The audit below stands entirely on trellis's own code and does not depend on either surface.

---

## 2. trellis is wired to nothing

Every subsystem is real, typed, and unit-tested; **not one is connected to a live surface.**
Today it runs on `web/demo_seed.py` and test fixtures. `ingest.py` says so itself: *"No
network here… Wire it behind your existing Discord pipeline."* The verdict on all three legs
is the same — **SEAM**: the mechanism is present and correct, the wire to the world is absent.

---

## 3. The three legs

### INGEST — how the world gets into the ledger — **SEAM**

| Component | Verdict | Evidence |
|---|---|---|
| `DiscordMessage` (typed record) | REAL type | `ingest.py:46` |
| `ingest_discord()` (maps a caller-fed iterable; no fetch) | SEAM | `ingest.py:71`; docstring `:26` |
| `ingest_calendar()` / `CalendarEvent` | SEAM | `ingest.py:58,101` |
| `position_history()` (recall-with-provenance query) | REAL logic | `ingest.py:167` |
| `RawItem` (idempotent raw unit) | REAL type | `sources.py:42` |
| `SourceAdapter.discover()` Protocol | SEAM — **zero implementations** | `sources.py:109` |
| `Ingestor.ingest()` (idempotent/resumable engine) | REAL engine, SEAM feed | `sources.py:130` |
| `DecisionObserver.harvest()` — `detect`/`confirm` **default to no-ops** | REAL logic, **STUB inputs** | `observe.py:96`, defaults `:92` |
| Google Drive / transcript ingestion | **ABSENT** | (no file) |

What feeds ingestion today: `tests/*` and `web/demo_seed.py:127` (hardcoded `RawItem`s +
a `Candidate` dict). Nothing from outside.

### CORE — sense→resolve→act→verify→remember — **SEAM**

| Component | Verdict | Evidence |
|---|---|---|
| `Witness.witness_cycle` (the state machine) | REAL method, SEAM as a *running agent* | `agent.py:123` |
| `LoopRun` / `Budget` (bounded loops, typed outcomes) | REAL, live in cycle | `loops.py:121`, wired `agent.py:132` |
| `ContextCompiler` (reload-the-read) | REAL, live | `context.py:127`, `agent.py:208` |
| `RuleVerifier` (maker≠verifier, deterministic floor) | REAL, live, separate identity | `verify.py:144`, `agent.py:184` |
| `ModelVerifier` (the model-verifier seat) | SEAM — never instantiated live | `verify.py:253` |
| `Workspace` (memory-beside-agent) | REAL, live | `memory.py:134`, `agent.py:299` |
| `ReflectionRitual` (daily reflection + gated self-change) | SEAM — never called from cycle, never scheduled | `reflect.py:120` |
| `LedgerScheduler` / `serve()` (in-process ticker) | SEAM — **`serve()` has zero callers** | `scheduler.py:33,143` |
| `MockProvider` | REAL but demo-only — the *only* provider ever instantiated | `providers/mock.py` |
| `ClaudeSDKProvider` / `OpenAICompatProvider` | SEAM — instantiated **nowhere** | `claude_sdk.py:19`, `openai_compat.py:21` |

**No unattended loop exists.** No `__main__`, no `main()` in `trellis/`; `scheduler.serve()`
is called by nothing; the only console entry is `trellis-web` — a read-only viewer whose
sole `while True` polls the ledger *file size* for the browser and never touches `Witness`.
Left running, nothing senses, resolves, or reflects on its own.

### ACT + APPROVAL + UI — decision → real side effect — **SEAM**

| Component | Verdict | Evidence |
|---|---|---|
| `Outbox.stage()` / `StagedAction` (durable, full payload) | REAL | `stage.py:136,71` |
| `Outbox.approve()` / `deny()` (independence-gated) | REAL | `stage.py:184` |
| `Outbox.fire()` (idempotent, crash-safe state machine) | SEAM — calls a caller-supplied `executor(a)` | `stage.py:219,254` |
| `Authenticator` / `Principal` (HMAC session, const-time) | REAL | `auth.py:40` |
| Web `/approve` `/deny` (auth'd; write `approved` and **stop**) | REAL but dead-ends | `app.py:814`; docstring `:828` |
| `propose_outbound()` ("the only way a Witness touches the world: stage and wait") | REAL | `agent.py:308` |
| **`executor`** (the thing that calls Discord/Docs/email) | **ABSENT** | only a param name in `stage.py` |

**What happens when an approved action fires today: nothing reaches the world.** The web
writes a `status:"approved"` ledger event and stops (*"Firing the action itself is the
harness's job, not the UI's"* — `app.py:828`). `Outbox.fire()` is the only path to a side
effect, and **every caller of `.fire()` in the repo is a test** passing a toy
`executor=lambda a: sent.append(...)`. No loop in `agent.py`/`loops.py`/`scheduler.py`
calls it. The act path terminates at a ledger `approved` event.

**UI role — confirmed inspect/approve-only.** Every route but the write endpoints is a
read-only GET of ledger views; the only writes are human-initiated, authenticated
approvals/ratifications. The agent loop never calls into the web app; the Outbox
reconstructs purely from the ledger. **"The UI is not used unless a human needs to inspect
or approve" is CONFIRMED.**

---

## 4. The wiring gap — what would make trellis actually run

Four pieces. Each is small relative to what's already built; **no core mechanism is
missing — only assembly and the "on" switch.**

1. **Ingest poller (read-only).** A loop that reads a live Discord surface and maps each
   `{role, content, timestamp}` → `DiscordMessage(..., posted_at=<msg ts, never now()>, ...)`
   → the existing `ingest_discord(ledger, msgs)`. ~30 lines. No signature changes.
2. **Drive transcript adapter (read-only).** A class implementing the waiting Protocol
   `SourceAdapter.discover() -> Iterable[RawItem]` (`sources.py:109`) yielding
   `RawItem(kind="transcript", content=<body>, event_time=<parsed meeting date>, ...)` into
   `Ingestor(ledger).ingest(adapter.discover(), observer.harvest)`.
3. **Real decision-finder + provider daemon.** Replace the `detect`/`confirm` no-ops
   (`observe.py:92`) with a real model; add a `provider_from_env()` factory and a ~30-line
   `main()` that assembles `Witness` + `LedgerScheduler`, registers `witness_cycle` and
   `ReflectionRitual.run`, and calls `scheduler.serve()`.
4. **Executor + firing loop (SIDE-EFFECTING — human gate required, §6).** A function
   `executor(a: StagedAction)` dispatching on `a.kind` to real send APIs, plus one loop that
   picks up APPROVED-not-fired actions and calls the already-built `box.fire(action_id,
   executor)` (`stage.py:219`). `fire()` already stamps the idempotency key and routes
   ambiguous outcomes to human `reconcile()`.

Which surfaces (1) and (2) point at, and whether (3)/(4) are wanted at all, is §5.

---

## 5. Open questions for Alex (not assumptions)

1. **What are trellis's intended surfaces?** Its own Discord presence? A specific channel?
   A specific Drive folder of transcripts? The seams are surface-agnostic; the target is a
   product decision, not something to infer.
2. **Is trellis meant to run unattended at all yet, or stay a library + viewer** exercised by
   demos/tests until the surfaces are decided?
3. **Which model goes in the provider seat** for the real `detect`/`confirm` and the cycle.

---

## 6. Safe to build vs. gated

- **Safe (read-only):** the ingest poller, the Drive adapter, and the provider daemon read
  a surface and write only to trellis's own ledger — no outward side effect.
- **Gated:** the executor (4). The moment it exists and a loop calls `fire()`, an approved
  action sends a real message / writes a real Doc — an outward, irreversible effect that
  belongs behind an explicit "arm it" from Alex. Which is, fittingly, the exact
  stage-for-human refusal trellis was built to enforce.

---

## Bottom line

trellis is an **end-to-end SEAM**: every subsystem is real, correct, and tested, and **none
is connected to a live surface.** The portal is correctly peripheral. The harness is ready;
the wires — and the decision of *what* to wire it to — are the work.
