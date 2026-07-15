# trellis web — the legible UI

A two-tier interface over the append-only ledger the harness already writes:
a **comprehend tier** (the story, in plain language) on top of the **verify
tier** (the raw ledger, for drill-down). The market solved *transparency for
engineers* — traces and spans. This is *comprehension for a person*.

See [`../docs/ROADMAP-UI-SPINE.md`](../docs/ROADMAP-UI-SPINE.md) for the design
thinking and [`../docs/VISUAL-TOUR.md`](../docs/VISUAL-TOUR.md) for the diagrams.

<p align="center"><img src="../docs/assets/ui-dashboard.png" width="820" alt="the dashboard"/></p>

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

## What's on the page

| Panel | What it shows | Backed by |
|-------|---------------|-----------|
| **Self-image glyph** | the agent as an honest data-viz creature, + *why* it looks that way | `web/glyph.py` from `growth_stats` |
| **Inbox** | staged actions awaiting your approve/deny — nothing sends without your yes | `stage.py` |
| **Decisions** | Y/N/T with EMP lineage; unresolved Ts past revisit glow red (hidden nos) | `decisions.py` |
| **Loops** | each loop's last outcome and run count | `loops.py` |
| **Trust** | verification pass-rate per maker — *verified by others, never itself* | `verify.py` |
| **Agents** | who's alive, how much you trust each, last seen | ledger authors |
| **Activity** | the story: what happened, newest first, in plain language | all ledger kinds |

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
