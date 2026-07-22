# Go-live checklist — wiring the code-complete trellis to your Discord

Everything is built, tested (541 tests, 10/10 stress), and committed on the
`go-live-hardening` branch. What remains is not code — it is the credentials and
ids only you can provision, plus two small arming steps. This is the honest gap
between "the harness works" and "it is watching your server."

## 1. What only you can provide

| What | Env var | Notes |
|------|---------|-------|
| A **trellis-owned** Discord bot token | `TRELLIS_DISCORD_TOKEN` | Create a bot that is *trellis's own identity* (D30) — never reuse another agent's. The secret is read on demand, never stored or logged. |
| The **read** allowlist | `TRELLIS_READ_SURFACES` | Comma-separated channel ids trellis may read. Empty = inert. An allowlisted channel implies its threads (D32); DMs are in but stay scoped to each interlocutor (D32/D36). |
| The **act** allowlist | `TRELLIS_ACT_SURFACES` | Channel ids trellis may *post to* — a **separate, deliberately smaller** set (D30). Empty = it can read but never send. |
| The **owner** Discord user id | `TRELLIS_APPROVER_DISCORD_ID` | Only *this* user's reaction approves a staged send (D38). Any other member's reaction is ignored. |
| The **maker** model seat | `TRELLIS_PROVIDER` + its key | The Opus-class reasoning model (D34). |
| The **verifier** seat | `TRELLIS_VERIFIER_PROVIDER` / `TRELLIS_VERIFIER_MODEL` | The cheaper Haiku seat; refuses to start if it equals the maker seat (D4/D34). |

## 2. Two arming steps (code exists; they are deliberately not on by default)

- **Arm the executor.** The send transport (`executor.urllib_discord_sender`) is
  built but not the default — an un-armed executor refuses rather than pretending
  to send. Production wiring passes the live sender **and the ledger** to
  `DiscordExecutor(iso, send_fn=..., ledger=...)` so the defense-in-depth approval
  re-check is active. Until you arm it, trellis stages sends but cannot post.
- **Seat the runner's model handlers.** `trellis run` registers the witness /
  reflection / harvest schedules, but their handlers need the provider seated
  (step 1). Until then the runner ticks and keeps the record honest but runs no
  model cycle.

## 3. The safety posture you ratified (unchanged by go-live)

- **Nothing auto-posts.** Every outbound stays staged for your yes (refusal #5).
  The executor can post; it only ever fires an owner-approved action.
- **The yes happens in Discord.** React ✅ (approve) / ❌ (deny) on the staged
  proposal trellis DMs you — routed through the same authenticated,
  maker≠approver, lifecycle-gated path the web portal uses.
- **The agent keeps its agency.** It changes its own mind, reflects, and re-decides
  on its own authority — logged, portal-visible, and machine-verified by the Haiku
  seat. A human is pulled in only for a send, a refuted verdict, or reversing a
  decision you personally ratified (D33).

## 4. One open design call

**Resolved (Alex, 2026-07-21):** the **/sessions** page shows DM content, so it is
owner-only even on localhost — an unauthenticated GET redirects to `/login`. The
other comprehension pages stay open.

## 5. Suggested first live hour (still fully safe)

1. Set step-1 vars with **`TRELLIS_ACT_SURFACES` empty** (read-only): trellis reads
   and stages, but physically cannot post.
2. `trellis run` — watch the Sessions page and the ledger fill; confirm attribution,
   threading, and DM-scoping look right on real traffic.
3. When you trust what you see, add one channel to `TRELLIS_ACT_SURFACES`, arm the
   executor, and try one staged send — approve it with a ✅ in Discord.

## 6. Walkthrough — creating the trellis Discord bot + gathering the ids

The safety-critical logic (approval mapping, guards, "only your reaction counts")
is built and tested; these steps just gather what only you can create.

**A. Create the bot**
1. https://discord.com/developers/applications → **New Application**, name it `trellis`.
2. Left sidebar → **Bot** → **Reset Token** → copy → this is **`TRELLIS_DISCORD_TOKEN`**
   (treat it like a password).
3. On the Bot page, enable the **Message Content Intent** and **Server Members Intent**
   under *Privileged Gateway Intents*; save.

**B. Invite it to your server**
4. **OAuth2 → URL Generator** → Scopes: `bot`; Bot Permissions: View Channels, Read
   Message History, Send Messages, Send Messages in Threads, Add Reactions.
5. Open the generated URL, pick your server, **Authorize**.

**C. Get the ids** (Discord → *Settings → Advanced → Developer Mode: ON*)
6. Right-click a channel → **Copy Channel ID** → **`TRELLIS_READ_SURFACES`** (watch)
   and **`TRELLIS_ACT_SURFACES`** (post — leave EMPTY for the first read-only run).
7. Right-click your own name → **Copy User ID** → **`TRELLIS_APPROVER_DISCORD_ID`**
   (only your reaction approves a send).

**D. Model seats** — `TRELLIS_PROVIDER` (+ key) for the Opus maker; `TRELLIS_VERIFIER_PROVIDER`
/ `TRELLIS_VERIFIER_MODEL` for the Haiku verifier.

Put them in `.env`, then run `trellis doctor` (it reports honestly what's still unset)
and `trellis discord` (it prints exactly which vars it needs).

### The remaining live plumbing (a small final mile, not another build)

Two seams are deliberately scaffolded because they can only be finished and tested
against the real bot your token creates:
- the **gateway socket** that receives your ✅ reactions (`DiscordGatewayConnection`);
- the **stdlib-urllib send** that posts a message (the `_urllib_sender` in
  `trellis discord`, and the DM-channel-open path in `executor.urllib_discord_sender`).
Once the token exists, finishing these + an end-to-end read-only test on your server
is the last step before it is live.
