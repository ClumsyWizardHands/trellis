# Set up trellis on your machine

trellis is a standalone, **bring-your-own-credentials** harness. You clone (or unzip)
it, point it at *your own* accounts, and it runs locally. The core has **zero runtime
dependencies**; every capability is opt-in. A fresh install is **inert** — it touches
nothing but its own offline demo until you configure a surface.

Works identically from a `git clone` or a plain downloaded `.zip` — nothing here
depends on git.

---

## Quick start (3 commands)

```sh
pip install -e .        # zero-dependency core
trellis init            # scaffold .env (+ a generated portal secret) and state/
trellis doctor          # honest readiness check — what's configured, what's reachable
```

Prove it runs before connecting anything:

```sh
trellis demo            # a full witness cycle, offline, no accounts (MockProvider)
```

Then edit `.env`, re-run `trellis doctor` until the lines you care about are `✓ OK`,
and launch the portal:

```sh
pip install -e '.[web]'
trellis web             # read-only comprehension & reflection portal on 127.0.0.1
```

---

## Pick a model seat

Set `TRELLIS_PROVIDER` in `.env` to **one** of:

| `TRELLIS_PROVIDER` | What it is | You provide | Install |
|---|---|---|---|
| `mock` | offline, deterministic, no accounts | nothing | core |
| `local` | any OpenAI-compatible endpoint — **Gemma via Ollama**, LM Studio, llama.cpp, vLLM | `TRELLIS_LOCAL_BASE_URL`, `TRELLIS_LOCAL_MODEL` | core (stdlib) |
| `openai` | hosted OpenAI | `OPENAI_API_KEY`, `TRELLIS_OPENAI_MODEL` | core (stdlib) |
| `claude` | Claude Agent SDK | your **Claude Max subscription** (`claude login`) *or* `ANTHROPIC_API_KEY` | `pip install -e '.[claude]'` |
| `codex` | official OpenAI **Codex CLI** | your **ChatGPT subscription** (`codex login`) — no API key | install the Codex CLI |

Local Gemma example: run `ollama serve`, `ollama pull gemma3`, then set
`TRELLIS_PROVIDER=local`, `TRELLIS_LOCAL_BASE_URL=http://localhost:11434/v1`,
`TRELLIS_LOCAL_MODEL=gemma3`. `trellis doctor` will probe it and report context honesty.

> **Run it on your Claude Max subscription (no API key).** The `claude` seat uses the
> Claude Agent SDK, which authenticates with your subscription the same way Claude Code
> does — this is a supported path (it is reverse-engineering the raw OAuth endpoints, which
> trellis does NOT do, that carries ToS risk). Two ways:
> - **Interactive:** run `claude login` once; set `TRELLIS_PROVIDER=claude` and leave
>   `ANTHROPIC_API_KEY` unset. The SDK uses your subscription automatically.
> - **Unattended (best for the always-on runner):** run `claude setup-token`, then set the
>   printed `CLAUDE_CODE_OAUTH_TOKEN` (a ~1-year token — no periodic re-login).
>
> `trellis doctor` reports which credential the seat will use and refuses READY only when it
> finds none. An `ANTHROPIC_API_KEY`, if set, takes precedence (per-token API billing).

> **Run OpenAI on your ChatGPT subscription (no API key)** — set `TRELLIS_PROVIDER=codex`.
> trellis shells out to OpenAI's **official Codex CLI** (the way the `local` seat shells out
> to Ollama); Codex owns the login and credential, trellis never touches them. Sign in once:
> - **Interactive:** `codex login` (Sign in with ChatGPT — uses your Plus/Pro subscription)
> - **Headless:** `codex login --device-auth`
> - **API key instead:** `printenv OPENAI_API_KEY | codex login --with-api-key`
>
> Caveat: Codex is a coding *agent*, not a bare chat model — heavier and more tool-shaped
> than the other seats. It is the honest path to "use my OpenAI subscription without a key".

## Connect surfaces (all optional, all independent)

- **Obsidian** — set `TRELLIS_VAULT_PATH` to a folder in your vault (e.g. `~/Obsidian/MyVault/trellis`). No credential; it's just a path. Writes are containment-checked, so trellis can only write inside it.
- **Discord** — create *your own* bot and follow [`SETUP-ISOLATED-DISCORD.md`](SETUP-ISOLATED-DISCORD.md). Set `TRELLIS_DISCORD_TOKEN` and `TRELLIS_READ_SURFACES` (channel ids you want read). Leave `TRELLIS_ACT_SURFACES` **empty** — the send path is deliberately unbuilt.
- **Google Drive** — planned (`.[google]` extra); env keys are stubbed in `.env.example`, adapter not built yet.

> The live ingestion loop that continuously polls these surfaces is the next build. Today
> the wiring, config, isolation, and the offline harness are in place; `doctor` tells you
> exactly what is and isn't ready — it never claims a surface works when it can't reach it.

---

## If you are an AI assistant setting this up for someone

Deterministic steps — safe to run; nothing sends or spends until a human fills secrets:

1. `pip install -e .` (add extras only as the chosen model/surface needs them).
2. `trellis init` — creates `.env` from `.env.example`. **Do not invent secret values.**
3. Show the human `.env` and ask them to paste their own token(s)/key(s). You reference
   secrets by env-var **name**; never type or guess a real credential.
4. `trellis doctor` — read the report back to the human; fix `✗ FAIL` lines, explain
   `· SKIP` lines (not configured) and `! WARN` lines.
5. `trellis demo` to prove the harness runs offline.
6. Stop there unless the human asks to go live. Never set `TRELLIS_ACT_SURFACES` or build
   a send path without an explicit human "arm it."

---

## Security posture

- **Inert by default.** Empty allowlists = touch nothing; empty `TRELLIS_ACT_SURFACES` = cannot send; the send executor is unbuilt. A fresh clone can only run the offline demo.
- **Secrets never in the repo.** `.env`, `state/`, and credential JSON are gitignored; only `.env.example` (placeholders) is committed. Secrets are read by name on demand and never written to the ledger or logs.
- **Portal auth** is a signed session (not a form field); if you don't set `TRELLIS_APPROVER_SECRET`, the portal prints a one-time console token at boot. Bind to `127.0.0.1` (the default); never expose it on `0.0.0.0` without TLS and a stable secret.
- Before pushing to a public repo, `trellis doctor` will hard-fail if your `.env` is tracked by git.
