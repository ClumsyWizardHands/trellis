# Plan — the durable outbox: refusal #5 survives a crash, and nothing fires twice

**Date:** 2026-07-20 · **Status:** PLAN — stress-tested before code.
**Source:** Codex infrastructure audit, Critical 3 (`docs/audits/AUDIT-2026-07-20.md`).

## The finding (real, reproduced by Codex)

The outbox keeps staged actions in an **in-memory dict**; the ledger holds only a
280-char *preview* and the approval events. Three consequences:

1. **Split-brain** — the web UI records an approval to the ledger that the in-memory
   outbox never sees (I closed the web self-approval half of this last session; the
   durability half is still open).
2. **No survival across a restart** — a fresh process cannot reconstruct what was
   pending or approved: the full payload is gone, only a preview remains.
3. **Double-fire on retry** — `fire()` calls the executor and *then* records "fired",
   with no idempotency. If the remote accepts but the local call throws, the action
   stays `approved` and a retry **sends it again**. For an agent whose one promise is
   "nothing reaches a stakeholder unless you meant it", sending a CEO the same draft
   twice is the exact failure it exists to prevent.

## The fix — event-sourced, reconstructable, idempotent

The **ledger is the single source of truth**; the in-memory dict becomes a rebuildable
cache. Concretely:

1. **Persist the full payload** at stage time (content, target, kind, `created_by`, a
   `content_hash`, and an `idempotency_key`) — not a preview. So the outbox is
   reconstructable from disk alone.
2. **`_load()` on construction** rebuilds every action's current status + payload from
   the ledger's `staged_action` events (payload from the `staged` event, status from the
   latest event). A fresh process — and the web UI, and the executor — all read the
   *same* store. Split-brain closed by construction.
3. **A state machine with an in-flight and an ambiguous state:**
   `staged → approved → firing → fired`, plus `denied` and — the key addition —
   **`unknown`** (the remote may or may not have received it).
4. **Idempotent fire:** `fire()` refuses if a `firing`/`fired` event already exists for
   the action (already in-flight or done → no blind retry). It writes a **`firing`**
   intent *before* calling the executor; on success → `fired`; on executor exception →
   **`unknown`** (durably recorded, NOT auto-retryable). A human `reconcile()`s an
   `unknown` to `fired` (it went out) or back to `approved` (it didn't; safe to retry).
   The `idempotency_key` rides to the executor so a destination that supports dedup gets
   true exactly-once.

## Invariants that must survive
- **Refusal #5 unchanged and strengthened:** nothing fires without a human `approved`
  event; the independence guard (`_require_approver`, ASCII-allowlist) is untouched and
  now also gates `reconcile`. The guarantee now holds *across a restart*, not just within
  one process.
- Append-only, attributed, bitemporal (D2): every transition is a ledger event; the
  in-memory dict never becomes the authority.
- The existing API (`stage/approve/deny/fire/pending`) and the web integration
  (`views.inbox`, `approval_guard`) keep working — the outbox now *reads the ledger the
  web already writes*.
- Core stays zero-dependency.

## Honest boundary (stated, not hidden)
True end-to-end exactly-once depends on the **destination**: if Discord/email honours an
idempotency key, a retry is a no-op; if it doesn't, the best any harness can do is **fire
at most once and surface `unknown` for a human** when the outcome is ambiguous. trellis
guarantees the *local* discipline (persist, single truth, no blind retry, reconcile the
ambiguous); it cannot unilaterally make a remote service deduplicate. That line is the
honest limit, and the `unknown` state is where it lives.

## Plan stress-test (before code)
| # | Attack | Verdict |
|---|--------|---------|
| 1 | Restart mid-life: stage+approve, drop the process, new Outbox(ledger) — is it still approved & fireable, with full content? | Fixed by `_load()`; regression-pinned. |
| 2 | Crash between remote-accept and local `fired`: retry `fire()` — double-send? | Refused: a `firing`/`fired` event already exists → no re-fire; the ambiguous case lands `unknown`, reconciled by a human. |
| 3 | Web approves, in-memory outbox never saw it (split-brain) | Closed: the outbox reads the same ledger the web writes. |
| 4 | Fire an unapproved / denied / already-fired action | Refused (status gate + idempotency). |
| 5 | Self-approve / homoglyph-approve across the durable path | Unchanged guard (`_require_approver`); still refused. |
| 6 | Executor raises — is the action silently stuck approved (retryable = double-fire)? | No: it lands `unknown` (durable), not `approved`; only a human `reconcile()` moves it. |

*DECISIONS D26.*
