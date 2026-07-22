# Build brief for Fable — the trellis onboarding / begin-learning ritual

*You are **Fable** (Anthropic's flagship model). This is a build brief, not an audit.
You were chosen for this because it is as much an interaction-design task as an
engineering one — the way trellis introduces itself and surfaces its own confusion is
half the product.*

---

## 0. The one-sentence job

When trellis starts in an environment for the first time, it must **not sit idle**. It
introduces itself, asks the human whether it may begin, and then — in the background, on
the human's own subscription model — **explores and MAPS the environment**: it ingests
the Discord history, the transcripts, and the Google material it's given, and it builds a
navigable knowledge base of *what everything here is* — never assuming what a term means,
staying **curious**, tracing the **cognitive lineage** of loaded words, and **verifying**
what it learns before it treats it as known.

trellis is **a mapper and an understander, not a task-completing assistant.** The
onboarding ritual is the purest expression of that identity. Build it as such.

---

## 1. Read first (so you build WITH the grain, not against it)

The whole point is that **almost all of this already exists** and is tested — your job is
mostly to *orchestrate and connect*, adding a thin new ritual on top, not to rewrite the
core. `main` is green (593 tests, 10/10 stress). Read:

- `README.md`, `WHAT-THIS-IS.md`, and `DECISIONS.md` — especially **D12** (contextual
  understanding & opinion, not completion), **D14** (memory is navigation:
  WALK/REOPEN/DECIDE), **D20** (a found decision is two linked nodes), **D22** (curiosity
  has teeth — a dry seek is not understanding), **D24** (the compiled, reloaded context),
  **D30** (isolation by identity + allowlist), **D34/D35** (broad Haiku verification;
  contested-and-escalate), **D37** (the always-on local runner).
- `trellis/curiosity.py` — open questions with teeth; a question does not resolve on "I
  searched," only on a pursued map-move. **This is your engine for "what is empire? why
  the lowercase e?".** Every loaded/ambiguous term becomes a curiosity node here.
- `trellis/observe.py` — understand a record as decisions: two linked nodes (the room's,
  the agent's), **finder ≠ confirmer**, confidence-aware, provenance FLOOR+OR. This is how
  the map records *what it understood* without laundering shaky reads into certainty.
- `trellis/sources.py` — the **idempotent ingestion spine** (identity-key dedup,
  content-hash corrections, two-phase markers, `Provenance`). **Every source you connect
  feeds this**, so a re-run never double-ingests.
- `trellis/ingest.py` + `trellis/discord_api.py` + `trellis/isolation.py` — the live
  Discord bridge, the stdlib REST client (`DiscordClient.fetch_messages/…`), and the
  read/act allowlist (only trellis's own surfaces, D30).
- `trellis/registry.py` (stable identities), `trellis/sessions.py` (per-interlocutor
  sessions), `trellis/context.py` (the reload-the-read compiler), `trellis/memory.py` (the
  workspace/read, synthesis-gated writes, the epitaph), `trellis/vault.py` (the
  Obsidian-reconciled face of the record).
- `trellis/verify.py` (`convene_verification`, contested-state) + `trellis/panel.py` (the
  refute-by-default Haiku panel) — the independent verification the learning must pass
  through. `trellis/providers/` (the `claude` = Claude Max and `codex` = ChatGPT-
  subscription seats, plus the cheap verifier seat).
- `trellis/runner.py` + `trellis/scheduler.py` + `trellis/agent.py` (the Witness cycle
  sense→resolve→act→verify→remember) — where the ritual gets scheduled and driven.

If a claim in the docs disagrees with the code, trust the code and **note it** (§6).

---

## 2. What to build — the behaviors, each tied to an existing primitive

Build a new **onboarding ritual** (a new module, e.g. `trellis/onboard.py`, plus a CLI
command, e.g. `trellis begin` / `trellis onboard`) that runs on an explicit initialize
command and does the following. Reuse the primitives named; do not duplicate them.

1. **Introduce + ask consent.** On the command, trellis posts/prints a genuine
   introduction — *"Hello, I'm trellis. I'd like to begin exploring and learning about
   this place — its people, its decisions, and what things here mean. May I begin?"* — and
   waits for a yes before it reads anything. (This is a human gate on *starting to learn*,
   not on each thought — consistent with D33: don't over-gate the agent's own reasoning.)
   Make this interaction excellent; it is the first thing anyone sees.

2. **Never assume meaning — verify it.** When the agent meets a term that is loaded,
   recurring, or idiosyncratic — the canonical example is *"an overnight soak"* (cooking?
   code? a test?), or *"empire"* written with a deliberate lowercase **e** — it must
   **refuse to assume** and instead mint a **curiosity node** (`curiosity.py`) for the
   term and pursue its meaning from the record. A meaning is not "known" until it is either
   traced to real evidence AND independently verified (`convene_verification`), or
   confirmed by a human. Bake the "one word can mean two things to two groups" discipline
   in structurally, not as a reminder.

3. **Trace cognitive lineage.** For such terms and for key decisions, the agent walks
   *how the meaning came to be* — the earliest and the most recent uses, who used it, how
   it shifted — most-recent-information-first, but lineage-aware (`observe.py` provenance,
   the `docs/lineage/` archaeology as a model). Curiosity has agency here: it may go read
   more to close a question, but a dry search never closes it (D22).

4. **Map, don't complete.** The output is a **navigable knowledge base of what everything
   here is** — people, channels, projects, recurring terms, decisions and the agent's own
   read of them — written into the workspace/read and surfaced through the vault
   (`memory.py`, `vault.py`), each entry carrying provenance and confidence. Its stopping
   condition is the Witness's, adapted: *"I have mapped what is here and put my
   uncertainties on the record"* — never "the task is done." An honest *"I don't yet
   understand X"* is a first-class output, surfaced to the human, not hidden.

5. **Ingest everything it's given, idempotently.** Backfill and then keep current across:
   **Discord history** (paginate `DiscordClient.fetch_messages` over the read-allowlisted
   channels/threads, oldest→newest, respecting D30 isolation and DM privacy), **the shared
   Discord messages** the human grants, and **the Google transcripts / Drive material**
   (see §3). Everything maps to `sources.RawItem` and rides the idempotent spine, so a
   re-run is a no-op and a corrected re-dump is a correction, not a duplicate.

6. **Coordinate the main agent + the Haiku verifiers, on startup.** The runner starts the
   Witness learning loop AND convenes the independent Haiku verifier panel on what it
   learns (`convene_verification` / `panel.py`), so a mapped meaning or decision is
   maker≠verifier checked; a REFUTED reading becomes contested-and-escalated (D35), not
   silently trusted. This is the "everything runs, coordinated" requirement — wire it into
   `runner.py` so a single initialize command brings up the whole coordinated set.

7. **Run in the background on the human's model.** The loop runs under the runner (D37,
   always-on-with-the-machine) on the configured subscription seat — `claude` (Claude Max)
   or `codex` (ChatGPT subscription). Bounded, budgeted, resumable; it picks up where it
   left off after a restart (cursor/marker state on the ledger, no naked `now()`).

---

## 3. Connections to wire (the human will provide credentials; you build the adapters)

The learning is only as good as its inputs. Set up the connections — **build the missing
adapters as new modules feeding `sources.py`; do not entangle them with the core.**

- **Discord saves / history.** The live client exists. Add a **backfill**: paginate
  `fetch_messages(after=cursor)` over each read-allowlisted surface until caught up, then
  hand off to the normal tick poll. Persist the backfill cursor on the ledger. Respect the
  D30 allowlist and the DM/privacy scoping (`surfaces.can_flow`) — the "shared Discord
  messages" must be ones the human has granted via the read allowlist.
- **Transcript saves.** trellis already models transcripts as `RawItem(kind="transcript"|
  "media_transcript", machine_transcribed=…)`. Wire whatever transcript source the human
  points at (a folder, or Google Docs — below) into that path, flagging ASR output as
  fallible (provenance).
- **Google Suite.** The `[google]` extra (`google-api-python-client`,
  `google-auth-oauthlib`) and the env stubs (`TRELLIS_GOOGLE_CLIENT_SECRET`,
  `TRELLIS_GOOGLE_TOKEN_STORE`, `TRELLIS_DRIVE_FOLDER`) exist, **but the adapter is not
  built.** Build a minimal Google source adapter (Drive folder listing + Docs/transcript
  fetch) as a `SourceAdapter` that yields `RawItem`s into the idempotent spine, gated by
  the same allowlist idea (one granted Drive folder id, D30-style). OAuth is the human's to
  approve in a browser — the adapter reads the token store Google's own client manages;
  **trellis must not handle raw OAuth secrets** (same posture as the `codex`/`claude`
  seats: let the official client own the credential). If a full build is more than a thin
  adapter, build the thin version and **note** what a fuller one needs (§6).

Where a connection can't be finished cleanly without credentials or a human's OAuth
approval, build the code path and make `trellis doctor` report it honestly as "wired,
awaiting the human's grant" — never a silent stub that pretends to work.

---

## 4. Hard constraints (this is where "don't break it" lives)

- **Minimal footprint. Do NOT rewrite the core.** Add new modules (`onboard.py`, a Google
  adapter, a backfill helper) and thin wiring; reuse curiosity/observe/sources/context/
  verify/panel/memory/vault/runner. If the clean way to do something needs a big change to
  an existing module, **stop and write it as a note/DECISIONS proposal for the human** (§6)
  rather than making the big change.
- **Keep `main` green.** The 593 tests and the 10/10 stress suite must still pass. Work
  test-first for new code; run the full suite before you claim done. The test suite is
  hermetic (it ignores `.env` via `TRELLIS_ENV_FILE`) — keep it that way.
- **Preserve every invariant.** No auto-fire / stage-don't-fire (the agent still never
  *sends* without the human's yes — learning is inbound + internal, but if onboarding ever
  posts (e.g. its introduction), that outbound goes through the staged, owner-approved
  path). Maker ≠ verifier. Append-only, bitemporal, attributed. No naked `now()`. Isolation
  + privacy on every ingested surface. And the deepest one: **no assumptions about
  meaning** — that is the thesis, not a nicety.
- **Curiosity, not confabulation.** A learned meaning with only a dry search behind it is
  `INSUFFICIENT`, never a confident map entry. Confidence takes the floor of its inputs.

---

## 5. Interaction design (why it's you)

You were picked because the *feel* of this matters. The introduction, the consent moment,
and — especially — the way trellis **surfaces its own confusion** ("I keep seeing 'empire'
in lowercase; I don't yet know if that's deliberate — here's what I've found, here's what
I'm unsure of") should read as a genuinely curious, honest colleague mapping a new place,
not a chatbot running a script. The human should be able to watch the map fill in and the
open questions light up (the portal's Assumptions/Curiosities + Sessions pages are the
surfaces — extend them if the map needs a home). Make the legibility real.

---

## 6. Deliverables

1. The onboarding ritual module + the initialize command, wired into the runner, with the
   coordinated main-agent + Haiku-verifier startup.
2. The source connections: Discord backfill, the transcript path, and the Google Drive/Docs
   adapter (thin, credential-clean) — or the honest "awaiting the human's grant" state.
3. Tests for all new code (mock the network/subprocess; no live calls in the suite), and a
   green full suite + stress run.
4. **A notes file** — `docs/ONBOARDING-NOTES-FROM-FABLE.md` — capturing: (a) anything you
   noticed that could be a problem but chose NOT to change (with where and why); (b) every
   place you built the thin version and what a fuller one needs; (c) design decisions only
   the human can make, as short DECISIONS-style proposals (D39+). **Noticing and noting a
   problem is a success here, not a failure — do not silently work around things.**
5. One explicit open item to record, not solve: **how this works for someone outside this
   org** who downloads trellis (different sources, different "empire", no shared Discord).
   This is "just for us right now." Capture it as an open design question; do not build it.

Keep verified separate from assumed in everything you write — the same discipline you're
building into trellis.
