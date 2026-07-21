# Codex audit prompt — pre-go-live code sanity check

> Paste everything below the line into Codex, run from the repo root. Its job is
> narrow and concrete: **find the bugs that will break this when it actually runs.**
> Not architecture, not philosophy — real defects, with reproductions.

---

You are auditing `trellis`, a zero-dependency Python agent harness, immediately
before it is wired to a live Discord + a real model for the first time. Your job is
a **rigorous code sanity check**: find hidden bugs, edge cases, and fragilities that
will surface in real use and break something. Concrete defects with reproductions —
not design opinions (a separate architecture audit covers that).

## What trellis is (30 seconds)

An append-only, bitemporal `ledger.jsonl` is the source of truth. The "Witness" runs
sense→resolve→act→verify→remember. Five structural refusals are enforced *in code*
(they raise, they don't remind): no silent failure, no self-certification
(maker≠verifier), no soul/embodiment, no naked `now()` (bitemporal), no auto-fire
(stage-for-human). The core imports no third-party package; optional adapters
(providers, web) lazy-import and fail loud.

## Orient (read first)

- `README.md`, `DECISIONS.md` (D1–D30), `ACCEPTANCE.md`, `VERIFICATION.md`.
- Module docstrings across `trellis/*.py`. Prior AI-written map:
  `docs/audits/WORKFLOW-MAP-2026-07-21.md` — **treat as a lead to verify, not truth.**
- Run it: `pip install -e '.[dev,web]'` → `python -m pytest` (expect ~358 passing) →
  `python stress/stress_test.py` → `trellis demo` → `trellis doctor`.

## Where to concentrate (the code that will actually run when it goes live)

Prioritize the hot paths + the newest, least-exercised code:

1. **The ledger** (`ledger.py`) — the append-only + bitemporal guarantees, the read
   cache with its stat-signature invalidation (`_sync_locked`), concurrent
   readers/writers over a shared file, partial/torn writes, rebuild-from-file
   correctness, replacement/shrink/same-size-rewrite detection.
2. **Durable outbox** (`stage.py`) — the fire state machine: idempotency, the POSIX
   advisory fire-lock, crash mid-fire → `UNKNOWN`/`FIRING` reconcile, double-fire
   impossibility, approver-independence gate. Try to make it fire twice or lose a yes.
3. **Isolation** (`isolation.py`, `surfaces.py`) — can a non-allowlisted surface ever
   reach the ledger? Can the injective `storage_key` collide? Can privacy-flow
   (`can_flow`/`declassify`) be bypassed? Can a DM be filed as a channel?
4. **The new install groundwork** (`config.py`, `providers/factory.py`, `cli.py`) —
   `.env` parsing edge cases, `provider_from_env` failure modes (does it ever silently
   return Mock?), `trellis init` never clobbering a real `.env`, `doctor`'s exit-code
   contract, secret values never landing in logs/`repr`/ledger, zip-safe (no-git) paths.
5. **The witness cycle + loops** (`agent.py`, `loops.py`) — a run that can exit without
   a typed outcome (refusal #1), budget accounting, exceptions escaping the `finally`,
   the context compiler (`context.py`) recording each cycle.
6. **Verification** (`verify.py`, `panel.py`) — maker==verifier slipping through,
   empty-predicate holes, `PRECONDITIONS_PASSED` vs `VERIFIED` conflation.
7. **Providers** (`providers/openai_compat.py`, `claude_sdk.py`) — request/response
   parsing, timeouts, the preflight honesty, failure surfaces when a real endpoint
   misbehaves (malformed JSON, 4xx/5xx, empty choices, tool-call parsing).
8. **The portal** (`web/app.py`, `web/views.py`, `auth.py`) — auth/session integrity,
   the approve/deny write path, any unhandled exception that 500s or crashes, SSE loop.

## Bug classes to hunt

Unhandled exceptions that crash the loop; silent failures (ironic here — flag them);
race conditions / TOCTOU on the ledger and outbox; resource leaks (files, locks);
integer/`None`/empty-collection edge cases; time-zone / naive-datetime slips;
off-by-one in bitemporal ordering or supersession; encoding/escaping bugs in
`storage_key` or vault frontmatter; path traversal / workspace escape; secret leakage;
idempotency-key gaps; state left inconsistent after a partial failure; anything that
passes tests but breaks on real, messy input.

## Method (and honesty bar)

- **Reproduce every finding.** A claim without a repro (a failing snippet, a command,
  a test) is a suspicion — label it `SUSPECTED`, not `CONFIRMED`. Don't self-certify.
- Write throwaway scripts / tests to try to break the invariants; actually run them.
- Prefer root-cause over symptom. If you propose a fix, it must preserve append-only,
  bitemporal, and the five refusals — never weaken an invariant to make a test pass.
- No false alarms and no padding. A short list of real bugs beats a long list of maybes.

## Output

A severity-ranked list (Critical / High / Medium / Low). Each finding:
`file:line` · one-line claim · concrete failure scenario (inputs → wrong result/crash)
· `CONFIRMED`/`SUSPECTED` · minimal repro · root-cause fix. End with a one-paragraph
**go-live verdict**: is this safe to run against a real Discord + model, and if not,
which findings are blockers?
