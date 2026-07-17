# trellis web — the comprehension & reflection portal

**Not an operations console.** A side nav of dedicated, self-explaining pages over
the append-only ledger the harness already writes — a place to *understand* what
the agent understood, and the room where it reflects on itself each day. Every term
defines itself in place; no insider vocabulary. The market solved *transparency for
engineers* (traces and spans); this is *comprehension for a person*.

See [`../docs/ROADMAP-UI-SPINE.md`](../docs/ROADMAP-UI-SPINE.md) for the design
thinking and [`../docs/VISUAL-TOUR.md`](../docs/VISUAL-TOUR.md) for the diagrams.

<p align="center"><img src="../docs/assets/ui/overview.png" width="860" alt="the trellis portal — Overview"/></p>

## Run it

```bash
pip install -e '.[web]'            # fastapi + uvicorn
# point it at any trellis ledger:
trellis-web --ledger state/ledger.jsonl
# or try the bundled demo ledger:
trellis-web --ledger web/demo/ledger.jsonl
# → open http://127.0.0.1:8674
```

To regenerate the demo ledger + the glyph/screenshot assets:

```bash
python3 web/demo_seed.py           # writes web/demo/ledger.jsonl
```

## The pages (a side nav of single-job surfaces)

| Page | What it shows | Backed by |
|------|---------------|-----------|
| **Overview** | the one-screen read: self-image, the attention rail (hidden-nos + reopened), what's waiting on your yes, loop health, latest story | `views.growth_stats`, `open_questions_view`, `inbox` |
| **The Map** | what the room decided (attributed, confidence, machine-heard flagged) with the agent's own opinion beside it | `observations_map` |
| **How I got here** (`/observation/<id>`) | one-click lineage: the observation, the agent's opinion, the cited source moments, confidence + caveats, and a one-click affirm | `observation_lineage` |
| **Assumptions & Curiosities** | open questions with the staleness rail — overdue lights up, a dry streak flags "keeps looking, nothing moves" | `curiosities` |
| **Ingestion** | what's been taken in and understood; coverage + how much rests on machine transcription | `ingestion_status` |
| **Decisions** | every Y/N/T with EMP lineage; a decision *opens up* into a WALK of its reasoning | `decision_timeline`, `decision_walk` |
| **Reflection** | the daily self-image beside yesterday's, the cited "why", the deltas, a self-change as a verified proposal | `reflection_view`, `glyph.py` |
| **Loops / Verification / Agents / Activity** | background jobs & health · who checked whom · who's on the record · the raw event log | `loop_health`, `trust_panel`, `roster`, `activity_feed` |

The only write paths are a human's **approve/deny** of a staged action and a
one-click **affirm** of an observation — both append an attributed event to the
ledger. Firing an approved action stays the harness's job, not the UI's.

## How it's built

`views.py` are **pure functions** (Ledger → view dicts) — unit-tested, no
framework. `glyph.py` is a **pure, deterministic** renderer (stats → SVG).
`app.py` is a thin FastAPI shell: HTMX from a CDN, inline templates, and an SSE
endpoint that tails the ledger file and pushes a refresh when it grows. The
ledger **is** the event store — no database, no message broker, no JS build.
One person can run and extend it.

The only write path is human approval/denial of a staged action, which appends
an `approved`/`denied` event to the ledger (the audit trail the inbox reads).
Firing the approved action itself stays the harness's job, not the UI's.
