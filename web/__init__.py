"""trellis web — the legible two-tier UI over the ledger.

The comprehend tier (story, in plain language) on top of the verify tier (the
raw ledger, for drill-down). Reads the append-only JSONL ledger the harness
already writes — the ledger IS the event store, so this is a read-mostly view
plus a human-approval flow. See docs/ROADMAP-UI-SPINE.md for the vision.

Layers:
  views.py  — PURE functions: Ledger → view dicts. Unit-tested, no framework.
  glyph.py  — PURE function: growth stats → an honest SVG creature. Deterministic.
  app.py    — FastAPI wiring: routes, SSE ledger tail, approve/deny. Optional dep.
"""

from .views import (roster, decision_timeline, loop_health, inbox, trust_panel,
                    memory_map, growth_stats, activity_feed)
from .glyph import render_glyph, GlyphStats

__all__ = [
    "roster", "decision_timeline", "loop_health", "inbox", "trust_panel",
    "memory_map", "growth_stats", "activity_feed", "render_glyph", "GlyphStats",
]
