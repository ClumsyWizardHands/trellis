# LINEAGE — the archaeology

Eleven months of agent builds on this machine, read by their timestamps
(mtimes, `~/Desktop` and `~/atlas`, surveyed 2026-07-15). Every build taught
something; this file says what, and where the lesson landed in trellis. The
point is Clare's principle: **anti-examples are the fuel.**

Timestamps are file mtimes — when the build was last truly alive, not when it
was born. Where a build is still running (the Atlas gateway), that's noted.

---

## Era 1 — "keep the agents listening" (Jul–Aug 2025)

**Builds:** `Agent Documentation/` (ZACH_COMPLETE_AGENT_COORDINATION.md, Jul 2025;
KEEPING_AGENTS_LISTENING.md, Aug 2025), `AI Protocal Cline/` (Jul 2025 —
token-cache-awareness, known-hiccups-and-fixes).

**What it was:** the first coordination attempts — agents on Google Sheets,
keep-alive tricks, hand-rolled protocols.

**What it taught:** liveness is not coordination. An agent that is "listening"
but holds no shared, auditable state coordinates nothing.
**Where it landed:** `passes.py` — coordination is a file with a lifecycle, not
a connection that stays open.

## Era 2 — the dog era (Sep–Nov 2025)

**Builds:** `PoliteParanoia` (Sep 2025 — pentest results, SECURITY_ASSESSMENT),
`border-collie` / `clare-border-collie` / `emmanuel-border-collie` (Sep–Oct 2025,
O3 implementations, Obsidian integration), `Rufus` (Oct 2025 —
CONTEXT_AWARENESS.md), `team-shepherd-swarm` (Oct–Nov 2025), `Agent_SwarmV2`
(Oct 2025), `empire-discord-bot` (Nov 2025), `Discord Injestion Bot` (Dec 2025).

**What it was:** herding agents — border collies for each teammate, swarms,
the first Discord bots. Multiplying agents faster than any of them earned trust.

**What it taught:** copies of an unreliable agent are unreliable at scale; a
swarm without typed handoffs is coordination theater ("a polished final
artifact, not a back-and-forth coordination process that was auditable" —
Clare, 2026-03-16, about exactly this pattern's descendants). PoliteParanoia's
pentest was prescient: the 2026 field record (79% injection success against
always-on agents) confirmed the paranoia was polite but correct.
**Where it landed:** `verify.py` trust records (trust is earned per-maker, in
the ledger), `stage.py` (the injection blast-radius answer).

## Era 3 — the soul era (Feb 2026)

**Builds:** `Argos` (Feb 13 — `argos-SOUL-compact.md`,
`compute-observatory-SOUL-compact.md`), `Alistar` (Feb 16 — the agent Brett
blasted on Feb 22 for "confused, arrogant assertion of agency"), `Familiar`
(Feb), `atlas-agent-template` (Feb 6), `atlas-mind-and-body` (Feb 9 — carries
`openclaw.json.template`: **Atlas is a migrated OpenClaw instance**),
`atlas-daemon` (Feb 13–23 — `principles-claw-comparison.md`).

**What it was:** the personality period. Agents got souls, compact souls, soul
files per subsystem. Simultaneously: the OpenClaw migration that became Atlas,
and the beginning of the principles-claw substrate.

**What it taught:** the two biggest lessons in the whole lineage —
1. A soul.md agent hallucinates a body and gaslights about continuity. "You
   cannot run a stable, honest loop on a dishonest self-concept." Named in
   June, *still shipping in Atlas's prompts in July*. Convention does not hold
   this line; a loader that raises does.
2. OpenClaw's gateway pattern (channels in, one loop, files beside) survived
   every rewrite since — the pattern is right even where the defaults are not.
**Where it landed:** `emp.py` (SoulRefusalError, the embodiment linter),
`memory.py` epitaphs (honest session death instead of continuity theater).

## Era 4 — infrastructure dreams (Mar–Apr 2026)

**Builds:** `Helicarrier` (Mar 13 — Tailscale remote docking, multi-machine),
`Principle Claw/` project folders (Mar–Jun), Brett's `universe-pi-e-` and
`universe-slut-pi-e` (April — the 4-wave swarm builds that shipped the
request/pass/mvp skills and the SLUT/YNT vocabulary).

**What it taught:** Helicarrier answered the wrong SPOF (machines, not
process); Brett's pi(e) repos proved swarm-built artifacts drift on their own
vocabulary without a glossary gate — three competing expansions of SLUT in one
repo. Vocabulary needs a schema, not a vibe.
**Where it landed:** `decisions.py` (Y/N/T as a typed grammar, not prose),
DECISIONS.md itself (a glossary gate with dates).

## Era 5 — the local turn + the audits (May–Jun 2026)

**Builds:** `daedalus` (May 27 — gemma-hermes composition benchmark, local-model
plans; skeleton refreshed Jun 25), `Odysseus` (Jun 28 — the big local assistant:
590 test dirs, services, bridge), `omnigent` (Jun 28 — provider-agnostic agent
experiments), and the two great Atlas self-examinations:
ATLAS-LOOP-PROVENANCE-AUDIT (Jun 10) and ATLAS-MEMORY-ARCHITECTURE (Jun 30).

**What it taught:** the audit is the richest single failure document in the
corpus — sessions keyed on user_id alone, every tier stamping write-time as
event-time, `max_turns=None`, no maker-checker, threads not modeled. The memory
doc proved the counter-pattern that works: maps not content, synthesis test,
bitemporal ledger with supersession. Odysseus/omnigent proved Alex can build
big — and that big is not the constraint; *provenance* is.
**Where it landed:** `surfaces.py` (the four-part key), `clock.py` + `ledger.py`
(bitemporality everywhere), `loops.py` (bounded by construction). The working
atlas-ledger pattern was kept nearly verbatim — it earned it.

## Era 6 — now (Jul 2026)

**State:** the Atlas gateway is live (gateway/ mtime Jul 10) and remains the
most evolved agent; Brett has deliberately de-centered the Discord agents from
verification work ("an ideal anti-example"); Clare's Open Dispatch prototype
runs local models on a Hermes kanban; the team's doctrine moved to: baby EMPs
as strategy-in-context, Y/N/T decision records as the atomic unit, cheap
independent verifiers on every skill fire, stage-don't-fire, phone as the
morning surface.

**trellis is this era's build:** not a rehab of Atlas, not another agent — the
infrastructure the next agents stand on, with every era's lesson enforced in
code rather than remembered in prose.

---

## The one-line version

| Era | The bet | The burn | The refusal it became |
|-----|---------|----------|----------------------|
| listening (2025-07) | keep agents alive | liveness ≠ coordination | passes as typed files |
| dogs (2025-09) | multiply agents | swarm theater | verify + trust records |
| souls (2026-02) | give them selves | dishonest self-concept | SoulRefusalError |
| infra (2026-03) | more machines | wrong SPOF; vocab drift | typed Y/N/T grammar |
| local+audit (2026-05) | examine everything | provenance was broken everywhere | bitemporal ledger, 4-part keys, bounded loops |
| now (2026-07) | verify everything | self-audits aren't audits | maker ≠ verifier, structurally |
