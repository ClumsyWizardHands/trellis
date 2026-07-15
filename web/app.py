"""app.py — the FastAPI wiring for the trellis web UI.

Optional dependency (pip install 'trellis-harness[web]'). Reads the JSONL
ledger the harness already writes and serves the comprehend-tier views, live-
updated over Server-Sent Events by tailing the ledger. The one write path is
human approval/denial of staged actions — everything else is read-only.

Run:  trellis-web --ledger state/ledger.jsonl
  or: uvicorn web.app:app --reload   (with TRELLIS_LEDGER env set)

Design: single file, HTMX from CDN, inline templates, SSE tail. No JS build,
no broker — buildable and runnable by one person (see docs/ROADMAP-UI-SPINE.md).
"""

from __future__ import annotations

import asyncio
import html
import json
import os
from pathlib import Path

try:
    from fastapi import FastAPI, Form, Request
    from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
except ImportError as e:  # pragma: no cover
    raise SystemExit("the web UI needs FastAPI: pip install 'trellis-harness[web]'") from e

from trellis.clock import TimeGround
from trellis.ledger import Ledger
from trellis.stage import Outbox, StagedAction

from . import views
from .glyph import GlyphStats, reflection, render_glyph

LEDGER_PATH = os.environ.get("TRELLIS_LEDGER", "state/ledger.jsonl")

app = FastAPI(title="trellis")


def _ledger() -> Ledger:
    return Ledger(LEDGER_PATH, TimeGround())


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


# ---- HTML shell ------------------------------------------------------------

SHELL = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>trellis</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/htmx/2.0.3/htmx.min.js"></script>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--ink:#e6edf3;--dim:#8b949e;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff;--y:#3fb950;--n:#8b949e;--t:#d29922}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
header{{display:flex;align-items:center;gap:16px;padding:16px 24px;border-bottom:1px solid var(--line)}}
header h1{{font-size:18px;margin:0;letter-spacing:.02em}}
.tag{{color:var(--dim);font-size:12px}}
main{{display:grid;grid-template-columns:300px 1fr;gap:0;min-height:calc(100vh - 58px)}}
aside{{border-right:1px solid var(--line);padding:20px;display:flex;flex-direction:column;gap:16px}}
.glyph{{width:100%;max-width:240px;margin:0 auto}}
.reflect{{font-size:11px;color:var(--dim);list-style:none;padding:0;margin:0}}
.reflect li{{padding:2px 0;border-bottom:1px dotted var(--line)}}
section{{padding:20px 24px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:16px;margin-bottom:16px}}
.panel h2{{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);margin:0 0 12px}}
.row{{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--line)}}
.row:last-child{{border-bottom:0}}
.pill{{font-size:11px;padding:2px 8px;border-radius:20px;font-weight:600}}
.Y{{background:rgba(63,185,80,.15);color:var(--y)}}.N{{background:rgba(139,148,158,.15);color:var(--n)}}
.T{{background:rgba(210,153,34,.15);color:var(--t)}}
.hn{{background:rgba(248,81,73,.15);color:var(--bad)}}
.muted{{color:var(--dim)}}.small{{font-size:12px}}
.attn{{color:var(--bad)}}.good{{color:var(--ok)}}
button{{background:var(--acc);color:#04101f;border:0;border-radius:6px;padding:6px 12px;
font-weight:600;cursor:pointer}}button.deny{{background:transparent;color:var(--bad);border:1px solid var(--bad)}}
input{{background:#0d1117;border:1px solid var(--line);color:var(--ink);border-radius:6px;padding:5px 8px}}
.feed li{{list-style:none;padding:6px 0;border-bottom:1px solid var(--line);display:flex;gap:10px}}
.feed{{padding:0;margin:0}}.who{{color:var(--acc);font-weight:600}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
</style></head><body>
<header><h1>🌱 trellis</h1><span class="tag">{ledger}</span>
<span class="tag" style="margin-left:auto">live · SSE</span></header>
<main>
<aside>
  <div class="glyph" hx-get="/glyph" hx-trigger="load, every 10s" hx-swap="innerHTML">{glyph}</div>
  <div><div class="panel" style="margin:0"><h2>self-image · why</h2>
  <ul class="reflect" hx-get="/reflection" hx-trigger="load, every 10s">{reflect}</ul></div></div>
</aside>
<section hx-ext="sse" sse-connect="/stream">
  <div hx-get="/panels" hx-trigger="load, sse:tick" hx-swap="innerHTML">{panels}</div>
</section>
</main></body></html>"""


def _glyph_html(led: Ledger) -> str:
    s = GlyphStats.from_growth(views.growth_stats(led))
    return render_glyph(s)


def _reflect_html(led: Ledger) -> str:
    s = GlyphStats.from_growth(views.growth_stats(led))
    return "".join(f"<li>{esc(x)}</li>" for x in reflection(s))


def _panels_html(led: Ledger) -> str:
    inbox = views.inbox(led)
    decisions = views.decision_timeline(led, limit=12)
    loops = views.loop_health(led)
    trust = views.trust_panel(led)
    ros = views.roster(led)
    feed = views.activity_feed(led, limit=20)
    hidden = sum(1 for d in decisions if d["hidden_no"])

    out = []
    # inbox first — the action surface
    out.append('<div class="panel"><h2>inbox · nothing sends without your yes</h2>')
    if not inbox:
        out.append('<div class="muted small">no actions waiting for approval.</div>')
    for a in inbox:
        out.append(f'<div class="row"><div><b>{esc(a["kind"])}</b> → {esc(a["target"])}'
                   f'<div class="muted small">{esc(a["preview"])}</div>'
                   f'<div class="muted small">staged by {esc(a["by"])} · {esc(a["age"])}</div></div>'
                   f'<form method="post" action="/approve" style="display:flex;gap:6px;align-items:center">'
                   f'<input type="hidden" name="action_id" value="{esc(a["action_id"])}">'
                   f'<input name="human" placeholder="your name" required>'
                   f'<button>approve</button>'
                   f'<button class="deny" formaction="/deny">deny</button></form></div>')
    out.append('</div>')

    out.append('<div class="grid2">')
    # decisions
    out.append('<div class="panel"><h2>decisions · with lineage</h2>')
    if hidden:
        out.append(f'<div class="attn small" style="margin-bottom:8px">⚠ {hidden} hidden '
                   'no(s): unresolved "triangulate" past its revisit date</div>')
    for d in decisions:
        cls = "hn" if d["hidden_no"] else d["verdict"]
        label = "T·hidden-no" if d["hidden_no"] else d["verdict"]
        out.append(f'<div class="row"><div><span class="pill {cls}">{esc(label)}</span> '
                   f'{esc(d["subject"])}<div class="muted small">{esc(d["rationale"])[:90]}</div>'
                   f'<div class="muted small">{esc(d["lineage"])} · {esc(d["author"])} · {esc(d["age"])}</div>'
                   f'</div></div>')
    if not decisions:
        out.append('<div class="muted small">no decisions on the record yet.</div>')
    out.append('</div>')

    # loops
    out.append('<div class="panel"><h2>loops · health</h2>')
    for l in loops:
        c = "attn" if l["attention"] else "good"
        out.append(f'<div class="row"><span>{esc(l["loop"])}<div class="muted small">'
                   f'{esc(l["purpose"])[:60]}</div></span>'
                   f'<span class="{c} small">{esc(l["last_outcome"])} · {l["runs"]} runs</span></div>')
    if not loops:
        out.append('<div class="muted small">no loops registered.</div>')
    out.append('</div></div>')

    out.append('<div class="grid2">')
    # trust
    out.append('<div class="panel"><h2>trust · verified by others, never itself</h2>')
    for t in trust:
        tv = "—" if t["trust"] is None else f'{int(t["trust"]*100)}%'
        out.append(f'<div class="row"><span>{esc(t["maker"])}</span>'
                   f'<span class="small"><span class="good">{t["verified"]}✓</span> '
                   f'<span class="attn">{t["refuted"]}✗</span> · {tv}</span></div>')
    if not trust:
        out.append('<div class="muted small">no verifications yet.</div>')
    out.append('</div>')

    # roster
    out.append('<div class="panel"><h2>agents · who\'s alive</h2>')
    for r in ros:
        tv = "unproven" if r["trust"] is None else f'{int(r["trust"]*100)}% trust'
        out.append(f'<div class="row"><span>{esc(r["agent"])}</span>'
                   f'<span class="muted small">{r["actions"]} acts · {esc(tv)} · {esc(r["last_seen"])}</span></div>')
    out.append('</div></div>')

    # activity feed
    out.append('<div class="panel"><h2>activity · the story</h2><ul class="feed">')
    for f in feed:
        out.append(f'<li><span class="muted small" style="min-width:64px">{esc(f["age"])}</span>'
                   f'<span><span class="who">{esc(f["who"])}</span> {esc(f["story"])}</span></li>')
    out.append('</ul></div>')
    return "".join(out)


# ---- routes ----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home():
    led = _ledger()
    return SHELL.format(ledger=esc(LEDGER_PATH), glyph=_glyph_html(led),
                        reflect=_reflect_html(led), panels=_panels_html(led))


@app.get("/panels", response_class=HTMLResponse)
def panels():
    return _panels_html(_ledger())


@app.get("/glyph", response_class=HTMLResponse)
def glyph():
    return _glyph_html(_ledger())


@app.get("/reflection", response_class=HTMLResponse)
def reflect():
    return _reflect_html(_ledger())


@app.post("/approve")
def approve(action_id: str = Form(...), human: str = Form(...)):
    _record_decision(action_id, human, approve=True)
    return RedirectResponse("/", status_code=303)


@app.post("/deny")
def deny(action_id: str = Form(...), human: str = Form(...)):
    _record_decision(action_id, human, approve=False)
    return RedirectResponse("/", status_code=303)


def _record_decision(action_id: str, human: str, approve: bool) -> None:
    """Record the human's approval/denial to the ledger — the audit trail the
    inbox reads. (Firing the action itself is the harness's job, not the UI's.)"""
    led = _ledger()
    led.append(kind="staged_action", author=human,
               body={"action_id": action_id, "event": "approved" if approve else "denied",
                     "status": "approved" if approve else "denied",
                     "via": "web-ui"},
               tags=("outbox", "approved" if approve else "denied"))


@app.get("/stream")
async def stream():
    """SSE: tail the ledger file; emit a 'tick' whenever it grows so the panels
    refresh. Simple size-poll — no broker, works over any filesystem."""
    async def gen():
        path = Path(LEDGER_PATH)
        last = path.stat().st_size if path.exists() else 0
        while True:
            await asyncio.sleep(1.5)
            now = path.stat().st_size if path.exists() else 0
            if now != last:
                last = now
                yield "event: tick\ndata: {}\n\n"
            else:
                yield ": keepalive\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


def main():  # console entry point
    global LEDGER_PATH
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser(description="trellis web UI")
    ap.add_argument("--ledger", default=LEDGER_PATH)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8674)
    args = ap.parse_args()
    os.environ["TRELLIS_LEDGER"] = args.ledger
    LEDGER_PATH = args.ledger
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
