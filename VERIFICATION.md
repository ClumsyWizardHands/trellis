# VERIFICATION — how this repo was checked (not by its maker alone)

The doctrine this repo enforces was applied to the repo itself: **a self-audit
is not an audit.** Three layers, in order of increasing independence.

## Layer 1 — deterministic suite (the floor)

`python3 -m pytest` — **the acceptance suite** (current count on the CI badge), structured as the acceptance checklist from
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

## Layer 3.5 — the 50-agent adversarial gauntlet (iterated to convergence)

On 2026-07-15 the harness's own doctrine — adversarial external verification —
was run *against the harness*, at scale, in rounds. Each round: N independent
subagents, each assigned one narrow attack, each writing and running a real
breaker script, each claimed break independently re-derived by a second agent.

| Round | Attackers | Breaks found | Nature |
|-------|-----------|--------------|--------|
| 1 | 50 | **19** (2 high) | first-pass holes a solo builder can't see: homoglyph bypasses, whitespace evasions, a fork in the ledger, an unbounded schedule wrap |
| 2 | 19 (re-attack the fixes) | **11** | my fixes were too shallow — mostly ONE root cause (invisible-char handling covered only Unicode categories Z/C) |
| 3 | 11 (re-attack the root fixes) | **9** | deeper + more exotic: Cyrillic Palochka 'l', a zero-width char *inside* a keyword, an object whose `__repr__` itself raises |
| 4 | 6 (structural only) | **5** (1 real, rest my over-corrections) | #42 ordering bug (real); identity over-folding (my fix merged real names — corrected to an ASCII allowlist); dotted-soul-filename; + advisory tuning |
| 5 | 13 (the memory-as-navigation build) | **4 confirmed** (2 high, 2 med) | attacked Phase 2's new code: a `resolve()` cross-key fork, a validity-retired head served by a length-keyed cache, a homoglyph outside the confusable table, and an `active(at=<past>)` that returned two live heads. All fixed at the root and regression-pinned; a 5th (raw `ledger.append` bypasses the domain guard) was ruled by-design and documented. |

**Convergence, called at round 4.** The structural refusals are now airtight and
regression-pinned: silent failure is impossible even when an exception's own
`__repr__` raises; self-certification is closed by an **ASCII-identity allowlist**
(exotic ids are refused, not folded — which also stopped my round-3 fix from
wrongly merging distinct real names like `мир` and `mir`); ledger integrity,
blank-author refusal, bounded loops, and privacy keying all hold. What still
"breaks" under attack is only the **advisory heuristics** — the embodiment/soul
linter, pass-substance, synthesis-justification — which *cannot* converge against
unlimited exotic Unicode or semantic padding. Continuing to run rounds on those
would be the perfectionism failure the harness is built against. They are
improved once, labeled advisory, and backed by the real gates: an identity
allowlist and human review. **222 tests, 10/10 stress.** Adversarial testing
never "ends" — it reaches diminishing returns, and this is that point.

**Round 5 (2026-07-17) applied the same discipline to a whole new subsystem** —
the memory-as-navigation build (titles, WALK/REOPEN/DECIDE, validity/retirement,
fold-not-clobber, the reflection ritual). 13 agents attacked it; 4 real flaws
were confirmed and fixed at the root (the anti-fork now holds on a homoglyph-
folded question-key even through `resolve()`; the resolved-head cache is keyed on
validity-that-can-elapse, not just ledger length; `active()` is now-only so no
past query returns two heads). The plan for this build was *itself* adversarially
stress-tested (8 agents, 4 flaws) and hardened **before** any code was written —
the harness's doctrine applied to its own blueprint.

**Round 6 (2026-07-17) attacked the reflection self-modification gate** — the
highest-stakes new surface. It found a real HIGH: a self-change with no ledger
evidence fell back to maker-authored OUTPUT evidence, which the deterministic
verifier only checks for non-emptiness — so an ungrounded change could "verify"
on its own rationale. Fixed: a self-change must cite openable ledger evidence or
it stays unverified. The gate was further hardened to **re-derive** its verdict
from the append-only record (an independent `verification` entry for the claim),
never trusting the reflection body's own `verified` flag. Both pinned. The round
also caught a second HIGH — the once-daily cadence keyed off the caller-supplied
`event_time`, so a future-dated reflection could wedge the schedule forever (or a
back-dated one over-fire); fixed by keying `due()` off the harness-owned
`write_time` (clock.py's "the harness owns time" premise). Pinned.

**Round 7 (2026-07-17) took the same discipline to the contemplative backdrop** —
the ingestion spine, the observation/opinion model, the reconciled vault, and the
anti-satisficing curiosity loop. The **plan** was stress-tested first (6 lenses,
22 candidates → 5 real problem-clusters: vault≠ledger reconstructability, two-node
identity collision, provenance laundering, ingestion determinism, "two questions a
day" as a checkmark) and hardened *before any code*. Then the **code** was attacked
(8 agents): 5 real flaws confirmed and fixed at the root — an opinion-T crashing a
half-written pair; resume leaking orphaned partial derived entries; two decisions
colliding on one stable id; a time-corrected re-dump looking brand-new; and —
the sharpest — `curiosity.resolve()` closing a question as "understood" on a DRY
seek or the question's own entry (the exact "I searched → I understand" laundering
the module exists to forbid). All pinned. **222 tests, 10/10 stress.**

**Round 8 (2026-07-17) — an external audit turned on the seams between modules and
the web surface** (the unit tests cover each module in isolation; fewer cover the
cross-module and UI write paths). The floor held under attack: the ledger's five
refusals, the anti-fork on the question-key, the two-node observation model,
ingestion idempotency + crash/resume, the vault reconciler, and the reflection
gate all survived their breakers, and a full contemplation-day flow reconstructed
correctly across three process restarts from the file alone. Three real defects
were confirmed (each independently re-derived by a second agent from a fresh
reading) and fixed at the root, regression-first:

- **HIGH — refusal #5 bypass on the actual approval surface.** The web `/approve`
  and `/deny` endpoints wrote the authoritative `staged_action` lifecycle event
  (the one `views.inbox()` reads as truth) **without** the independence guard the
  library `stage.Outbox.approve` enforces — so the staging agent could self-approve
  its own outbound action through the UI. Fixed: `views.approval_guard` (named
  human + maker ≠ approver, identity-normalized) gates every web approve/deny;
  `/affirm` rejects a blank human with 400 instead of a 500.
- **HIGH — refusal #5 bypass via homoglyph, in the core.** `stage.Outbox.approve`
  used only `same_identity(human, created_by)`, which deliberately does not fold
  confusables — so a staging agent `witness` could self-approve as `witnеss`
  (Cyrillic е). The ASCII-identity allowlist (`identity.require_identity`) that
  closes this for the *verification* gate (`verify._guard_independence`) was never
  wired into the *approval* gate. Fixed: `approve`/`deny` (and the web guard) now
  require an ASCII identity — an exotic id is **refused, not reasoned about**,
  parity with the verifier gate.
- **MEDIUM — a satisficing hole in `curiosity.resolve()`.** Closing a question
  accepted **any** live decision that merely postdated it, even one about an
  unrelated topic ("I made some unrelated move, therefore I understand this") —
  the same laundering the module forbids, one step removed. Fixed: the cited
  map-move must appear in the `delta_refs` of a **non-dry seek of this assumption**,
  tying the close to a recorded pursuit of *this* question. Honest boundary: the
  seek is a self-report, so this is a strictly higher bar (a durable false record)
  rather than an airtight proof — labelled advisory in the code, with the human
  reading the cited seek+delta as the real backstop.

Also confirmed as an **honest advisory boundary, not a fix**: a single malformed
observation candidate (an opinion-T with no POVs) raises loudly out of
`Ingestor.ingest` — intended fail-loud, pinned by
`test_opinion_T_without_povs_leaves_no_half_written_pair` — but the raise aborts
the whole batch and the item re-crashes on every resume. Whether to isolate
per-candidate failures (record-and-continue, as the accept=False path already
does) is a **decision for the human**, since it changes that pinned test's
expectation. **225 tests, 10/10 stress.**


The count falling 19 → 11 → 9 is the point: not a harness that was never broken,
but one broken **cheaply, in the open, and closed at the root** each round. The
most valuable output was not the patches — it was the round-3 realization that
the findings split into two kinds:

- **Structural refusals** (silent failure, self-certification, blank authors,
  ledger integrity, unbounded loops) — these can be made *airtight*, and were.
- **Heuristic quality-lints** (the embodiment linter, pass-substance, synthesis
  justification) — these *cannot* be made adversarially complete: an unbounded
  blocklist against exotic Unicode is unwinnable, and no lexical test measures
  semantic substance. Pretending otherwise would be the exact overconfidence
  the harness forbids. So they are improved once, then **honestly labeled
  advisory**, with the real gate placed where it belongs: a **charset allowlist
  for identities** (an id must reduce to a valid ASCII identifier or it is
  refused — not an ever-growing homoglyph table) and **human review** for
  content (a malicious EMP is caught by the human who reads it, not by a lint).

That separation — knowing which guarantees are structural and which are
best-effort, and saying so — is the mature form of the harness.

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
