# Plan — evidence-aware verification: a pass must mean the outcome held, not that a file exists

**Date:** 2026-07-20 · **Status:** PLAN — stress-tested before code.
**Source:** Codex infrastructure audit, Critical 4 (`docs/audits/AUDIT-2026-07-20.md`).

## The finding (real, reproduced)

`RuleVerifier` returns **VERIFIED** when it has only confirmed that evidence *exists* —
a file is present, a ledger id resolves, an output string is non-blank. Worse, a claim
supported **only** by an unopenable `external://` ref gets **VERIFIED**, because the
external check is marked `passed=True`, so the intended INSUFFICIENT branch is
unreachable. The name overclaims: "VERIFIED" reads as "the claim is true," but the
check was "the artifact exists." Trust then compounds on existence, not outcomes.

## The fix (honest, contained — no gate is weakened)

1. **A deterministic pass is `PRECONDITIONS_PASSED`, not `VERIFIED`, unless an OUTCOME
   was actually checked.** New `VerdictStatus.PRECONDITIONS_PASSED` = "the evidence is
   well-formed and openable, and every stated predicate held — but no claimed outcome
   was independently confirmed." `VERIFIED` is earned only when at least one **outcome
   predicate** passed and nothing failed.
2. **Outcome predicates.** `Evidence` gains `expect_hash` (file content sha256),
   `expect_contains` (substring in file/ledger-entry body), and `expect_kind` (a ledger
   entry is of the claimed kind). The RuleVerifier resolves and checks them — a real
   content check, not existence. A claim can now assert a *checkable outcome*.
3. **External-only → INSUFFICIENT** (the reproduced bug): an unopenable external ref is
   a non-passing "cannot open here" check; if it is the only evidence, the verdict is
   INSUFFICIENT, never VERIFIED.
4. **Trust counts honestly.** `trust_record` gains a `preconditions_passed` bucket;
   `verified_ratio` counts only true VERIFIED. `reflect.self_image_stats`: `checked`
   includes preconditions, `verified` counts outcome-verified only — so the glyph's
   warmth reflects real verification, not artifact existence.
5. **The self-change / proposal gates stay STRICT.** `reflect.apply_self_change` and
   `selfimprove.can_take_effect` still require an independent **VERIFIED** verdict — so
   to earn it, a self-change now attaches an outcome predicate (its cited ledger evidence
   is confirmed to be of the claimed kind, defeating the "any existing id" laundering).
   No gate is loosened; the bar is raised from "the id exists" to "the id is the evidence
   I claim it is."

## Invariants that must survive
- D4 maker ≠ verifier holds unchanged; the ASCII-identity allowlist is untouched.
- Append-only, attributed, bitemporal verdicts (D2). `record_verdict` records the new
  status like any other.
- The panel's refute-by-default quorum is unchanged; a PRECONDITIONS_PASSED floor does
  not short-circuit (only REFUTED does), so model lenses still decide.
- Existing callers that pass existence-only evidence keep working — they now land
  PRECONDITIONS_PASSED (honest) instead of a false VERIFIED; only the apply-gates, which
  demand VERIFIED, require the (additive) outcome predicate.

## Plan stress-test (before code)
| # | Attack | Verdict |
|---|--------|---------|
| 1 | Does external-only still verify? | Fixed → INSUFFICIENT; regression-pinned. |
| 2 | Can an existence-only claim still masquerade as VERIFIED? | No — it lands PRECONDITIONS_PASSED; trust no longer counts it. |
| 3 | Does the change weaken the self-change gate? | No — the gate still requires VERIFIED; earning it now requires an outcome predicate (a strictly higher bar). |
| 4 | Does an `expect_hash`/`expect_contains` predicate itself become a laundering vector (maker asserts a trivial substring)? | Advisory boundary, labelled: a predicate proves the content the maker *named* is present; it cannot prove the maker named the *right* thing — that is the model verifier's and the human's job. Still strictly stronger than existence. |
| 5 | Do panel / demo / glyph break? | Panel unchanged (floor only short-circuits on REFUTED). Demo + glyph updated to the honest counting; trust reflects outcome-verification. |

## What this does NOT do (named, honest)
Full evidence provenance (origin, signatures, tenant), reproducible command/exit-status
predicates, and calibrated trust-by-consequence are the larger evidence-resolver program
Codex describes — the next steps, not this increment. This increment stops the overclaim
and makes an outcome checkable.

*DECISIONS D25.*
