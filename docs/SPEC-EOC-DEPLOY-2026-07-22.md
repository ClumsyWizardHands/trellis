# SPEC — Empire of the Chief deployment: concerns → EMP triangulation → roadmap

**The core answer:** trellis is deployable in a private Discord channel today
via `trellis begin` (the onboarding/learning loop, end-to-end complete, 651
tests passing). The three agreed experimental variables — **this harness + the
baby EMPs + Brett's OAuth** — are all supported in the code as it stands. What
this spec adds: the Chief-of-Staff EMP in loadable form
(`examples/chief-of-staff-emp.md`), every harvested concern from the 2026-07-21
Alex/Clare 1:1 triangulated against the repo through the EMPs, and a staged
roadmap whose one pre-launch build item is **D44** (wire the witness cycle from
the CLI). Everything else is credentials, human steps, or post-launch.

- Authored: Clare Healy, 2026-07-22 (with Fable). Sources: the 07-21 1:1
  transcript (verbatim), the baby EMPs doc (v1/v2/v3 + Lab agreements), this
  repo at `8db3f9f`.
- Method: harvest the anxieties/questions → triangulate each against the repo
  *through the EMPs* (the EMP element decides, not taste) → Y/N/T with lineage.
- Clock, said loudly: the in-call commitment was repo-update EOD 07-21 and
  Discord deploy by 12:00 CT 07-22. The repo update lands with this PR — behind
  the committed mark. The deploy runbook below is built for same-day execution.
- Amended same morning (Clare's updates, 07-22): Alex has already stood the
  trellis bot up in the Alliance of Empires server, and Clare + Sarah hold
  Brett's OAuth via the custody profile and can share it with Alex as the
  agent's owner. C2, C4, C6, D48, R1, and the runbook reflect both.

---

## 1 · The harvest — anxieties, concerns, open questions from the 1:1

| # | Concern / question | Who, where |
|---|---|---|
| C1 | Which harness is right? (proposed 4-way audit: principles-claw/Hermes, open claw, pi, trellis) | Clare 00:39; Alex 00:47 |
| C2 | Where and how does the agent run — whose machine, who hosts? | Clare 00:40, Alex 00:48 |
| C3 | Whose model usage powers it? Clare doesn't want her Anthropic usage consumed; interest in testing PBC on the GPT family | Clare 00:44–00:46 |
| C4 | Discord permissions and scope for the agent | Clare 00:40 |
| C5 | Directives → process → no feedback → stall → frustration; don't do a mountain of audit work that never gets responded to | Clare 00:50–00:54 |
| C6 | The ultimate end is chiefs' access to Brett's workspace — a current-state blocker, ASAP | Clare 00:52 |
| C7 | Trust: "when there's a lack of trust on an agent... I don't know what to show to put trust back" | Alex 00:55–00:56 |
| C8 | Don't pass a stinky turd — no team triangulation yet, not yet presented with a pass | Alex 01:01 |
| C9 | Alex's prior harvest of "what works with agents and what doesn't" (Brett/Sarah's stated wants) — not yet located; risk of shipping something they said no to | Alex 00:48 |
| C10 | Which model *starts* it (Alex: "not a coding model — the new soul model"?); OpenAI harness-friendliness needs verification | Alex 00:46 |
| C11 | The reflection/art feature currently draws "aliens" — a named anti-example, unrefined | Alex 01:02 |
| C12 | Alex has improvements not yet pushed; the repo is in flux under continuous updates | Alex 01:09 |
| C13 | Search-the-Stack integration — future, explicitly not launch-gating | Alex/Clare 01:09 |
| C14 | Brett: don't overinvest in one particular agent | Clare 00:56 |
| C15 | Minimize every variable except the three: harness, EMPs, OAuth | Clare 00:52 |

## 2 · The triangulation — each concern, through the EMPs, against the repo

**C1 — harness choice → Y, trellis, by the ship-the-process reframe.** The
in-room resolution: run the experiment instead of auditing four candidates
first (C5's principle: get feedback on *outputs*, not on the process). The EMP
backs it twice: *loops are the operating unit — don't wait for permission to
try a reversible loop* (Lab agreement L3), and trellis is the only candidate
purpose-built to the *no-self-verify / trace-test* principle. The 4-way audit
stays available as a post-launch T if the experiment disappoints — the
experiment IS its first data point.

**C2 — where it runs → resolved by events: Alex's machine, Alex owns.**
Repo doctrine D37: always-on *with a machine*, not a server. Alex stood the
bot up in the Alliance of Empires server, so he owns and hosts the agent —
which also fits the custody-spec pattern (a chief's machine holding a
Brett-delegated grant; Clare/Sarah share the custody profile with him, C6).
Clare stays **approver**: owner ≠ approver keeps a human cross-check on the
agent's sends, the same shape as maker ≠ verifier. Migration later stays
cheap because state is one ledger file.

**C3/C10 — model seat → T (default: Codex maker + Haiku verifier).** The repo
is genuinely model-agnostic (D11): four real providers, subscription seats for
both Claude Max (`claude login`) and ChatGPT (official Codex CLI — no API key,
credential untouched). The EMP decides the posture: *00-grade every decision
until any agent can execute it* — the harness must not depend on any one
frontier seat. Default resolves C3 directly: **maker = Codex seat on the
ChatGPT subscription** (Clare's stated interest in testing a principles-based
approach on the GPT family, 00:45; zero draw on her Anthropic usage),
**verifier = Claude Haiku** (cheap, and maker≠verifier across *vendors*, the
strongest form of no-self-verify — the factory enforces seat separation
either way). Swapping seats later is a .env change, which is the point.

**C4 — Discord scope → Y, answered in code.** D40: read scope = exactly what
the bot's own identity can see; grant is edited in Discord, not config. Launch
posture: the trellis-owned bot (D30 — never reuse another agent's token) is
**already in the Alliance of Empires server** (Alex, 07-22 AM) — scope it to
**one private channel** there via Discord channel permissions; other agents
(Moro) live in that server, and D30's own-bot/own-token rule is exactly what
keeps the identities separate. `TRELLIS_ACT_SURFACES` **empty** on first
run; `TRELLIS_APPROVER_DISCORD_ID` = Clare for the experiment. The EMP's
*pass-before-irreversible* is structurally enforced: stage-don't-fire outbox,
✅-reaction approval, executor that refuses when un-armed.

**C5 — process-stall anxiety → Y, absorbed into the plan's shape.** This PR
ships artifacts (spec + loadable EMP), not a request for feedback on method.
The deploy runs tomorrow's feedback loop on the agent's *outputs* in-channel.
Friction line 1 of the EMP encodes it permanently.

**C6 — workspace access → T, the honest gap, named loudly.** The EMP custody
means spans Email, Calendar, Drive. The repo today ships **Drive read-only
docs+text** (delegated OAuth grant flow, folder allowlist, shared-drive
support landed 07-21) — **no Gmail, no Calendar**. So launch honestly: the
experiment demonstrates the trust architecture on Discord + granted Drive
folders; **Gmail/Calendar read adapters are roadmap phase R1**, not silently
implied. Custody update (Clare, 07-22): Clare and Sarah already hold Brett's
OAuth via the custody profile and can share it with Alex as the agent's owner
— so no step waits on Brett's calendar. The distinction that keeps this clean:
the custody profile is the *human's* credential (full workspace, as Brett);
the *agent's* credential should still be minted through `trellis google grant`
run under that profile on the deployment machine — least-privilege
(`drive.readonly`, named folders only), token store held read-only, ledgered,
revocable — never the custody credential handed to the agent wholesale. The
custody share unlocks the full suite exactly as fast as the R1 adapters land:
scope widens adapter-by-adapter, re-asking consent each time (D41's posture
when D40 scope widens). Acting as Brett is where pass-before-irreversible
binds hardest.

**C7 — what to SHOW to rebuild trust → Y, the repo's whole thesis.** The
showable objects exist: the dated ledger (append-only, authored, bitemporal),
REFUTED-decision escalation, staged sends approved by visible ✅ in-channel
(Sarah's trace test verbatim: seen with human eyes), the web portal's
comprehension pages. The deployment should *demonstrate* — first staged send
approved live in the private channel — not describe.

**C8 — no stinky turd → Y, this pass is the triangulation.** Clare's
dissection (this spec) is the first non-Alex triangulation; the PR is the
pass; Alex reviews before merge; nothing reaches Brett's channel until the
private-channel run holds up. Sequence satisfies *wash your hands / no agent
goes it alone*.

**C9 — Alex's agent-notes harvest → T, held by Alex.** Not in this repo; can't
be triangulated from here. Pre-launch if found today, else it audits the
running experiment (cheap: the ledger makes retro-checking trivial). Bank it
per *memory-delusion* — if it isn't found and banked, it didn't happen.

**C11 — the aliens → N for launch, kept on roadmap.** Self-portrait/glyph code
exists and harms nothing. The EMP's *attention economics* rules it out of the
launch path: it doesn't raise tomorrow's bet-quality. Refinement (reflect on
yesterday's image vs. today's events) is R3.

**C12 — repo in flux → Y, resolved by the agreed choreography.** This work
lands as a PR on a branch; Alex merges his pending improvements and this PR in
whatever order he wants tomorrow morning; the ledger and EMP files don't
collide with harness internals by design.

**C13 — Search-the-Stack → Y (defer).** Already ratified in-room; matches the
repo's W-list restraint. R4, post-launch, when it's ready.

**C14 — don't overinvest in one agent → Y, satisfied structurally.** Model
agnosticism (D11) + EMP-not-soul (identity is a swappable document, not an
accreted persona) + one-ledger state portability = the experiment doesn't
marry the team to trellis; it tests trellis.

**C15 — minimize variables → Y, enforced by this spec's scope.** The PR adds
docs + one EMP file + supersedes one stale doc note. No harness code changes
in this pass; the one build item (D44) is proposed below with an exact sketch,
for Alex's hands or a reviewed follow-up commit — his call tomorrow morning.

## 3 · Proposed decisions (numbered to follow D41–D45, for Alex to ratify)

- **D46 (proposal)** — The Chief-of-Staff seat EMP ships as
  `examples/chief-of-staff-emp.md`, compiled from baby EMP v3 (staging), and
  is **superseded, never edited** when the chiefs' bonfire ratifies canon.
  Sensitive material (v3's T1/T2) stays out of the shipped EMP entirely;
  those Ts remain Clare-held in the vault.
- **D47 (proposal)** — Launch scope is honest: Discord (one private channel,
  read) + granted Drive folders. Gmail/Calendar are roadmap R1, and nobody
  presents the agent as having workspace access it doesn't have.
- **D48 (proposal)** — Seats and roles at launch: maker = Codex (ChatGPT
  subscription), verifier = Claude Haiku; **owner/host = Alex, approver =
  Clare** — owner ≠ approver keeps a human cross-check on the agent's sends.
  Any seat swap is a .env change + a ledger note, not a rebuild.
- **D44 (endorse + sketch)** — Wire the witness cycle from the CLI. Sketch:
  `cli.py` `cmd_run`/`cmd_tick` currently pass `handlers={}` (cli.py:493,
  516) while `Runner.DEFAULT_SCHEDULES` (runner.py:352) registers
  `witness.cycle/reflect/harvest`. Build a handler factory that (a) constructs
  the configured provider seats via `providers/factory.py`, (b) binds
  `Witness.witness_cycle` (agent.py:133) over the ingested events since the
  last cycle, (c) registers under the schedule names — mirroring exactly how
  `trellis begin` seats its onboarding handler (cli.py:897). Until D44 lands,
  `trellis begin` is the deployment: the agent learns, maps, backfills, and
  confirms terms — honestly, without scheduled opinions.
- **D41, D42, D43 (endorse as written)** — consent as a standing revocable
  ledgered grant; meaning trust-tiers; make the day-budget real (D43 matters
  more once any seat runs on an API key; subscription seats blunt it today).

## 4 · Roadmap

**R0 — today, pre-launch (this PR + Alex's morning review):** merge Alex's
pending improvements; review + merge this PR; decide D44 (wire now vs. launch
on `begin` and wire this week); Alex looks for the C9 harvest.

**R1 — launch (today, target 12:00 CT — runbook §5):** private channel live,
consent ritual, backfill, EMP-grounded learning loop; first staged send
approved with ✅ in front of human eyes. Then: the Google grant — Clare/Sarah
share the Brett custody profile with Alex, who runs `trellis google grant`
under it on the deployment machine and names the granted folders (can land
after noon — say so rather than slip silently).

**R2 — this week:** D44 live if not at launch; Gmail + Calendar read adapters
(the C6 gap — extends `sources.py`/`google_source.py` patterns, same
delegated-grant, read-only posture); C9 retro-audit against the ledger;
self-improvement Phases 2–4 on Alex's go.

**R3 — next:** reflection feature refined past the aliens (compare yesterday's
image to today's events); incremental Drive sync (changes API), subfolder
recursion; thread-enumeration backfill.

**R4 — future, explicitly deferred:** Search-the-Stack integration; the 4-way
harness audit if the experiment's data says so; D45 (trellis for someone
outside this org).

## 5 · Launch runbook (same-day)

Human-only steps: the bot already exists and sits in the Alliance of Empires
server (Alex, 07-22 AM — per GO-LIVE-CHECKLIST §6 confirm Public Bot is off
and Message Content + Server Members intents are on). Remaining: create/choose
the one private channel and restrict the bot to it via channel permissions
(Alex), copy the guild/channel/user ids, and share the Brett custody profile
with Alex (Clare/Sarah). Then, on Alex's machine:

1. `pip install -e .` → `trellis init` → `trellis doctor` → `trellis demo`
2. `.env`: bot token · guild id · `TRELLIS_ACT_SURFACES=` (empty) · approver
   id (Clare) · `TRELLIS_PROVIDER=codex` · `TRELLIS_VERIFIER_PROVIDER=claude`
   + Haiku model · `TRELLIS_EMP_PATH=examples/chief-of-staff-emp.md` ·
   optional vault subfolder path
3. `trellis begin` — consent ritual runs in-channel; watch the Sessions page
   and the ledger
4. When the read loop looks right: add the one channel to
   `TRELLIS_ACT_SURFACES`, arm the executor, stage one send, approve with ✅
5. Brett's OAuth: Alex runs `trellis google grant` on the deployment machine
   under the shared Brett custody profile,
   `TRELLIS_DRIVE_FOLDER=<the named folder ids>`
6. `trellis confirm "<term>" "<meaning>"` as terms surface (start with:
   empire, EMP, 00-grade, Y/N/T, DAP, sapling)

## 6 · Held out of scope, on purpose

Sensitive v3 material (T1 — Brett's strain; T2 — identity stakes) stays out of
the shipped EMP and out of this repo; Clare holds those Ts in the vault.
`docs/SETUP-ISOLATED-DISCORD.md` carries a supersedure banner as of this PR
(its "NOT DONE / executor not built" header predates the go-live layer). The
EMP v3 bonfire ratification (due 2026-07-23) supersedes `chief-of-staff-emp.md`
when it lands.
