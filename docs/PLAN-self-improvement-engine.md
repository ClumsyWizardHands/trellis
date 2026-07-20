# Plan — the self-improvement engine: a mind that proposes its own repair, never applies it

**Date:** 2026-07-20 · **Status:** PLAN — stress-tested here *before any code*, the way
trellis plans (see `PLAN-integration-v0.2.md`, `PLAN-contemplative-ingestion.md`).
**Rule:** a self-improving agent is the single most doctrine-sensitive thing this
project can build. The plan is attacked before it is built, and the invariants win
every tie.

This is Alex's ask (2026-07-20): *"infrastructure and a process for the agent to
constantly think about ways to improve itself… Could this thing that came up in
conversation be a skill? Is there already a skill? Where did I get confused today?
What did Brett or Sarah post? If it's a skill from a YouTube short should we add it?
Why? Recursively improve itself all the time."*

## 0. The one line that keeps this honest

> **The agent improves itself continuously; it never *changes* itself without an
> independent verified verdict AND a human's yes.**

"Recursively improve itself all the time" is a real and good ambition — but it can
**not** mean the agent edits its own EMP, installs its own skills, or rewrites its own
process. Every one of those is a self-change, and trellis already has the law for
self-change: `reflect.SelfChange` is *staged, independently verified, and human-gated*
(`apply_self_change` refuses to take effect without an independent `verification` entry
on the record). The engine's entire safety core therefore **already exists**. This plan
composes existing primitives into a standing loop whose only output is a **queue of
staged, verified, human-ratifiable improvement proposals** — it does not invent a new
authority for the agent over itself.

## 1. Why trellis is almost uniquely built for this

Every other "self-improving agent" story skips exactly the two gates trellis makes
structural: **independent verification (maker ≠ verifier)** and **human ratification
(stage-don't-fire)**. An agent that proposes improvements, cites its evidence, has a
*different* checker confirm the evidence is real, and waits for a human to ratify — that
is the difference between compounding trust and a runaway. The engine is the contemplative
backdrop (D19–D22) turned on the agent's *own operation* instead of the team's record.

Each of Alex's questions is already a primitive; the engine is composition, not new machinery:

| Alex's question | The primitive it becomes |
|---|---|
| "constantly think about ways to improve itself" | `reflect.py`'s ritual, generalised: `SelfChange` → a typed `ImprovementProposal`, staged + verified + human-gated (unchanged safety core). |
| "where did I get confused today?" | Confusion is a **burn → the friction register** (`EMP.friction`). A daily *confusion harvest* appends attributed, transcript-grounded friction the next prompt reads. |
| "is there already a skill for this?" | **Memory-as-navigation applied to a capability estate** — `navigate.search_titles` + the anti-fork, pointed at skills, so we dedup before proposing. |
| "could this be a skill?" | A **Y/N/T decision node**: subject = "make X a skill"; if Y, a *human* authors/installs it (W1). |
| "what did Brett or Sarah post?" | `ingest.position_history` already does attributed, time-ordered, staleness-tagged recall; the engine watches team posts for improvement signal. |
| "YouTube-short skill — add it? why?" | **W1 doing its job**: external skills default-N; the T-grammar *forces* the "why" (named POVs, the missing piece, an owner, a revisit). Structurally never an auto-install. |

## 2. Invariants that MUST survive (the regression contract)

If a phase breaks one of these, the phase is wrong, not the invariant.

1. **No self-application.** An `ImprovementProposal` NEVER mutates the EMP, the skill set,
   the prompt, or any config. It records a proposal; taking effect is a *separate*
   human-in-the-loop step behind the existing verified gate. (Refusal #5, D18, W3.)
2. **No self-certification.** The proposal's evidence is confirmed by a verifier that is
   **not** the proposing agent (D4, `verify._guard_independence`, the ASCII-identity
   allowlist hardened 2026-07-17).
3. **W1 holds — no auto-installed skills.** "Add this skill" is a *default-N* Y/N/T
   requiring named POVs + missing-piece + owner + revisit; the human installs. Adding a
   skill from an untrusted source (a YouTube short) is the exact 824-malicious-skills
   supply-chain case W1 refuses.
4. **Confusion is functional, never performed.** The confusion harvest records *burns*
   ("I mis-resolved X because the read lacked Y"), which pass the dread-lint — it must not
   become "I feel inadequate." (D13, `emp.lint_mortality`.)
5. **Everything append-only, attributed, bitemporal.** Proposals, harvests, and skill
   nodes are ledger entries with authors and stamps; a proposal that is later withdrawn is
   retired, not deleted (D2, D15).
6. **Memory is navigation.** The skill estate is 00-grade titles walked to, anti-forked on
   a stable capability key, never a bulk dump (D14, D16).
7. **Core stays zero-dependency**; any model call is behind the `Provider` seam.

## 3. Architecture — three additive layers on the existing spine

```text
   the day's ledger slice (what the agent did, where it stumbled, what the team posted)
                    │
          ┌─────────┴───────────┐
          ▼                     ▼
   CONFUSION HARVEST        SIGNAL WATCH
   (burns → friction)    (team posts, corrections,
          │               dry-streaks, refutations →
          │                improvement-worthy signals)
          └─────────┬───────────┘
                    ▼
        THE IMPROVEMENT CURIOSITY LOOP
   (a first-class question: "what should I change about how I work?"
    — staleness-railed like any curiosity; a dry pass is not progress)
                    │
                    ▼
         IMPROVEMENT PROPOSALS  (typed, staged)
   target ∈ {emp:friction, emp:principle, process, skill:add,
             skill:retire, prompt, loop-config}
                    │
             ┌──────┴───────┐
             ▼              ▼
   SKILL ESTATE lookup   INDEPENDENT VERIFIER
   (dedup: "already a     (maker ≠ verifier;
    skill?" via titles)    evidence must be openable)
                    │
                    ▼
              STAGED for a human — the Reflection/Improvement page
              shows each proposal, its evidence, its verdict; a human
              ratifies (installs the skill, edits the EMP) — or denies.
```

### 3.1 Layer A — the confusion/friction harvest (`selfimprove.py`, additive)
A daily pass over the ledger slice that finds the agent's **own** stumbles — a
`protocol_violation`, a loop that went to TRIAGE, a `refuted` verification of its own
claim, a `dry_streak` on a question, a correction a human made to its read — and records
each as an **attributed friction entry** with a source ref. These flow into
`EMP.friction`, which `emp.kernel()` already injects into the prompt, so tomorrow's agent
reads today's burns. Dread-linted (functional, not performed).

### 3.2 Layer B — the skill/capability estate (navigate applied to skills)
Skills become **first-class navigable nodes**: a 00-grade title, what it does, where it
came from, a trust status (`local-reviewed` / `proposed` / `external-unverified`), and a
stable `capability_key` for anti-fork. `search_titles` answers "is there already a skill
for this?" *before* a proposal is minted (dedup = the curiosity anti-fork, reused). This
is the one genuinely new store; it is pure memory-as-navigation.

### 3.3 Layer C — the improvement proposal (generalise `reflect.SelfChange`)
`SelfChange` is already a target+proposal+rationale+evidence, staged and verified. Generalise
it to an `ImprovementProposal` with a typed `target` and a `source` (self-confusion /
team-post / external), reusing `apply_self_change`'s **exact** gate: no openable ledger
evidence → recorded but unverified → cannot take effect; independent verified verdict
required to apply; the record, not the proposal's own flag, is the authority. A
`skill:add` from an external source carries W1's default-N and the T-grammar's forced "why."

## 4. What is genuinely the human's call (freeze before building — from the context audit's Q-list)
- **Confusion granularity:** every stumble, or only recurring ones? (Default: recurring —
  a burn that repeats is a burn worth an EMP line; a one-off is noise.)
- **Proposal cadence:** the daily reflection ritual, or its own loop? (Default: ride the
  daily ritual — one contemplative pass, not a second budget.)
- **Skill trust tiers:** who may move a skill `proposed → local-reviewed`? (Default: only
  a human, in the portal — W1.)
- **External signal:** may the agent *fetch* a YouTube-short skill to evaluate it, or only
  *note* that one exists? (Default: **note only** — fetching untrusted code is the
  supply-chain surface; the human fetches if the proposal is ratified.)

## 5. Phases (each green before the next)
- **Phase 1 — the estate + the proposal type.** `selfimprove.py`: the `SkillNode` estate
  (navigable, anti-forked) and the `ImprovementProposal` reusing the verified/staged gate.
  Tests: a proposal cannot self-apply; W1 default-N on external skills; dedup finds an
  existing skill; an unverified proposal cannot take effect.
- **Phase 2 — the confusion harvest.** The daily burn-finder → attributed friction,
  dread-linted. Tests: a `protocol_violation`/refutation/dry-streak becomes a friction
  entry the kernel reads; performed-confusion is flagged.
- **Phase 3 — the loop with teeth.** The improvement curiosity question ("what should I
  change about how I work?"), staleness-railed, anti-forked, whose close requires a
  ratified-or-denied proposal (a dry improvement pass is not progress — the curiosity
  discipline, reused).
- **Phase 4 — the portal surface + verify/docs.** An Improvement page (proposals, evidence,
  verdicts, ratify/deny — the same independence guard as `/approve`); DECISIONS **D23**;
  ACCEPTANCE/VERIFICATION rows; an adversarial round on the new code.

## 6. Hardening log — the plan stress-test (2026-07-20)
Six lenses attacked this plan against the actual code *before any build*:

| # | Sev | The attack | Verdict / fix folded in |
|---|-----|-----------|-------------------------|
| 1 | HIGH | Can a proposal self-apply — bypass the human? | **Blocked by design:** `ImprovementProposal` reuses `apply_self_change`, which requires an independent `verification` entry authored by a non-maker; applying is a separate human step. No code path mutates EMP/skills from the proposal. |
| 2 | HIGH | Can the agent be its own verifier (self-cert) by naming a second id? | **Blocked:** `verify._guard_independence` + the ASCII-identity allowlist (hardened 2026-07-17) refuse maker==verifier and exotic/homoglyph ids. The engine calls the same gate; it adds no new verify path. |
| 3 | HIGH | Can "add this skill" auto-install (W1 bypass)? | **Blocked:** `skill:add` is a Y/N/T with default-N; external source ⇒ the human fetches/installs. The engine can *note* and *propose*, never *fetch-and-run*. §4 default: note-only for external. |
| 4 | MED | Does the confusion harvest become performed self-loathing (soul via the mortality door)? | **Guarded:** every friction entry passes `emp.lint_mortality`/embodiment lint at write; a burn is a fact with a source ref, not a feeling. |
| 5 | MED | Does the skill estate fork on rewording ("summarise" vs "summarize a doc")? | **Reuse the anti-fork:** `capability_key` is homoglyph/case-folded like `question_key`; a reworded skill folds onto the same node (dedup answers "already a skill?"). |
| 6 | MED | Can a proposal launder shaky evidence into a confident change? | **FLOOR+OR provenance** (D20) rides along; and the verifier checks the cited ledger entries are *openable*, not merely present — an ungrounded proposal stays unverified and cannot apply. |

**What held (no real flaw):** the safety core is entirely reused, not reinvented — the
engine cannot be *more* dangerous than `reflect.apply_self_change`, which two prior rounds
already hardened. The residual risk is **advisory, honestly labelled**: no lexical test
proves a proposed EMP line is *wise* — that is the human's ratification, exactly where the
plan puts it.

---

*Plan status: **Phase 1 built (2026-07-20)** — SkillEstate + ImprovementProposal + the reused verified/human gate, 11 tests, all refusals pinned. Phases 2–4 (confusion harvest, improvement-curiosity loop, portal) follow. Next: on Alex's go, build Phase 1 → 4, each green before
the next, with the Phase-4 adversarial round. The safety core is reused; the new surface is
a queue of proposals a human ratifies — the agent thinks about improving itself all the
time, and never changes itself alone.*
