# Plan v2 — the contemplative backdrop: ingestion, and a mind that maps its own understanding

**Date:** 2026-07-17 · **Status:** HARDENED (v2) — stress-tested and folded; ready to build on your go.
**Rhythm:** plan → stress-test → harden → build, each phase green before the next.

This is the *permeating backdrop* Alex asked for: not a second agent, but the standing inner
life of the trellis agent — a **contemplating mind of decisions**, not a scraper. It
continuously takes in the team's record (transcripts, the daily Discord downloads, Brett's
videos, audio notes) and *understands* it: tracking not just *what* was decided but *how the
room got there*, minting Y/N/T saplings, mapping them into an Obsidian vault by title,
reflecting each day, and staying honestly curious about where it is assuming and what it
needs to learn.

The harness we already built is the spine that makes such a mind **trustworthy** instead of
a confident hallucinator. This plan extends that spine to *the world's material coming in* —
and v2 folds in your four clarifications plus a six-lens adversarial round that raised 22
candidate flaws against v1. The confirmed structural ones are fixed below (§9 is the log).

---

## 0. Your calls (ratified 2026-07-17)

| Fork | Your call | Effect on the design |
|---|---|---|
| **Autonomy** | *Autonomy of **understanding**, not posting.* Search **persistently** — never "one search, done" as an excuse. Nothing posts freely. | The green/amber/red spread **collapses**: read / search / research / map run fully live and *thoroughly*; **anything that leaves the machine stays staged for you**. The real work moves to giving "persistent, non-satisficing understanding" actual teeth (§3.5, §5). |
| **Source feed** | *Both — read Atlas's dumps, fetch the gaps.* Exact paths given. | Phase A reads Atlas's existing outputs and can query its ChromaDB index; we keep **our own** ingest markers as our truth. Lighter than budgeted (§3.1). |
| **Observed decisions** | *Both, as two linked nodes.* | An **observation node** (attributed to the room) + the agent's **opinion node**, joined by an edge — with **distinct, stable identities** so they never collide and re-harvest is idempotent (§3.3). |
| **Canon** | *Questioned — "what's the point? what does it serve?"* | **Reframed from an input-gate to an output-signal** (§4). The agent never blocks on canon; confidence + your affirmation *compound*. No bottleneck, no crutch. |
| **Scope** | *Deferred — personal agent, your machine, Claude SDK + Max, not a server.* | Single-writer assumption is legitimate (simplifies idempotency). No channel scoping now. |

---

## 1. Autonomy, settled: persistence of understanding, not freedom to post

You clarified the line I most wanted clarified. Autonomy here is **not** "act in the world."
It is: **read, search, research, and map freely — and do so *thoroughly*, not as a checkbox.**
Nothing leaves your machine without your yes. Concretely:

- **Live, no gate:** ingesting, reading, semantic search over the record, read-only web
  research, writing to the agent's own vault memory, forming opinions. Every one is still
  *recorded and attributed* in the ledger, so it is never silent.
- **Staged for you (unchanged from the harness):** anything outbound — a Discord post, a DM,
  an email, anything reaching a person or a system. The stage-don't-fire gate stands exactly
  as built; refusal #5 is untouched.

The green/amber/red grading from v1 is **gone** — you don't want autonomous posting, so
there's no "amber" to defend, and the round's autonomy findings (self-assigned grades, the
lapsing undo-window, reversibility-vs-blast-radius confusion) *dissolve with it*. What
survives is the one hard part: making "persistent, honest understanding" structural rather
than aspirational, so the agent can't make one search and call it knowing. That lives in the
curiosity loop (§3.5) and gets real teeth (§5).

---

## 2. Invariants that must survive (the regression contract)

1. **The vault and the ledger are ONE store with two faces — and drift is *detectable*.**
   The markdown files are the content; the ledger is the append-only event/attribution/
   lineage index over them, storing a **content hash** per write (v1 wrongly claimed the
   vault was reconstructable from the ledger alone — it stored only a byte-count). A
   **reconciliation pass** detects and heals divergence (§3.2). Not "the ledger is
   everything"; rather "nothing changes in the vault without a matching, hashed, attributed
   ledger event, and the two are continuously reconciled."
2. **The five refusals hold**, refusal #5 intact (nothing outbound fires without your yes).
3. **Nothing about the world is asserted without structured provenance.** Confidence, source
   refs, `transcript_fallible`, and reconstructed-time are **typed fields on the record**,
   not free prose — and they **propagate** through folds and summaries so a low-confidence,
   machine-transcribed observation can never launder into asserted fact (§3.3, §3.4).
4. **Memory stays navigation** — 00-grade titles walked to, not bulk context.
5. **Ingestion is idempotent and resumable** — re-reading, partial runs, and corrected
   re-dumps never double-count or fork a decision (§3.1).
6. **The mortality posture and epistemic honesty hold** — time-blind, only-the-words,
   confidence-stated, functional not performed.

---

## 3. Architecture — five layers, bottom to top

### 3.1 Sources & ingestion — read Atlas's dumps, fetch the gaps; idempotent by design

**Concrete sources (from you):** transcripts at `~/atlas/data/transcripts/`, Whisper output
at `~/.principles-claw/transcripts/`, Discord daily markdown at `~/atlas/data/discord-logs/`,
the raw archive `~/atlas/data/discord_messages.jsonl`, Atlas's index-state at
`~/atlas/data/state/`, and its ChromaDB at `~/atlas/data/transcripts/.chroma_db/`. Config
mirrors Atlas's `tools/config.yaml` + typed `config.py`.

A thin **adapter interface** (`discover() → items`, `fetch(item) → text+provenance`), with:
a **dumps adapter** (primary), a **`discord-read` gap-fill adapter**, and a **media adapter**
(Brett's videos / audio notes → the **`audio-transcription` skill**, tagged loudly as
machine transcription, lower confidence). We can *query Atlas's ChromaDB* for semantic recall
instead of re-embedding; Atlas's `state/` tells us what *Atlas* indexed, but **our ledger is
the truth for what *we* understood.**

**Idempotency, fixed against the round's five determinism findings:**

- **Stable content key** = `sha256(source + channel + best-id + event_time + content)`.
  When a message has **no id** (the round caught `message_id` defaulting to `""`, which
  collapses every id-less message in a channel into one key), the key falls back to the
  content+time hash — never a shared empty string.
- **Two-phase markers** for "one raw item → many derived decisions": an `ingest_started(key)`
  and a later `ingest_complete(key, derived_ids[])`. A key counts as done **only** if a
  complete record exists; a started-but-incomplete key is **resumed** (its partial derived
  entries are retired and re-harvested). This is v1's fatal gap — an append-only marker
  couldn't record partial progress — closed.
- **Corrected re-dump ≠ duplicate:** a re-dump with the same key but a **different content
  hash** is a *correction* (supersede the prior ingest + re-harvest), distinguishable
  precisely because the hash differs. Same key, same hash → true no-op.
- **Single-writer** (your personal-agent clarification) removes the TOCTOU race the round
  flagged; the read-side resolver still dedups by key (last-complete-wins), so even a
  double-append is idempotent at read time.

### 3.2 The Obsidian vault = the navigable memory, reconciled with the ledger

The vault **is** the existing `Workspace`, rooted at your Obsidian vault directory, with
Obsidian conventions layered on — but v1 overclaimed its relationship to the ledger, and the
round was right. The honest model:

- **The markdown files hold the content; the ledger holds the events.** Each `memory_write`
  now records a **content hash** (not just a byte-count) + path + title + provenance. The
  vault is git-versioned (human-editable in Obsidian is a *feature*, not a threat).
- **A reconciliation pass** (runs each contemplation cycle, and on demand) walks the vault
  against the ledger and heals the four drifts the round named:
  1. **A human edited a note in Obsidian** → the hash mismatch is detected and folded as a
     new *attributed* write ("edited by Alex, <time>"), so the human's edit joins the lineage
     instead of being clobbered or lost.
  2. **A wikilink points to a retired/superseded decision** → the link is re-pointed to the
     live head (or marked "retired" inline), because —
  3. **Retirement/supersession now touch the files, not just the ledger.** When a decision is
     retired or superseded, the reconciliation stamps the note's frontmatter (`status:
     retired`, `superseded_by: …`) and updates back-links. v1 left the ledger and the `.md`
     files to silently disagree; they no longer do.
  4. **Stale `ledger_entry` frontmatter after a fold** → frontmatter carries the **question
     identity** (stable) plus the *current head* entry id, refreshed by reconciliation, not a
     single frozen id that goes stale on every fold.
- **Drift is a first-class, surfaced condition**, not a comment. If reconciliation finds
  something it can't heal automatically, it raises it on the Assumptions & Curiosities board
  (§4) rather than papering over it.

Vault shape: `decisions/` (observation + opinion notes) · `reads/` (current synthesized read
per topic/room) · `people/` · `threads/` · `questions/` (open assumptions & curiosities) ·
`reflections/` · `epitaphs/`.

### 3.3 The observation/opinion model — two nodes, distinct identities, typed provenance

The round confirmed two real flaws in v1's sketch, both fixed here:

**(a) Distinct, stable identities (v1's nodes would have collided / forked).** An observation
and an opinion about the same decision are given **namespaced keys** — `obs:<id>` and
`op:<id>` — so the `question_key` anti-fork we hardened never wrongly refuses the pair, and
they're joined by a typed `opinion_of` edge. Crucially, `<id>` is **not** a slug of the
free-text subject (which the round showed forks on any rewording during re-harvest). It's a
**stable decision identity** = hash of `(source transcript + anchor/moment + participants)`.
So re-harvesting the same meeting maps to the **same** `obs:` node (a fold/REOPEN), never a
new forked one. Idempotency (#5) now holds across re-reads *and* rewordings.

**(b) A structural home for confidence & provenance (v1 left them as free prose that could
launder).** Both nodes carry typed fields **in the ledger body** (the source of truth), not
in the rationale text:

- `attributed_to` — the participants the decision belongs to (the room), distinct from the
  agent that *recorded* it.
- `source_refs` — the ingest keys / transcript anchors it rests on (openable, citable).
- `confidence` — a scalar the agent must state (how sure, given only the words).
- `transcript_fallible` / `machine_transcribed` — flags; a decision resting on Whisper output
  or a garbled passage is marked, always.
- `event_time_reconstructed` — the moment is the transcript's claim, not ground truth; the
  bitemporal stamp already separates *when it happened* (claimed) from *when I read it*.

Both are ordinary `Decision`s, so they inherit the hardened grammar (T-guard, WALK/REOPEN/
DECIDE, validity/retirement, anti-fork). **Many decisions per transcript** is the normal case:
the harvest loops over candidate moments; each candidate is **independently verified** (finder
≠ confirmer) before it becomes a node — and the confirmer returns a **confidence-aware**
verdict, not a binary "verified" that would (the round's point) launder a 0.4 into a 1.0.

### 3.4 Provenance propagation — no laundering upward

The round's sharpest cluster: confidence/provenance that exists on a leaf observation but
**doesn't survive** being folded up into a `read` or summarized. Fixed structurally:

- A summary/read **inherits the floor of its inputs' confidence** and the **union of their
  `source_refs`**, and is flagged `machine_transcribed` if *any* input was. You cannot make a
  confident read out of shaky observations; the shakiness rides along.
- The **synthesis gate and fold-not-clobber carry provenance forward** (they operate on the
  ledger body, where the fields now live) — a fold that dropped provenance is a bug the
  reconciliation catches.
- The UI always shows a read's confidence and lets you open the exact observations (and their
  transcript moments) it rests on. Confidence is *displayed and audited*, never silently
  hardened.

### 3.5 The contemplation & curiosity loop — with teeth (your core concern, the round's #19–21)

This is where your worry — "it'll make one search and say it did its job" — and the round's
strongest findings converge. v1's "ask two questions a day" **was itself the green checkmark
it claimed to abolish.** v2 makes curiosity structural:

- **Open questions are first-class nodes** (`questions/`), not prose: each has a title, the
  assumption it targets, *what would resolve it*, an owner, and — the key — a **staleness /
  accountability rail exactly like "an unresolved T is a hidden no."** An open question that
  sits untouched past its revisit **surfaces as needing attention**. The agent can't emit a
  question and forget it; open questions accrue and nag until pursued or honestly closed.
- **Anti-fork on questions:** a curiosity is keyed off the *assumption it targets*, so the
  same question reworded tomorrow maps to the **same** node (REOPEN/refresh), not a fresh
  checkmark. The daily gate is not "did I write two questions" — it's "did I make real
  progress on the open set, and is that set honestly maintained."
- **Seeking is a bounded loop whose stop condition is diminishing returns, not "I searched."**
  A completion claim of "I now understand X" is **verified against evidence that the map
  actually changed** — did the search resolve an assumption, sharpen a question, or shift a
  confidence? "I ran a search" is not evidence of understanding; the confirmer checks the
  record moved. This is the exact anti-satisficing mechanism you asked for, built on the
  maker≠verifier spine we already have.
- **The daily reflection** (the ritual we built, cadence keyed off harness write-time — the
  bug we just fixed) now reflects on *the world it's mapping*: what came in, what changed,
  where it's assuming, what it must learn — cited, synthesis-gated, dread-linted, and
  verifier-gated for any self-change. Mortality posture: *this session won't remember; what
  did I leave?*

---

## 4. Canon, reframed — an output, not a gate (your question answered)

You asked what canon serves and whether it becomes a bottleneck. The one real danger it
guarded is that a **confident-but-wrong read calcifies into the bedrock everything downstream
trusts.** But gating *belief* behind your blessing makes the agent the deferring, permission-
asking crutch you don't want. So v2 flips it:

- **The agent operates entirely in its own working understanding — no gate.** It thinks,
  maps, forms opinions, and self-corrects freely.
- **Canon is what *rises*, not what's *permitted*.** "Canon" = the small set of things that
  earned **high confidence *and* your affirmation.** Your affirmation (a click in the portal)
  **compounds trust** the way a verifier's verdict does today — it raises standing; it never
  unlocks the agent's ability to proceed, because the agent never needed unlocking.
- **What you're getting to:** an agent whose map of your world you trust *because you can
  audit how it got there*, not because it asked permission for each belief. It thinks freely,
  is wrong out loud and correctable, rather than tentative-and-blocked and quietly
  calcifying. The only thing that stays hard-gated is **outbound action** (§1) — never belief.

---

## 5. How it loops into the UI (the portal grows)

Same discipline (pure views over ledger+vault, self-explaining): **The Map** (the vault as a
navigable graph — a decision opens to its observation *and* the agent's opinion, side by side,
with the cited transcript moments and confidence); **Assumptions & Curiosities** (the
`questions/` board with its staleness rail — the contemplating mind made visible, and where
your worry is *watchable*: you can see if it's genuinely pursuing or stalling); **Ingestion**
(coverage vs. gaps, what's machine-transcribed, conversation velocity per room over time);
**Reflection** (now reflecting on the world, not just its own runs).

## 6. Phases (each green before the next)

- **A — ingestion spine:** adapters (dumps + gap-fill + media→transcription), the fixed
  content-key + two-phase markers + resume, provenance-stamped material in. *No decisions
  minted yet.*
- **B — observation/opinion model:** two-linked-node harvest with distinct stable identities
  and typed provenance, confidence-aware verification, velocity + time-blind stamping; the
  vault projection with content-hash + reconciliation.
- **C — contemplation loop with teeth:** first-class question nodes + staleness rail +
  anti-fork; the diminishing-returns seek loop with evidence-verified understanding.
- **D — the spoken face:** the Discord conversational surface reusing threading/passes;
  outbound staged (refusal #5).
- **E — UI surfaces + verify/docs/push:** the Map, Assumptions & Curiosities, Ingestion;
  adversarial round on the new code; DECISIONS entries; push.

## 7. What we deliberately do NOT do

- No rebuilding Atlas's downloader — read its dumps, fill gaps, reuse its index.
- No treating the vault as a second source of truth **and** no pretending it's fully
  reconstructable from the ledger — it's one store, two faces, continuously reconciled.
- No auto-consolidation "dream" writes — every observation/opinion is verifier-gated.
- No autonomous outbound — belief is free, action stays staged.
- No pretending to know tone or stakes — velocity is a proxy, confidence is stated, the
  transcript is fallible, and the agent says so.

## 8. Open decisions (small, after your clarifications)

- **D-2 · Vault location.** You name the Obsidian vault directory; the Atlas paths above are
  set.
- **D-4 · Affirmation UX.** How you affirm in the portal (a per-decision "yes, that's right"
  that compounds confidence) — trivial; I'll default to a one-click affirm on the Map.

---

## 9. Hardening log — the plan stress-test (2026-07-17)

Six adversarial lenses attacked v1; 22 candidate flaws raised, each cross-checked against the
actual code. The confirmed structural ones — folded above — clustered into five real problems
v1 had:

| Cluster | What v1 got wrong | Fixed in v2 |
|---|---|---|
| **Vault ≠ ledger** | The ledger stores a byte-count, not content, so "reconstructable from the ledger alone" was false; retirement/supersession never touched the `.md` files or wikilinks; frontmatter ids went stale on every fold. | §3.2: content-hash in the ledger; a reconciliation pass that heals human edits, stale links, retired notes; frontmatter keyed off stable identity, not a frozen id. |
| **Two-node identity** | Observation + opinion could collide on one `question_key`; and keying off the free-text subject forks on any rewording during re-harvest (idempotency broken). | §3.3: namespaced `obs:`/`op:` keys + a stable decision identity (source+anchor+participants), so re-harvest folds, never forks. |
| **Provenance laundering** | confidence / `transcript_fallible` were free prose on `Decision`; they didn't propagate through folds/summaries; the confirmer's binary verdict laundered a 0.4 into "verified." | §3.3–3.4: typed provenance fields in the ledger body; floor-inheritance on summaries; confidence-aware verification. |
| **Ingestion determinism** | `message_id` defaulted to `""` (all id-less messages collapse); append-only markers couldn't record partial progress; a corrected re-dump looked like a duplicate. | §3.1: content-hash fallback keys; two-phase started/complete markers with resume; hash-diff distinguishes correction from duplicate; single-writer removes the race. |
| **Curiosity without teeth** | "Two questions a day" *was* the checkmark it claimed to abolish; open questions had no staleness rail; no anti-fork on questions. | §3.5: first-class question nodes with the "hidden-no" staleness rail + anti-fork; a diminishing-returns seek loop whose "I understand" is verified against a changed map. |

The autonomy findings from v1 (self-assigned grades, the lapsing undo-window, reversibility-
vs-blast-radius) **dissolved** once you confirmed no autonomous posting — there is no amber
tier to defend; belief is free, outbound stays staged.

---

*Plan status: **hardened (v2)**. Next: on your go — and once you name the vault directory —
build Phase A → E, each green before the next, with an adversarial round on the new code as
we did for the memory core.*
