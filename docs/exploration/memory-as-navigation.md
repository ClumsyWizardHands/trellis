# Memory as navigation — an exploration (not a build)

**Date:** 2026-07-17 · **For:** Alex · **Method:** 14 sub-agents — 8 researching real
memory systems (Letta/MemGPT, mem0, Zep/Graphiti, Claude's memory tool, LangMem,
Cognee/A-MEM/Generative-Agents, RAG-as-memory, reconstructive-memory cognitive
science), 6 interrogating the specific idea (one steelman, two attacks, three
reframes). Alex was explicit: *"don't just agree with me — explore."* This doc
does not agree with the literal proposal; it finds the version of it that survives.

## The proposal under examination

> "Memory as navigation, not an automatic saved state. Every memory records a YNT
> (yes/no/triangulate) sapling that gets saved **elsewhere** — not in the system
> prompt. The system instead **navigates** using memory, helping to **relearn all
> decisions**." — Alex, 2026-07-17

## Where I land (the short version)

1. **The direction is right, and it's validated by three independent proof points**
   — not a fringe bet.
2. **But the literal claim — "relearn-by-navigation as the PRIMARY mode" — has one
   load-bearing ambiguity and two real failure modes.** Taken naively it would
   reintroduce the exact non-determinism the harness exists to forbid.
3. **The version that survives interrogation is precise, and trellis is already
   ~90% built to be it.** The delta is small and nameable: a three-verb grammar,
   a cached "resolved head," a reshaped prompt boundary, and a forgetting policy —
   plus one real bug the exploration turned up.

---

## 1. The spectrum every memory system lives on

The axis Alex is probing is real and the field is spread across it:

| System | Where it sits | How memory gets used |
|---|---|---|
| **RAG-as-memory** | pure automatic saved-state | vectors written without judgment, injected without traversal — "retrieval happens *to* the context" |
| **mem0** | automatic saved-state | background LLM extracts memories silently, top-k injected silently; the agent never navigates |
| **Zep / Graphiti** | automatic saved-state (but temporally honest) | auto-extracts a temporal knowledge graph, auto-injects a reconstructed slice — **but** with a real bi-temporal model (four timestamps per edge) |
| **LangMem / LangGraph Store** | middle | nothing auto-injects; an item does nothing until code/agent `search`es for it |
| **Letta MemFS / "Context Repositories"** | hybrid, sliding to navigation | git-markdown filetree; titles + one-line descriptions always resident, bodies opened on demand |
| **Claude memory tool** | navigation | injects **zero** memory content by default — only the *imperative* "view memory before acting" |
| **Stanford Generative Agents** | navigation + reflection | scores & traverses a memory stream on demand; **re-derives** abstractions via reflection |
| **Human memory (cog-sci)** | maximally navigation | every recall reconstructed from cues; no stored snapshot |
| **trellis (today)** | navigation-leaning | files beside the agent, titles-only map in a <1.2k-token prompt, synthesis-test write gate, bitemporal YNT ledger |

Read top-to-bottom, the trend of the *best* recent systems is **away from
automatic saved-state and toward navigation.** Alex is pushing trellis further down
a road the frontier is already on.

---

## 2. The direction is validated — three independent proof points

**Letta abandoned database memory blocks for a git-markdown filesystem (Feb 2026).**
Their "Context Repositories": memory is a directory of markdown files; the filetree
+ frontmatter descriptions stay in the prompt as a persistent *map*, bodies load
only when the agent opens them. They arrived at trellis's "titles-only map + forced
open" pattern **independently** — and published a benchmark showing plain file
operations beat their own bespoke memory-block API (74.0% vs mem0's 68.5% on
LoCoMo) because models wield file tools better than custom memory verbs. The bespoke
saved-state interface was a *liability* they migrated off.

**Anthropic's Claude memory tool injects zero memory content by default** — only the
standing instruction to *view memory before acting*. That is literally
relearn-by-navigation as the primary mode, hard-coded into the protocol. The
frontier lab shipped the thing Alex is describing.

**Cognitive science says the bet is correct about how memory actually works.**
Human memory is *reconstructive*, not playback (Bartlett's schemas, Loftus,
Schacter's constructive-episodic-simulation hypothesis): every recall is re-derived
from cues by traversing associative structure. Reconstruction is what buys
generalization and compression. Re-deriving a decision uses the *same machinery* the
brain uses to simulate futures — so "relearn by navigation" is native, not exotic.

So: the direction is not a whim. It's where Letta went, where Anthropic went, and
how brains work.

---

## 3. Where the naive version breaks (the interrogation earned its keep)

### 3.1 The crux — "relearn" fuses two operations that must stay surgically separate

"Relearn all decisions by navigation" hides two readings, and the fusion is the
whole ballgame:

- **RE-WALK** — navigate to the *recorded* YNT node + its lineage and reconstruct
  the *understanding* (why the verdict holds). The verdict is authoritative and
  read-only.
- **RE-DERIVE** — re-reason the decision from raw inputs and emit a possibly-
  *different* verdict.

**The failure, concretely** (from the crux agent): six months ago trellis recorded
"blue-green or rolling deploys? → rolling," because flag-based rollback made
blue-green's doubled warm-capacity cost not worth it. A fresh agent RE-DERIVES from
a sparse node, the "flag-rollback exists" premise doesn't resurface, and it silently
flips the decision to blue-green. Nothing is superseded on the record; the agent
just *quietly re-decided a settled question differently* — which is exactly the
drift/gaslighting trellis is built to forbid. Reconstruction's native failure mode
is **confabulation**: confidently remembering something that didn't happen.

**The resolution — split "relearn" into three grammar verbs, never one:**

- **WALK** — re-understand; returns a **read-only** verdict + reconstructs the why.
  Default. Verdict immutability is a *type-level* property of the walk, so the code
  literally cannot emit a new verdict from a walk.
- **REOPEN** — the only path that writes a **T**; requires an *objective trigger*
  (past its revisit date, a lineage premise flipped, a contradiction detected).
- **DECIDE** — emit a Y/N; permitted **only** on a T-state or a brand-new node.

This reconciles "memory is navigation" with "the record is authoritative":
navigation reconstructs the *why*, never the *verdict* — and re-deciding is possible
only when the record itself says it's due. This is the single most important output
of the whole exploration.

### 3.2 Cost & non-determinism — don't make navigation the naive primary mode

Navigation conflates **learning** (build a durable representation once) with
**inference** (decide now). A cached prompt is cheap and deterministic *because it
freezes the learned result*. Re-navigating on every decision un-freezes it — paying
retrieval + re-read latency each time, and risking a different answer each time.
The cost verdict hinges on a number we don't have: **decisions-per-session × saplings-
per-decision** (roughly, 5 decisions/session survives; 50 does not).

**The fix:** keep a **deterministic materialized projection** — the *resolved head*
of each decision's supersession chain — and cache *that* for hot decisions.
Navigation becomes the path for **cold-start, stale, audit, and genuine-judgment**
calls, not for re-reading settled hot facts on every turn. Two-tier: **navigate
cold, cache the resolved head hot.**

### 3.3 "Not in the system prompt" is the wrong invariant

The boundary isn't *where bytes live* — it's *what the resident bytes commit you
to*: their **cardinality** (O(1) vs O(memories)) and their **shape** (question vs
answer). Two things *must* stay resident or navigation is impossible: the **EMP**
(the traverse-don't-assume doctrine + YNT grammar, ~350 tokens, O(1)) and the
**clock** (~30 tokens, O(1)). Both are answer-free, so they're safe.

The dangerous resident is the **map**. A titles-only map can smuggle saved-state
back in through *answer-shaped titles*: "Auth token model? **[resolved: JWT
rejected]**" has leaked the verdict into the prompt — you're back to saved-state
wearing a map's clothes. **Fix:** resident = EMP + clock + a *sparse, question-
shaped entry-point index* (root coordinates only, ~800 tokens, O(1)); navigate the
map body itself. Add a **resolution-leakage lint**: any resident/index title must be
question-shaped, never carry its answer.

### 3.4 There is no forgetting policy (birth control ≠ forgetting)

trellis has a *write gate* (the synthesis test) — that bounds the **inflow** rate.
It does nothing about the **stock** going stale or self-contradictory. Append-only +
"fold, don't prune" + human-gated canon = **monotonic growth with no current-truth
resolution.** At 50k saplings, two things bite: the fixed-budget map can't cover the
store (coverage collapse), and navigation success compounds as (1−ε)^depth while
depth grows with log(N) — so per-hop error matters. **Fix:** adopt Zep/Graphiti's
**validity intervals** — when a sapling supersedes another for the same *scoped*
question, stamp the old one's `valid_to` so folding **retires it from the ACTIVE
index** (history preserved, current truth resolved). The map indexes *active*
saplings only.

### 3.5 A real bug the exploration found in passing

`Workspace.write()` **clobbers** — `path.write_text` overwrites the prior file. That
silently violates "fold, don't prune": Session A writes "deploy via Blue; we said N
to Green"; Session B overwrites it with "deploy via Green"; the reasoning and the
prior verdict are **gone from the file** (the ledger logs the write event but not the
content). If memory is going to be sapling-shaped, workspace writes must **fold, not
clobber** — version-on-write, retaining the superseded body. This one's a genuine
fix regardless of the bigger design.

---

## 4. The design that survives interrogation

Putting the fixes together — this is what "memory as navigation" should mean in
trellis, and note how little of it is new:

1. **Three-verb grammar: WALK (read-only, default) · REOPEN (writes a T, needs a
   trigger) · DECIDE (Y/N, only on a T or new node).** Verdict immutability enforced
   at the type level. *(new — the core of it)*
2. **Two-tier read: navigate cold/stale/judgment; cache the deterministic resolved
   head for hot decisions.** *(new — a materialized view over the existing ledger)*
3. **Resident set = EMP + clock + sparse question-shaped entry index (O(1)).**
   Navigate the map body; lint resident titles for leaked answers. *(refines the
   existing `prompt.py`)*
4. **Forgetting = validity intervals + an active index.** Folding stamps `valid_to`
   and retires from the active map; nothing is deleted. *(borrows Zep's proven
   bi-temporal edge — trellis's ledger is already bitemporal, this extends it)*
5. **Workspace writes fold, not clobber.** *(a bug fix)*

## 5. How much of this is already built

The composition agent's finding, which I think is the most important framing for
*you*: **you are describing something trellis is already ~90% built to be.** "A YNT
sapling saved elsewhere" is a re-description of the existing `DecisionLog` — decisions
already live in the bitemporal ledger, already carry lineage (`upstream()`), already
supersede rather than delete, and the prompt already carries only a map. So this is
**not a new subsystem.** The genuine delta is the four items above, and the biggest
of them — the WALK/REOPEN/DECIDE grammar — is a discipline layer over records that
already exist, not a rewrite.

The one thing I'd push back on hardest: **do not adopt "relearn-by-navigation as the
primary mode" without the resolved-head cache and the three-verb grammar.** Naked, it
trades trellis's deterministic authority for non-determinism — and determinism-with-
receipts is the entire reason the harness is trustworthy. Navigation should
reconstruct the *why*; the *verdict* stays on the record.

## 6. Open questions — as Y/N/T for you

These are genuine decisions the evidence can't settle; they're yours to call.

- **T — Does "relearn" mean WALK by default?** (My strong lean: yes — read-only
  re-understanding, with REOPEN only on an objective staleness/contradiction
  trigger. Needs your ratification because it defines the whole behavior.)
- **T — Do freeform notes/skills become sapling-shaped too, or only formal
  decisions?** "Every memory is a YNT sapling" could mean collapsing `Workspace` and
  `DecisionLog` into one store — powerful, but you'd lose the cheap freeform note.
  Missing piece: whether the note/skill layer needs verdict+lineage discipline.
- **T — What triggers a REOPEN?** wall-clock TTL, a flipped lineage premise, or an
  incoming contradiction score — and who sets it at write time? (Cascade risk: if a
  premise flips to T, do dependent Y/Ns auto-cascade to T, or just flag?)
- **N (for now) — Auto-consolidation subagents (the Letta "dream" pattern)?** Lean
  no: they write memory *without* the verification gate, which is exactly trellis's
  cardinal sin. Revisit only if consolidation itself passes a checker.
- **Y — Fold, not clobber, in the workspace.** This one's just correct; ship it
  whenever we next touch memory.

---

*This is exploration, not a build. Nothing above is committed to code. The three-verb
grammar and the resolved-head cache are the two moves I'd want to prototype first if
we decide to proceed — small, and they're where the whole idea lives or dies.*

*Sourced from 14 sub-agents, 2026-07-17. Full agent findings: the workflow journal.*
