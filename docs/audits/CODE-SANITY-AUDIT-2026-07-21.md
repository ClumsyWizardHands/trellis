# Trellis pre–go-live code sanity audit

**Date:** 2026-07-21  
**Scope:** Concrete runtime defects immediately before connecting Trellis to live Discord and a real model. Architecture seams are excluded unless they produce a reproduced incorrect result or crash.  
**Method:** Read the project doctrine and workflow map, traced critical paths, ran the full baseline, and exercised focused throwaway repros. Every retained finding below is **CONFIRMED**.

## Baseline

- `pip install -e '.[dev,web]'` was repeated in an isolated virtual environment because macOS PEP 668 blocks writes to the system Python.
- `python -m pytest -q`: **358 passed**.
- `python stress/stress_test.py`: **10/10 attacks defeated**.
- `trellis doctor`: returned READY for the unconfigured checkout.
- `trellis demo`: repository-root state made it fail with `CollidingDecisionError`; an isolated fresh-copy repro confirmed the first invocation succeeds and the second fails.
- The audit left the worktree clean before this report was added.

## Critical

### 1. `trellis/stage.py:219` · A stale `Outbox` can fire after another process records a denial

**Status:** CONFIRMED

**Failure scenario:** Stage once; construct `a = Outbox(ledger)` and `b = Outbox(ledger)`; run `a.approve(id, "alice")`, then `b.deny(id, "bob", "do not send")`, then `a.fire(id, executor)`. The executor ran. Ledger order was:

```text
staged → approved → denied → firing → fired
```

**Root cause:** `fire()` authorizes from cached `a.status`, while `_fire_block()` rereads only `firing` and `fired` events.

**Root-cause fix:** Under the fire lock, reconstruct the latest ledger state and require its latest authoritative transition to be `approved`. Do not authorize from the instance cache.

### 2. `trellis/stage.py:184` · A failed approval append leaves the action fireable without any durable yes

**Status:** CONFIRMED

**Failure scenario:** Make `ledger.append` raise `OSError("disk full")` only for the `approved` event; call `box.approve(...)` and catch the exception; restore `append`; call `box.fire(...)`. The executor ran while the ledger contained zero approval events.

**Root cause:** `approve()` mutates `a.status` before `_log()` persists the transition.

**Root-cause fix:** Persist first, then mutate the cache. After any persistence failure, reload or roll back. `fire()` must independently rederive approval from the ledger.

### 3. `trellis/stage.py:268` · The staging agent can reconcile its own ambiguous send and cause a duplicate

**Status:** CONFIRMED

**Failure scenario:** An executor appended `"x"` to `sent` and then raised a timeout. `box.reconcile(id, human="witness", fired=False)` was accepted even though `created_by == "witness"`. Retrying produced:

```python
sent == ["x", "x"]
```

**Root cause:** `reconcile()` checks only blank/ASCII identity, not maker independence or authenticated human authority.

**Root-cause fix:** Apply the same authenticated-human and maker-not-equal-to-reconciler gate as approval.

### 4. `trellis/surfaces.py:112` · Any agent can mint a valid DM-to-public declassification token

**Status:** CONFIRMED

**Minimal repro:** `declassify(ledger, dm, public, approved_by="witness-agent", reason="agent decided")` returned a token, and `flow_with_token(...)` returned `True`.

**Root cause:** `approved_by` is an unauthenticated string despite the contract saying agents cannot authorize declassification.

**Root-cause fix:** Require a verified authority capability or authenticated principal from the trusted boundary, not a caller-supplied name.

## High

### 5. `trellis/ledger.py:193` · Concurrent corrections can fork one lineage into two live heads

**Status:** CONFIRMED

**Failure scenario:** Two threads were synchronized after both `_superseder_of(root)` checks returned `None`; both `correct(root, ...)` calls succeeded. `current("fact")` returned two heads, both superseding the same root.

**Root cause:** Supersession validation and append are a TOCTOU pair.

**Root-cause fix:** Serialize check-plus-append with the ledger write lock across threads/processes. Apply the same protection to `DecisionLog`’s question-key anti-fork.

### 6. `trellis/surfaces.py:66` · `storage_key()` is not injective

**Status:** CONFIRMED

`"-"` is used both as legal field data and as the missing-value sentinel:

```python
ConversationKey("trellis", Surface.CHANNEL, "chan", "").storage_key() \
    == ConversationKey("trellis", Surface.CHANNEL, "chan", "-").storage_key()
```

The same collision occurs for `thread=None` versus `ThreadRef(id="-", ...)`.

**Root-cause fix:** Encode optionality explicitly—length-prefix fields or tag them as absent/present—rather than substituting a legal field value.

### 7. `trellis/verify.py:218` · A maker’s own `run.ok()` label launders existence-only evidence into `VERIFIED`

**Status:** CONFIRMED

**Failure scenario:** Create an authentic `LoopRun`, call `run.ok("I assert success")`, then claim an unrelated production migration with only an existing empty file plus that `loop_run_id`. `RuleVerifier("independent", ledger).verify(claim)` returned `verified`.

**Root cause:** Recency and `loop outcome is ok` increment `outcome_checks`, even though the outcome is only the maker’s self-authored label.

**Root-cause fix:** Treat loop recency and the maker’s outcome label as provenance/precondition checks. Require predicates tied to the claimed artifact or result before returning `VERIFIED`.

### 8. `trellis/context.py:165`, `trellis/agent.py:208` · The prior read is never actually given to the model, and empty cycles record no manifest

**Status:** CONFIRMED

**Failure scenario:** Write a prior read containing `ULTRA_SECRET_PRIOR_FACT`; compilation produced only `(open read/prior.md...)`. A captured second Witness request did not contain the first cycle’s read body. Current providers are invoked without file-reading tools. Separately, `witness_cycle([])` ended `nothing_new` with zero `context_manifest` entries.

**Root cause:** The compiler loads ledger metadata about the read, not its content; `Witness._resolve()` skips compilation entirely when `subjects` is empty.

**Root-cause fix:** Load scoped workspace content or a bounded excerpt into the packet, and compile/record a manifest on every cycle, including zero-event cycles.

### 9. `web/app.py:36`, `trellis/cli.py:202` · `trellis web` ignores the `.env` created by `trellis init`

**Status:** CONFIRMED

**Failure scenario:** In a directory containing `.env` with a stable portal secret, human `alice`, and custom ledger, importing `web.app` yielded:

```json
{"ephemeral": true, "human": "operator", "ledger": "state/ledger.jsonl"}
```

**Root cause:** `web.app` initializes ledger/auth globals during import, while `cmd_web` never loads `.env`.

**Root-cause fix:** Load configuration before those globals are created. This must also work for the direct `trellis-web` entry point.

### 10. `trellis/agent.py:181` · Verification can crash after the cycle is durably recorded as OK

**Status:** CONFIRMED

**Failure scenario:** A valid opinion completed the loop; a verifier then raised `RuntimeError("verifier endpoint down")`. `witness_cycle` raised, the ledger contained `loop_run_end: ok`, and contained no verification record.

**Root cause:** The loop closes before verification begins.

**Root-cause fix:** Give verification its own typed outcome, or do not finalize the overall cycle as OK before verification finishes. Record verification failure before propagating it.

## Medium

### 11. `trellis/agent.py:247` · Plausible malformed structured output bypasses the retry and crashes later

**Status:** CONFIRMED

**Repro response:** A syntactically valid opinion with `"povs": ["not-an-object"]`. Parsing accepted it; `_to_decision()` raised `TypeError`; only one provider call occurred and the run became `protocol_violation`.

**Root-cause fix:** Validate nested field types, verdicts, and POV objects inside `_parse_opinions`, or include conversion in the retryable validation block.

### 12. `trellis/loops.py:87`, `trellis/agent.py:227` · `max_provider_calls=1` permits two provider calls

**Status:** CONFIRMED

**Failure scenario:** First reply malformed, second reply `[]`; the configured maximum was one, but actual and charged calls were two and the cycle ended `nothing_new`.

**Root cause:** The pre-call check uses `spent > max`, allowing another call when `spent == max`.

**Root-cause fix:** Enforce the next call prospectively with `>=` and immediately mark budget exhaustion after charging.

### 13. `trellis/panel.py:73` · Duplicate or empty verifier panels can manufacture quorum

**Status:** CONFIRMED

**Failure scenarios:**

- Lenses `("correctness", "correctness")`, quorum 2, produced two identical verifier IDs and `VERIFIED`.
- An empty panel with `quorum=-1` returned `VERIFIED`.

**Root-cause fix:** Require unique, non-empty lenses and `1 <= quorum <= len(unique_lenses)`.

### 14. `trellis/cli.py:81`, `trellis/providers/factory.py:50` · `doctor` can report READY for unusable configuration or crash with a traceback

**Status:** CONFIRMED

**Repros:**

- `TRELLIS_LEDGER=.` → exit 0 and `ledger path writable`, although `Ledger(".")` fails.
- A bogus Discord token plus one read surface → exit 0 and `OK Discord read`; no credential/reachability check occurred.
- `TRELLIS_MIN_CONTEXT=not-an-int` → uncaught `ValueError` traceback.

**Root-cause fix:** Open/probe the configured ledger itself, label Discord as unverified unless actually checked, and normalize configuration exceptions to a `FAIL` report with exit 1.

### 15. `trellis/providers/openai_compat.py:52` · Provider preflight succeeds when the configured model is absent

**Status:** CONFIRMED

**Failure scenario:** Local `/models` returned only `other-model`; the provider was configured with `configured-missing`; `preflight()` returned `{"ok": true, ...}`.

Malformed HTTP-200 payloads also escaped as raw `JSONDecodeError`/shape errors rather than a consistent provider failure.

**Root-cause fix:** Require the configured model to appear in the model list or return an explicit non-ready result. Normalize malformed responses to `ProviderUnavailable` without exposing secrets.

### 16. `trellis/stage.py:121`, `trellis/stage.py:136` · Durable outbox reconstruction drops authorization and routing metadata

**Status:** CONFIRMED

**Failure scenarios:**

- Stage an action with a DM `destination`; after restart, `Outbox(...).get(id).destination is None`.
- A web-style approved event reconstructs with `status == "approved"` but `approved_by is None`.

**Root-cause fix:** Persist and reconstruct the complete structured destination, and retain the lifecycle event’s ledger author as the transition actor.

### 17. `trellis/ledger.py:149` · A same-size in-place rewrite with preserved mtime leaves the cache stale

**Status:** CONFIRMED

**Failure scenario:** Cache a line containing `AAAA`; rewrite equal-length `BBBB`; restore the original `mtime_ns`. The existing `Ledger` returned `AAAA`; a fresh `Ledger` returned `BBBB`.

**Root-cause fix:** Include `ctime_ns` in the POSIX signature or maintain a content fingerprint for the immutable prefix. Size, inode, and mtime cannot detect a preserved-mtime rewrite.

### 18. `web/views.py:189` · The portal inflates trust by omitting `PRECONDITIONS_PASSED` from its denominator

**Status:** CONFIRMED

**Failure scenario:** One verified verdict plus 99 precondition-only verdicts produced core `verified_ratio = 0.01`, but the portal reported `trust = 1.0`, total 1.

**Root-cause fix:** Derive the portal value from `verify.trust_record()` or count every verdict status consistently.

## Low

### 19. `trellis/cli.py:190`, `examples/run_witness.py:28` · The advertised demo is repository-dependent and cannot be run twice

**Status:** CONFIRMED

**Repros:**

- Installed `trellis demo` outside the checkout exits 1 because `examples/run_witness.py` is not packaged.
- In a fresh copied example directory, the first run exited 0 and the second exited 1 with `CollidingDecisionError` against its persisted `.state`.

**Root-cause fix:** Package the demo implementation/data and make each invocation use isolated state or idempotently resolve its existing demo decisions.

## Go-live verdict

**Trellis is not safe to wire to live Discord yet.** Findings 1–4 are immediate blockers: they permit sends against or without durable human authorization, duplicate sends after agent-authored reconciliation, and agent-authorized private-to-public flow. Before trusting the resulting record, also block on the ledger correction race, verification laundering, missing prior-read content, ignored web `.env`, and the post-OK verification crash. The remaining findings should be fixed before unattended use, but they are secondary to those authorization, privacy, and truth-integrity failures.
