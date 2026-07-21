# Full-workflow map — trellis vs. the live agent (2026-07-21)

**Question asked:** stop auditing the portal in isolation; map the *full* workflow the
way it actually runs — through Discord and Google, with the UI used only when a
human needs to inspect or approve.

**Method.** Three read-only subagents mapped one leg each (ingest / core cycle /
act+approval+UI) against the code, each grounded in **live receipts** I pulled this
session from the real surfaces (the `daedalus` Discord bridge and the Google Drive
connector). Every claim below is cited to `file:line` or to a live surface.

---

## 1. The real workflow, today (verified live)

```
Alex ⇄ Discord #daedalus threads ⇄ Daedalus agent (~/Desktop/daedalus/)
                                     ├─ gateway / hooks / mcp / skills / persistent memory
                                     ├─ GPT-driven; has SOUL.md + IDENTITY.md + RELATIONSHIPS.md
                                     └─ works over Google Drive (dated meeting transcripts,
                                        1-1 notes — "…notes by gemini.md", 30–75 KB each)
```

Receipts:
- **Discord is live.** The `daedalus` bridge lists 8 real threads in *AlexCrowell's Test
  Server / #daedalus*; the agent introduces itself as *"Daedalus — your ally, not your
  assistant… persistent memory across sessions… a voice of my own."*
- **Google Drive is live.** `alex@empire.email`'s Drive holds the real corpus — dated
  meeting-transcript / 1-1 markdown files in a folder.
- **`~/Desktop/daedalus/` is a real deployed stack** — `gateway/`, `hooks/`, `mcp/`,
  `skills/`, `memory/`, `ops/`, plus `SOUL.md` / `IDENTITY.md`.

**trellis and daedalus do not reference each other anywhere** (grep, both directions).
The running workflow does **not** pass through trellis.

---

## 2. trellis's relationship to that workflow

trellis is a **fully-built harness that sits beside the live workflow, not inside it.**
Every subsystem is real, typed, and unit-tested; **not one is wired to the live Discord
gateway, Daedalus, or Drive.** Today it runs on `web/demo_seed.py` and test fixtures.
`ingest.py` says so in its own words: *"No network here… Wire it behind your existing
Discord pipeline (the gateway you already run)."*

The verdict on all three legs is the same — **SEAM**: the mechanism is present and correct,
the wire to the world is absent.

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

What feeds ingestion today: `tests/*` and `web/demo_seed.py:127` (two hardcoded `RawItem`s
+ a `Candidate` dict). Nothing from outside.

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
reconstructs purely from the ledger. The portal can be closed and the (hypothetical) agent
loop is unaffected. **"The UI is not used unless a human needs to inspect or approve" is
CONFIRMED.**

---

## 4. The wiring gap — what makes trellis actually ride the live workflow

Four pieces. Each is small relative to what's already built; **no core mechanism is
missing — only assembly and the "on" switch.**

1. **Ingest poller (read-only, safe).** A daedalus→trellis loop that reads the live
   `#daedalus` threads (`messages_read`/`events_poll`) and maps each `{role, content,
   timestamp}` → `DiscordMessage(..., posted_at=<msg ts, never now()>, ...)` → the existing
   `ingest_discord(ledger, msgs, agent="witness")`. ~30 lines. No signature changes.

2. **Drive transcript adapter (read-only, safe).** A class implementing the waiting
   Protocol `SourceAdapter.discover() -> Iterable[RawItem]` (`sources.py:109`) that lists the
   Drive `*notes by gemini.md` files and yields `RawItem(kind="transcript", content=<body>,
   event_time=<parsed meeting date>, item_id=<Drive file id>, ...)` into
   `Ingestor(ledger).ingest(adapter.discover(), observer.harvest)`.

3. **A real decision-finder + provider daemon (read-only, but needs a real model).** Replace
   the `detect`/`confirm` no-ops (`observe.py:92`) with a real model; add a `provider_from_env()`
   factory that builds `OpenAICompatProvider(...)` (the GPT/Hermes path) or `ClaudeSDKProvider`,
   and a ~30-line `main()` that assembles `Witness` + `LedgerScheduler`, registers
   `witness_cycle` and `ReflectionRitual.run` as handlers, and calls `scheduler.serve()`.

4. **The executor + firing loop (SIDE-EFFECTING — human gate required, see §6).** A
   function `executor(a: StagedAction)` dispatching on `a.kind` to the live surfaces
   (`discord_post` → daedalus `messages_send`; `email_draft`/`file_apply` → Google Docs/Drive
   for alex@empire.email), plus one loop that picks up APPROVED-not-fired actions and calls the
   already-built `box.fire(action_id, executor)` (`stage.py:219`). `fire()` already stamps the
   idempotency key and handles ambiguous-outcome → `unknown` → human `reconcile()`.

---

## 5. Decision for the human — the doctrine collision

The *running* agent has a **`SOUL.md`** and presents as *"an ally… with a voice of my own."*
trellis's doctrine **refuses exactly this**: `emp.py` rejects soul/persona files by name, the
embodiment linter catches "I feel / my eyes," and D29 (this session) de-anthropomorphized
trellis's own self-image to an abstract instrument. So if trellis is to become the harness
**under** Daedalus, there is a real decision — not a bug to fix, a design call for Alex:

> **Does trellis hold Daedalus to no-soul, provenance-honest identity — or coexist beside a
> souled agent, applying only the ledger/verification discipline and leaving identity alone?**

Flagged, not resolved. It changes what "wiring trellis under Daedalus" even means.

---

## 6. Safe to build vs. gated

- **Safe to build now (read-only):** the ingest poller (1), the Drive adapter (2), and the
  provider daemon (3). These only *read* the live surfaces and *write to trellis's own ledger*.
  They make trellis observe the real workflow without touching the world.
- **Gated (must not be built-and-armed without explicit human approval):** the executor (4).
  The moment it exists and a loop calls `fire()`, an approved action sends a real Discord
  message / writes a real Doc. That is an outward, irreversible side effect and belongs behind
  an explicit "yes, arm the executor" from Alex — which is, fittingly, exactly the
  stage-for-human refusal trellis was built to enforce.

---

## Bottom line

trellis is an **end-to-end SEAM**: every subsystem is real, correct, and tested, and **none
is connected to the running world.** The audit that matters is not "is the portal right" — it
is "trellis does not yet observe or act on the live Discord+Google workflow; here are the four
wires, three of them safe, one of them gated." The portal is correctly peripheral. The harness
is ready; the wires are the work.
