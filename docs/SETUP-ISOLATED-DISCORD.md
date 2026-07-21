# Setup — trellis's own isolated Discord identity

> **Status: NOT DONE.** The isolation *boundary* is built and tested
> (`trellis/isolation.py`, D30). The live wiring below is pending the steps only
> Alex can do (creating a bot, handing over ids). The **send executor is
> deliberately not built** — trellis reads first; it does not act until explicitly
> armed (W3).

The point: trellis gets its **own** Discord application, its **own** token, and
access to **only its own channel** — enforced by Discord channel permissions, not
by trust. It can never see `#vex-atlas-work`, `#daedalus`, or any other agent's
channel, because it was never granted them.

---

## Part A — create the trellis bot (Alex; ~10 min)

1. **Discord Developer Portal** → <https://discord.com/developers/applications> →
   **New Application** → name it `trellis`.
2. **Bot** tab → **Add Bot**. Turn **Public Bot OFF** (only you can invite it).
3. **Reset Token** → copy it once. This is the value for `TRELLIS_DISCORD_TOKEN`
   (see Part C). Treat it like a password — I never need to see it.
4. **Privileged Gateway Intents** (same page): turn **MESSAGE CONTENT INTENT ON**.
   A bot cannot read message *text* without it. Leave Presence/Server-Members OFF.

## Part B — grant it ONE channel, nothing else (Alex; the isolation step)

A bot added to a server is a server member; the isolation is done at the **channel**
level, so do this deliberately:

5. **OAuth2 → URL Generator** → scopes: check **`bot`** only. Under **Bot
   Permissions**, check *only*: **View Channels**, **Read Message History**.
   Do **not** grant Send Messages, Manage anything, or Administrator. (Send comes
   later, only when you arm the executor.)
6. Open the generated URL, invite the bot to your server.
7. **Now restrict it to one channel.** Create (or pick) a dedicated channel, e.g.
   **`#trellis`**. In that server's settings, set channel permission overwrites so
   the trellis bot role can **View Channel** + **Read Message History** on
   `#trellis` **only**, and is **denied View Channel** on every other channel /
   category. This is what makes the isolation physical — verify by logging in as
   the bot (or checking its role) that it sees exactly one channel.
8. **Copy the channel id.** User Settings → Advanced → **Developer Mode ON**, then
   right-click `#trellis` → **Copy Channel ID**. This is your `TRELLIS_READ_SURFACES`
   value.

## Part C — configure trellis (the env contract `isolation.py` reads)

Set these where trellis will run (a `.env`, your shell profile, or the service
manager). Names must match exactly:

```sh
export TRELLIS_DISCORD_TOKEN="<the bot token from step 3>"   # secret; referenced by name only
export TRELLIS_READ_SURFACES="<the #trellis channel id>"      # comma-separated if more than one
export TRELLIS_ACT_SURFACES=""                                # EMPTY for now — trellis does not send yet
```

- Empty `TRELLIS_ACT_SURFACES` = trellis cannot post anywhere. Keep it empty until
  the executor is built and you explicitly arm it.
- Empty/unset allowlists = trellis is inert. That is the safe default by design.

## Part D — Google Drive transcripts (later, same shape)

Not built yet. When you want it: create a Drive folder that holds **only** the
transcripts trellis should read, copy its folder id from the URL
(`drive.google.com/drive/folders/<THIS_ID>`), and it will go in a
`TRELLIS_DRIVE_FOLDER` env var consumed by a `DriveTranscriptAdapter`
(implements the existing `SourceAdapter.discover()` seam). Read-only.

---

## What must be true before the first live Discord test

Do these **before** pointing anything at Discord — all safe, no live token needed:

1. **Build the read-only poller** (`ingest_scoped_discord` already exists; it needs
   a thin fetcher that maps the bridge/API's messages → `DiscordMessage`). Ship it
   with a **`--dry-run`** that prints what it *would* ingest without writing.
2. **Unit-test the poller against fakes** — including a fake batch that contains a
   non-allowlisted channel, proving it never lands (mirrors `test_isolation.py`).
3. **Decide the exact channel** (`#trellis`) and confirm the bot sees *only* it.
4. **Keep the model out of the first test.** The first milestone is pure ingest:
   does trellis pull its channel's messages into its ledger, correctly attributed,
   with nothing else leaking? No reasoning, no acting.
5. **Leave `TRELLIS_ACT_SURFACES` empty and the executor unbuilt.**

Then the first live test is narrow and reversible: read `#trellis` → confirm the
messages appear in trellis's ledger with the right `agent="trellis"` storage keys →
confirm nothing from any other channel is present. If that holds, we widen.

## Checklist

- [ ] A — trellis bot created, Public Bot off, Message Content Intent on
- [ ] B — invited with View Channels + Read Message History only; restricted to `#trellis`; channel id copied
- [ ] C — `TRELLIS_DISCORD_TOKEN` + `TRELLIS_READ_SURFACES` set; `TRELLIS_ACT_SURFACES` empty
- [ ] read-only poller built with `--dry-run` + tests (Claude)
- [ ] dry-run reviewed against the real channel
- [ ] first live test: read-only ingest of `#trellis`, verify isolation
- [ ] (later) Drive adapter; (later, gated) send executor
