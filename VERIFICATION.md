# VERIFICATION — how this repo was checked (not by its maker alone)

The doctrine this repo enforces was applied to the repo itself: **a self-audit
is not an audit.** Three layers, in order of increasing independence.

## Layer 1 — deterministic suite (the floor)

`python3 -m pytest` — **66 tests**, structured as the acceptance checklist from
the baby EMP (see ACCEPTANCE.md: the ten unforgivables mapped to named tests).
Zero network, zero API keys, deterministic clock — a time bug cannot hide
behind a real clock.

## Layer 2 — adversarial stress (the attack)

`python3 stress/stress_test.py` — **10 scenarios, each trying to BREAK a
refusal**, with recorded evidence in STRESS-REPORT.md (deterministic seed;
numbers reproduce). Highlights: 200 chaotic loop runs with injected crashes and
silent wanderings → 0 unrecorded outcomes; 5,000 fuzzed privacy flows → 0
DM-to-public leaks without a token; 400 disguised self-audit attempts → 400
refused; 8 threads × 500 concurrent ledger appends → 0 lost, file readable.

The stress suite earned its keep during the build: it caught a real Workspace
path bug and a parser crash the unit tests missed. Both fixes carry comments
naming the suite as the finder.

## Layer 3 — independent fresh-eyes review (the audit)

A separate agent with fresh context — not the builder — was instructed to
**refute** the repo's claims (2026-07-15). It verified the headline claims by
running everything itself, then found **five live defects**, including a
genuine bypass of the self-approval gate. All five were fixed and pinned as
regression tests in `tests/test_review_regressions.py`:

| Severity | Finding | Fix |
|----------|---------|-----|
| HIGH | Disguised self-approval: `"WITNESS:A"` / `"witness:a."` approved the staging agent's own action | one shared identity normalization (`identity.py`), used by every independence gate |
| HIGH | A naive (no-timezone) `revisit_at` on a T crashed the hidden-no query for the whole board | refused at mint, like every other timestamp |
| MEDIUM | A whitespace-only verifier-model reply crashed verification instead of landing as INSUFFICIENT | blank replies are INSUFFICIENT, never a crash |
| MEDIUM | CLI↔DM cross-human flow leaked (both rank-3 private surfaces) | private surfaces of different humans never cross, in any combination |
| LOW-MED | A malformed pass file (turd-drop) loaded fine from the synced exchange dir, bypassing creation-time validation | validation runs on load too — the file is the trust boundary |
| LOW | Pass lifecycle recorded actors but didn't authorize them | only the sender/receiver may perform their side's transitions |

The review also confirmed portability (macOS, Python 3.10+; no 3.11-only
syntax; core is stdlib-only) and that ACCEPTANCE.md's 28 test mappings are
real, not decorative.

## What is verified, and what is not — said plainly

Verified: the **harness** refuses the recorded failure modes, structurally,
under attack, on this suite. Not verified (and not claimable): that any
*model* seated in the harness is wise, that a live Discord deployment behaves,
or that these refusals cover failure modes not yet on the record. The gap is
by design the human's seat: staged actions wait for you, trust compounds
per-maker in the ledger, and the friction register grows as new burns are
recorded.

To re-verify after any change: `python3 -m pytest && python3 stress/stress_test.py`.
If you change a refusal, add the attack that would have caught the old behavior
first — that's how every guard in here got built.
