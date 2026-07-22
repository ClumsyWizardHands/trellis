# Onboarding build — notes from Fable

*Companion to the build ratified by `docs/FABLE-ONBOARDING-PROMPT.md`. Everything
here follows the brief's own discipline: **verified is kept separate from
assumed**, and noticing a problem is a success, not a failure. Suite state at
delivery: **645 tests passing** (593 baseline + 52 new), **stress 10/10**.
Post-delivery, Alex ratified two decisions now in DECISIONS.md: **D39** (no
daily budget on subscription seats) and **D40** (read scope = everything the
bot identity can see in the server, granted in Discord itself) — both built
and pinned by `tests/test_read_scope_and_budget.py`.*

What was built (all new modules; no core rewritten):

| Piece | Where | State |
|---|---|---|
| Begin-learning ritual (consent, term curiosities, lineage, verified meanings, the map) | `trellis/onboard.py` | built + tested |
| `trellis begin` / `trellis onboard` (+ `--once`), `trellis google grant/status`, doctor lines | `trellis/cli.py` | built + tested |
| Discord history backfill (oldest→newest, one cursor contract with the live poll) | `trellis/backfill.py` | built + tested |
| Local transcript folder adapter + shared `document_harvester` | `trellis/transcripts.py` | built + tested |
| Google Drive/Docs adapter (thin, credential-clean, honest ungranted state) | `trellis/google_source.py` | built + tested (offline; live path awaits the grant) |

---

## (a) Noticed, and NOT changed (with where and why)

1. **The daily budget cap never trips on metered seats.** `runner.DayBudget`
   enforces `TRELLIS_DAILY_BUDGET` against the sum of `charge` ledger records —
   and **nothing in the codebase ever calls `DayBudget.charge()`**. The Witness
   charges only its per-run `loops.Budget` (turns/tokens); no handler appends a
   `charge` entry, so the cap gates a sum that is always zero. *Update
   2026-07-22: Alex ratified **D39** — subscription seats (codex; claude on the
   Max login) now run uncapped by design, which is honest. The gap REMAINS for
   metered/API-key seats: their $5 default cap still guards a sum nothing
   increments → **D43 proposal below**.*

2. **The standing Witness schedules never fire from the CLI.**
   `Runner.DEFAULT_SCHEDULES` registers `witness.cycle` / `witness.reflect` /
   `witness.harvest` on every tick, but `trellis tick` and `trellis run` pass
   `handlers={}`, and `scheduler.run_due` silently skips a due schedule with no
   handler. Visible in `health()` as "registered but never fired" — so it is
   loud-ish, not silent — but the doctrine's main loop has no CLI wiring. The
   onboarding loop (`onboard.learn`) is the first scheduled model loop that
   actually runs end-to-end from a command. Why not changed: choosing which
   events feed a witness cycle (per surface? per session? how many?) is a
   design decision → **D42 proposal below**.

3. **Ledger growth.** Full message/document content lands in the ledger (as the
   existing Discord path already did). Drive docs/transcripts are capped at
   200k chars per entry with an honest `truncated` flag, but a folder of many
   large docs will still grow the JSONL and its in-memory read cache. Fine at
   personal scale; worth revisiting before pointing trellis at a large corpus.

4. **`TRELLIS_VAULT_PATH` should be a *subfolder* of the Obsidian vault** (as
   `.env.example` already suggests). The onboarding map writes under it, and
   `Workspace.map()` walks every `.md` below the root — pointed at a whole
   personal vault, the map view and reconciliation would sweep everything.
   Existing behavior; now it matters more, so it is named here.

5. **Fixed in passing (CLI wiring, not core): `trellis run`'s Discord poll was
   a false claim.** `cli._run_runner` feature-detected a `poll_client`
   parameter that `Runner.run` never grew, so `trellis run` printed "Discord
   poll wired" while never polling. It now attaches a real `DiscordPoll` as
   `runner.discord`, the same way `trellis begin` does. (Reported here because
   the brief said to note what I touched beyond the strict scope.)

## (b) Thin versions, and what a fuller one needs

1. **Google adapter** (`google_source.py`): re-lists the one granted folder on
   every pass (idempotent, so correct — but O(folder) per pass); no subfolder
   recursion; reads Google Docs + `text/*` only (no PDFs/Sheets/Slides — they
   land in the honest `skipped` count); ASR detection is a filename heuristic
   ("transcript" ⇒ `machine_transcribed=True`); doctor reports config-verified,
   not reachability-verified. Fuller: the Drive *changes* API with a
   `startPageToken` persisted on the ledger (true incremental sync), recursive
   walk with per-subfolder grants, PDF text extraction, and provenance from
   Drive revision history. *Update 2026-07-22: `TRELLIS_DRIVE_FOLDER` now takes
   a comma-separated list of granted folder ids (still an explicit allowlist),
   and the token store is strictly READ-ONLY to trellis — a refresh happens in
   memory and is never written back, so a store copied from (or pointed at)
   another agent's token file can never have its scopes clobbered.*

2. **Term scout** (`onboard.TermScout`): deterministic — seed terms
   (`TRELLIS_ONBOARD_TERMS`, phrases welcome) + recurring rare words and
   bigrams (≥4 uses, ≥2 voices) + casing-variant tracking. It cannot judge that
   a *single-use* phrase is loaded; "an overnight soak" is caught by the seed
   list or by recurrence. Fuller: a cheap-model candidate pass whose proposals
   are still only ever minted as curiosity nodes (the never-assume gate stays).

3. **Speaker attribution inside documents**: a transcript is attributed to
   `"(document) <title>"` — honestly the document's voice, not falsely the
   ingest agent's, but also not the speaker's. Fuller: a speaker-turn parser
   feeding `observe.DecisionObserver`, so decisions inside transcripts become
   the two-node observation/opinion pairs the machinery already supports.

4. **Thread history**: the backfill covers every read-allowlisted channel (and
   any thread id explicitly allowlisted/passed as a surface), but it does not
   *enumerate* a channel's active/archived threads — `discord_api.py` has no
   thread-listing calls, and adding them is a core-adjacent change I did not
   make. Fuller: `GET /guilds/{id}/threads/active` + archived-thread pagination,
   feeding `PollSurface(is_thread=True, parent_channel=…)` entries.

5. **Meaning proposals** (`propose_meaning`): one attempt, ≤8 fenced excerpts,
   strict JSON, malformed ⇒ `None` (recorded, never retried into
   confabulation). Fuller: the Witness-style retry ladder and a richer evidence
   window.

6. **Decision harvest during onboarding**: ingested transcripts do not yet run
   through `observe.py`'s detect/confirm pair (that needs a ratified detector
   prompt). The spine is shared, so wiring it later retires nothing.

7. **Portal surface**: open term-curiosities appear on the existing
   Assumptions/Curiosities page automatically (they are ordinary question
   nodes), and sessions on the Sessions page. A dedicated "Map" page (terms +
   confidence + verification state, the watch-the-map-fill-in view) is not
   built; the map lives as vault/workspace notes under `map/`.

## (c) Proposals for the human (DECISIONS-style; D39/D40 were ratified 2026-07-22 and moved into DECISIONS.md)

- **D41 (proposal) — Consent to learn is a standing, revocable, ledgered
  grant.** The latest `onboard_consent` entry wins; `declined` halts every
  learning pass at its consent gate (a typed `blocked/needs_input` outcome,
  nothing read). The grant's scope is the configured sources at pass time —
  under ratified D40 that means widening the bot's channel visibility in
  Discord widens the grant without re-asking. *Implemented as described;
  ratify or tighten (e.g. re-ask on scope widening).*

- **D42 (proposal) — Meaning has trust tiers.** A traced-but-unread meaning
  carries 0.6; a model-proposed, unconfirmed meaning is **capped at 0.7**; only
  an independently verified (maker≠verifier panel) or human-confirmed meaning
  (0.95) counts as "known", and only "known" meanings should ground downstream
  opinions. *Implemented as caps in `onboard.py`; the downstream-grounding rule
  is doctrine to ratify.*

- **D43 (proposal) — Make the metered-seat budget real.** For API-key seats
  only (D39 removed the question for subscription seats): decide the costing
  model (provider-reported usage → `DayBudget.charge` records, or a flat
  per-call estimate the human ratifies), then wire it into every model-bearing
  handler. Until then a metered seat's cap is a comfort, not a cap (see (a)1).

- **D44 (proposal) — Wire the Witness cycle from the CLI.** Choose what feeds
  it (e.g. each tick's newly admitted messages per surface, as `Event`s), at
  what cadence, and with which provider seat — then `trellis run` grows the
  handler. The onboarding loop shows the wiring shape.

## (d) The one open item to record, not solve (§6.5)

**D45 (open design question, deliberately unbuilt) — trellis for someone
outside this org.** Someone who downloads trellis has: no shared Discord, no
"empire", no Brett/Sarah lineage, different sources, no seeded vocabulary, and
no EMP. What already generalizes: the adapters + idempotent spine are
source-agnostic; the term discipline takes any seed list and finds recurrence
on its own; consent, verification, and the map are org-free. What does not: the
demo EMP's voice, the default schedules' names, the assumption that a Discord
estate exists at all, and — deepest — *who writes the newcomer's EMP*. Is
first-run onboarding an interview that drafts an EMP the human ratifies? Is an
empty seed list safe, or does it just make a quieter mapper? This is "just for
us right now"; the question is on the record, unanswered on purpose.

## Verified vs assumed, about this build itself

- **Verified:** all module behavior described above is pinned by the 43 new
  tests (`tests/test_backfill.py`, `test_transcripts.py`,
  `test_google_source.py`, `test_onboard.py`, `test_cli_begin.py`); full suite
  636 green; stress 10/10; the offline smoke run of `trellis begin --once`
  produced the map, the curiosity nodes, and honest "open, not yet verified"
  outcomes with no model configured.
- **Assumed (not yet exercised live):** the real Discord REST responses at
  backfill scale (rate-limit pacing beyond the unit-tested shape); the live
  Google client path (`build()`/export against a real token store); the Claude
  Max / Codex seats inside the onboarding loop. Each is behind an injectable
  seam and honestly reported by `doctor` until granted.
