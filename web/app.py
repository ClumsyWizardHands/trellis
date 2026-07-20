"""app.py — the trellis comprehension-and-reflection portal.

This is NOT an operations console. Work happens where the team already is (chat);
this is the window you open to UNDERSTAND what the agent understood, and to watch
it reflect. Every page is self-explaining: no insider vocabulary, terms define
themselves in place. The one write path is a human approving/denying a staged
action — everything else is read-only over the ledger the harness writes.

Design (see docs/ROADMAP-UI-SPINE.md): a left nav of dedicated, plainly-named
pages; server-rendered HTML; HTMX from CDN; SSE tail for liveness. Single file,
no JS build, runnable by one person.

Run:  trellis-web --ledger state/ledger.jsonl
  or: uvicorn web.app:app --reload   (with TRELLIS_LEDGER env set)
"""

from __future__ import annotations

import asyncio
import html
import os
from pathlib import Path

try:
    from fastapi import FastAPI, Form, HTTPException, Request
    from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
except ImportError as e:  # pragma: no cover
    raise SystemExit("the web UI needs FastAPI: pip install 'trellis-harness[web]'") from e

from trellis.clock import TimeGround
from trellis.ledger import Ledger

from . import views
from .glyph import GlyphStats, reflection, render_glyph

LEDGER_PATH = os.environ.get("TRELLIS_LEDGER", "state/ledger.jsonl")

app = FastAPI(title="trellis")


def _ledger() -> Ledger:
    return Ledger(LEDGER_PATH, TimeGround())


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


# ---- the nav: plainly-named, self-describing pages -------------------------

NAV = [
    ("/", "Overview", "the one-screen read: what's live right now"),
    ("/map", "The Map", "what the room decided — and what the agent thinks about it"),
    ("/curiosities", "Assumptions", "where it knows it's assuming, and what it's chasing"),
    ("/ingestion", "Ingestion", "what's been taken in and understood — coverage and gaps"),
    ("/decisions", "Decisions", "every Yes / No / Triangulate — click one to walk its reasoning"),
    ("/reflection", "Reflection", "once a day, the agent looks at itself in the mirror of its record"),
    ("/loops", "Loops", "the background jobs, and whether each is healthy or needs a look"),
    ("/verification", "Verification", "the maker never grades its own work — who checked whom"),
    ("/agents", "Agents", "who is on the record, and how much they've been independently verified"),
    ("/activity", "Activity", "the raw event log, newest first — copy-pasteable"),
]

STYLE = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2230;--line:#30363d;--ink:#e6edf3;
--dim:#8b949e;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff;
--y:#3fb950;--n:#8b949e;--t:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
a{color:inherit;text-decoration:none}
header{display:flex;align-items:center;gap:14px;padding:14px 22px;border-bottom:1px solid var(--line)}
header h1{font-size:17px;margin:0;letter-spacing:.02em}
.tag{color:var(--dim);font-size:12px}
main{display:grid;grid-template-columns:264px 1fr;min-height:calc(100vh - 55px)}
nav{border-right:1px solid var(--line);padding:14px;display:flex;flex-direction:column;gap:4px}
nav a{display:block;padding:10px 12px;border-radius:9px;border:1px solid transparent}
nav a .t{font-weight:600}
nav a .d{font-size:11.5px;color:var(--dim);margin-top:2px}
nav a:hover{background:var(--panel)}
nav a.on{background:var(--panel2);border-color:var(--line)}
nav a.on .t{color:var(--acc)}
section{padding:22px 26px;max-width:1040px}
.pagehead h2{font-size:20px;margin:0 0 4px}
.pagehead p{color:var(--dim);margin:0 0 18px;font-size:13px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:16px;margin-bottom:16px}
.panel h3{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);margin:0 0 12px}
.row{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:0}
.pill{font-size:11px;padding:2px 9px;border-radius:20px;font-weight:700;white-space:nowrap}
.Y{background:rgba(63,185,80,.15);color:var(--y)}.N{background:rgba(139,148,158,.15);color:var(--n)}
.T{background:rgba(210,153,34,.15);color:var(--t)}.hn{background:rgba(248,81,73,.15);color:var(--bad)}
.muted{color:var(--dim)}.small{font-size:12px}.attn{color:var(--bad)}.good{color:var(--ok)}.warn{color:var(--warn)}
.legend{font-size:12px;color:var(--dim);background:var(--panel2);border:1px solid var(--line);
border-radius:9px;padding:10px 12px;margin-bottom:16px}
.legend b{color:var(--ink)}
button{background:var(--acc);color:#04101f;border:0;border-radius:6px;padding:6px 12px;font-weight:600;cursor:pointer}
button.deny{background:transparent;color:var(--bad);border:1px solid var(--bad)}
input{background:#0d1117;border:1px solid var(--line);color:var(--ink);border-radius:6px;padding:5px 8px}
.feed li{list-style:none;padding:7px 0;border-bottom:1px solid var(--line);display:flex;gap:10px}
.feed{padding:0;margin:0}.who{color:var(--acc);font-weight:600}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.mirror{display:grid;grid-template-columns:220px 1fr;gap:20px;align-items:start}
.glyphbox{text-align:center}.glyphbox .cap{font-size:11px;color:var(--dim);margin-top:6px}
.delta-up{color:var(--ok)}.delta-down{color:var(--warn)}
.kv{display:flex;gap:8px;flex-wrap:wrap}
.chip{background:var(--panel2);border:1px solid var(--line);border-radius:7px;padding:4px 9px;font-size:12px}
code{background:#0d1117;border:1px solid var(--line);border-radius:5px;padding:1px 5px;font-size:12px}
.crumbs{display:flex;flex-direction:column;gap:0}
.crumb{border-left:2px solid var(--line);padding:6px 0 6px 14px;margin-left:6px}
.crumb:first-child{border-color:var(--acc)}
"""

SHELL = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>trellis · {title}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/htmx/2.0.3/htmx.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/htmx-ext-sse/2.2.2/sse.min.js"></script>
<style>{style}</style></head><body>
<header><h1>🌱 trellis</h1><span class="tag">a comprehension &amp; reflection portal — not an ops console</span>
<span class="tag" style="margin-left:auto">{ledger} · live · SSE</span></header>
<main>
<nav>{nav}</nav>
<section hx-ext="sse" sse-connect="/stream">
  <div hx-get="{path}?frag=1" hx-trigger="sse:tick" hx-swap="innerHTML">{body}</div>
</section>
</main></body></html>"""


def _nav_html(active: str) -> str:
    out = []
    for path, title, desc in NAV:
        on = "on" if path == active else ""
        out.append(f'<a class="{on}" href="{path}"><div class="t">{esc(title)}</div>'
                   f'<div class="d">{esc(desc)}</div></a>')
    return "".join(out)


def _shell(active: str, body: str) -> str:
    title = next((t for p, t, _ in NAV if p == active), "trellis")
    return SHELL.format(title=esc(title), style=STYLE, ledger=esc(Path(LEDGER_PATH).name),
                        nav=_nav_html(active), path=active, body=body)


def _pagehead(title: str, subtitle: str) -> str:
    return f'<div class="pagehead"><h2>{esc(title)}</h2><p>{esc(subtitle)}</p></div>'


# ---- page bodies (pure-ish: ledger in, HTML out) ---------------------------

def _overview_body(led: Ledger) -> str:
    stats = views.growth_stats(led)
    gs = GlyphStats.from_growth(stats)
    inbox = views.inbox(led)
    openq = views.open_questions_view(led)
    loops = views.loop_health(led)
    feed = views.activity_feed(led, limit=8)
    out = [_pagehead("Overview", "What the agent is doing right now, in one screen.")]

    # the self-image, small, links to Reflection
    out.append('<div class="panel"><div class="mirror">')
    out.append(f'<div class="glyphbox">{render_glyph(gs, size=180)}'
               '<div class="cap">the agent\'s honest self-image — every trait is a real '
               'ledger number. <a class="good" href="/reflection">see why →</a></div></div>')
    out.append('<div>')
    out.append(f'<div class="kv" style="margin-bottom:10px">'
               f'<span class="chip">{stats["entries"]} events</span>'
               f'<span class="chip">{stats["decisions"]} decisions</span>'
               f'<span class="chip">{stats["memories"]} memories</span>'
               f'<span class="chip">{stats["verified"]}/{stats["checked"]} verified</span>'
               f'<span class="chip">{stats["age_days"]:.0f}d on the record</span></div>')
    # attention rail
    if openq:
        out.append('<div class="legend"><b class="attn">Needs attention.</b> Unresolved '
                   '“triangulate” decisions past their revisit date, plus anything re-opened:</div>')
        for q in openq:
            tag = "hidden no" if q["kind"] == "hidden-no" else "reopened"
            out.append(f'<div class="row"><div><span class="pill hn">{esc(tag)}</span> '
                       f'<a href="/decisions/{esc(q["id"])}">{esc(q["subject"])}</a>'
                       f'<div class="muted small">owner: {esc(q["owner"] or "—")} · '
                       f'missing: {esc(q["missing"] or "—")}</div></div></div>')
    else:
        out.append('<div class="good small">✓ Nothing overdue: no hidden nos, nothing re-opened.</div>')
    out.append('</div></div></div>')

    # inbox
    out.append('<div class="panel"><h3>Waiting on you · nothing sends without your yes</h3>')
    out.append(_inbox_rows(inbox))
    out.append('</div>')

    # loops + recent story
    out.append('<div class="grid2">')
    out.append('<div class="panel"><h3>Loops at a glance</h3>')
    for l in loops:
        c = "attn" if l["attention"] else "good"
        out.append(f'<div class="row"><span>{esc(l["loop"])}</span>'
                   f'<span class="{c} small">{esc(l["last_outcome"])} · {l["runs"]} runs</span></div>')
    if not loops:
        out.append('<div class="muted small">no loops registered yet.</div>')
    out.append('</div>')
    out.append('<div class="panel"><h3>Latest activity</h3><ul class="feed">')
    for f in feed:
        out.append(f'<li><span class="muted small" style="min-width:58px">{esc(f["age"])}</span>'
                   f'<span><span class="who">{esc(f["who"])}</span> {esc(f["story"])}</span></li>')
    out.append('</ul></div></div>')
    return "".join(out)


def _inbox_rows(inbox: list) -> str:
    if not inbox:
        return '<div class="muted small">No actions waiting for approval. The agent stages; you decide.</div>'
    out = []
    for a in inbox:
        out.append(f'<div class="row"><div><b>{esc(a["kind"])}</b> → {esc(a["target"])}'
                   f'<div class="muted small">{esc(a["preview"])}</div>'
                   f'<div class="muted small">staged by {esc(a["by"])} · {esc(a["age"])}</div></div>'
                   f'<form method="post" action="/approve" style="display:flex;gap:6px;align-items:center">'
                   f'<input type="hidden" name="action_id" value="{esc(a["action_id"])}">'
                   f'<input name="human" placeholder="your name" required>'
                   f'<button>approve</button>'
                   f'<button class="deny" formaction="/deny">deny</button></form></div>')
    return "".join(out)


def _decisions_body(led: Ledger) -> str:
    rows = views.decision_timeline(led, limit=100)
    out = [_pagehead("Decisions", "Every Yes / No / Triangulate the agent has committed — with lineage.")]
    out.append('<div class="legend"><b>Y</b> = commit · <b>N</b> = a real, returnable no · '
               '<b>T</b> = triangulate: a call for ≥3 named viewpoints, with an owner, a missing '
               'piece, and a revisit date. <b class="attn">A T past its revisit date is a “hidden '
               'no”.</b> Click any decision to <b>walk</b> its reasoning.</div>')
    out.append('<div class="panel">')
    if not rows:
        out.append('<div class="muted small">No decisions on the record yet.</div>')
    for d in rows:
        cls = "hn" if d["hidden_no"] else d["verdict"]
        label = "T · hidden-no" if d["hidden_no"] else d["verdict"]
        out.append(f'<div class="row"><div><span class="pill {cls}">{esc(label)}</span> '
                   f'<a href="/decisions/{esc(d["id"])}">{esc(d["subject"])}</a>'
                   f'<div class="muted small">{esc(d["rationale"])[:110]}</div>'
                   f'<div class="muted small">{esc(d["lineage"])} · {esc(d["author"])} · {esc(d["age"])}</div>'
                   f'</div><span class="muted small">walk →</span></div>')
    out.append('</div>')
    return "".join(out)


def _decision_walk_body(led: Ledger, decision_id: str) -> str:
    w = views.decision_walk(led, decision_id)
    if w is None:
        return _pagehead("Decision not found",
                         "No live decision with that id.") + \
               '<div class="panel"><a href="/decisions">← back to decisions</a></div>'
    out = [_pagehead(f"Walk · {w['subject']}",
                     "Re-inhabiting this decision read-only: the why, the viewpoints, the lineage. "
                     "Walking never re-decides — divergence is recorded, never silently flipped.")]
    out.append('<div class="panel"><a href="/decisions">← all decisions</a></div>')
    out.append('<div class="panel">')
    out.append(f'<div class="kv" style="margin-bottom:12px"><span class="pill {esc(w["verdict"])}">'
               f'{esc(w["verdict"])}</span>')
    if w["reopened"]:
        out.append('<span class="pill hn">re-opened — needs re-triangulation</span>')
    out.append('</div>')
    out.append(f'<div><b>Why:</b> {esc(w["rationale"])}</div>')
    if w["povs"]:
        out.append('<h3 style="margin-top:16px">Points of view (a T needs ≥3, named)</h3>')
        for p in w["povs"]:
            basis = f' — <span class="muted">{esc(p.get("basis"))}</span>' if p.get("basis") else ""
            out.append(f'<div class="row"><div><b>{esc(p.get("holder"))}</b>: {esc(p.get("position"))}{basis}</div></div>')
    out.append('</div>')

    out.append('<div class="panel"><h3>Lineage — breadcrumbs upstream toward the EMP</h3><div class="crumbs">')
    for c in reversed(w["upstream"]):
        out.append(f'<div class="crumb"><span class="pill {esc(c["verdict"])}">{esc(c["verdict"])}</span> '
                   f'{esc(c["subject"])} <span class="muted small">· {esc(c["emp_lineage"])} · '
                   f'{esc(c["decided"][:10])}</span></div>')
    out.append('</div></div>')
    return "".join(out)


def _self_portrait_panel(led: Ledger) -> str:
    """The daily self-portrait that builds on the previous day: a morph from
    yesterday's snapshot to today's, the growth strip of the whole chain, and an
    honest delta caption. Every trait is a deterministic function of the ledger
    snapshots the reflection ritual writes — it builds on yesterday, it never
    performs a self."""
    from .selfportrait import (portrait_delta, render_growth_strip, render_morph,
                              render_self_portrait, snapshot_series)
    series = snapshot_series(led)
    if not series:
        return ""
    today = series[-1][1]
    prev = series[-2][1] if len(series) >= 2 else None
    art = render_morph(prev, today, size=200) if prev is not None \
        else render_self_portrait(today, None, size=200)
    delta = portrait_delta(prev, today)
    out = ['<div class="panel"><h3>Daily self-portrait — built on yesterday</h3>'
           '<div class="mirror">']
    out.append(f'<div class="glyphbox">{art}'
               '<div class="cap">yesterday → today (the change you see is the change '
               'in the record)</div></div>')
    out.append('<div><div class="legend">This portrait is a deterministic morph of '
               'two real self-image snapshots — it grows out of the previous day, and '
               'changes only because the record changed. It is not a mood.</div>')
    out.append('<ul class="feed">' + "".join(
        f'<li><span>{esc(x)}</span></li>' for x in delta) + '</ul></div></div>')
    if len(series) >= 2:
        out.append(f'<div style="margin-top:14px;overflow-x:auto">{render_growth_strip(series)}</div>')
    out.append('</div>')
    return "".join(out)


def _reflection_body(led: Ledger) -> str:
    r = views.reflection_view(led)
    stats = views.growth_stats(led)
    gs = GlyphStats.from_growth(stats)
    out = [_pagehead("Reflection",
                     "Once a day the agent looks at itself in the mirror of its own record — "
                     "grounded, cited, and honest. It is a data-visualisation of real numbers, "
                     "never a claim to a self.")]
    out.append(_self_portrait_panel(led))
    if r is None:
        out.append('<div class="panel"><div class="mirror">')
        out.append(f'<div class="glyphbox">{render_glyph(gs, size=200)}'
                   '<div class="cap">today\'s self-image</div></div>')
        out.append('<div><div class="legend">The daily reflection ritual hasn\'t run yet, so there\'s '
                   'no “yesterday” to compare against. This is the current self-image from the live '
                   'record; every trait below is a real number.</div>')
        out.append('<ul class="feed">' + "".join(
            f'<li><span>{esc(x)}</span></li>' for x in reflection(gs)) + '</ul>')
        out.append('</div></div></div>')
        return "".join(out)

    # today's mirror
    out.append('<div class="panel"><div class="mirror">')
    out.append(f'<div class="glyphbox">{render_glyph(GlyphStats.from_growth(r["self_image"]), size=200)}'
               f'<div class="cap">today · {esc(r["age"])}</div></div>')
    out.append('<div>')
    if r["narrative"]:
        out.append(f'<div style="margin-bottom:8px">{esc(r["narrative"])}</div>')
    if r["learned"]:
        out.append(f'<div class="muted small" style="margin-bottom:12px"><b>learned:</b> {esc(r["learned"])}</div>')
    out.append('<h3>Why I look like this</h3><ul class="feed">')
    for x in r["why"]:
        out.append(f'<li><span>{esc(x)}</span></li>')
    out.append('</ul></div></div></div>')

    # yesterday vs today deltas
    if r["has_yesterday"]:
        out.append(f'<div class="panel"><h3>Yesterday → today (vs {esc(r["yesterday_age"])})</h3>')
        for k, dv in r["deltas"].items():
            d = dv["delta"]
            arrow = ""
            if isinstance(d, (int, float)) and d:
                cls = "delta-up" if d > 0 else "delta-down"
                arrow = f' <span class="{cls}">({"+" if d > 0 else ""}{d})</span>'
            out.append(f'<div class="row"><span>{esc(k)}</span>'
                       f'<span class="small">{esc(dv["prev"])} → <b>{esc(dv["now"])}</b>{arrow}</span></div>')
        out.append('</div>')

    # the cited events (clickable, real)
    out.append(f'<div class="panel"><h3>Grounded in {r["cited_count"]} real event(s)</h3>')
    for c in r["cites"][:12]:
        out.append(f'<div class="row"><span class="small">{esc(c.get("kind"))} · {esc(c.get("author"))}</span>'
                   f'<span class="muted small">{esc(c.get("when","")[:19])} · <code>{esc(c.get("id"))}</code></span></div>')
    if not r["cites"]:
        out.append('<div class="muted small">no events in the window.</div>')
    out.append('</div>')

    # self-change as a verified proposal
    sc = r["self_change"]
    if sc:
        verified = sc.get("verified")
        badge = ('<span class="pill Y">verified — may take effect</span>' if verified
                 else f'<span class="pill hn">not verified ({esc(sc.get("verdict") or "pending")}) — cannot take effect</span>')
        out.append(f'<div class="panel"><h3>Proposed self-change · staged, not applied</h3>')
        out.append(f'<div class="kv" style="margin-bottom:10px">{badge}</div>')
        out.append(f'<div><b>{esc(sc.get("target"))}</b>: {esc(sc.get("proposal"))}</div>')
        out.append(f'<div class="muted small" style="margin-top:6px">{esc(sc.get("rationale"))}</div>')
        out.append('<div class="legend" style="margin-top:12px">A self-change is only a proposal on '
                   'the record. It cannot take effect unless an <b>independent</b> verifier confirms '
                   'it — the agent never certifies its own change.</div>')
        out.append('</div>')
    return "".join(out)


def _loops_body(led: Ledger) -> str:
    loops = views.loop_health(led)
    out = [_pagehead("Loops", "The agent's background jobs — each bounded, each ending in a typed outcome.")]
    out.append('<div class="legend">Every loop has a turn budget and a plain stop condition, so it '
               'can never run silently forever. <b class="good">ok / nothing_new</b> = healthy; '
               'anything else <b class="attn">needs a look</b>.</div>')
    out.append('<div class="panel">')
    if not loops:
        out.append('<div class="muted small">No loops registered yet.</div>')
    for l in loops:
        c = "attn" if l["attention"] else "good"
        out.append(f'<div class="row"><div>{esc(l["loop"])}'
                   f'<div class="muted small">{esc(l["purpose"])[:90]}</div></div>'
                   f'<span class="{c} small">{esc(l["last_outcome"])} · {l["runs"]} runs</span></div>')
    out.append('</div>')
    return "".join(out)


def _verification_body(led: Ledger) -> str:
    trust = views.trust_panel(led)
    out = [_pagehead("Verification", "The maker never grades its own work — a self-audit is not an audit.")]
    out.append('<div class="legend">Every completion is <b>claimed with evidence</b>, then judged by '
               'a <b>different</b> agent (ideally a cheaper model with fresh context, prompted to '
               'refute). Verdicts land in the ledger, so trust compounds — or doesn\'t.</div>')
    out.append('<div class="panel"><h3>Who checked whom</h3>')
    if not trust:
        out.append('<div class="muted small">No verifications on the record yet.</div>')
    for t in trust:
        tv = "—" if t["trust"] is None else f'{int(t["trust"]*100)}%'
        out.append(f'<div class="row"><span>{esc(t["maker"])}</span>'
                   f'<span class="small"><span class="good">{t["verified"]}✓</span> '
                   f'<span class="attn">{t["refuted"]}✗</span> '
                   f'<span class="muted">{t["insufficient"]}?</span> · {tv} verified</span></div>')
    out.append('</div>')
    return "".join(out)


def _agents_body(led: Ledger) -> str:
    ros = views.roster(led)
    out = [_pagehead("Agents", "Who is on the record — with how much they've been independently verified.")]
    out.append('<div class="panel">')
    for r in ros:
        tv = "unproven" if r["trust"] is None else f'{int(r["trust"]*100)}% trust'
        out.append(f'<div class="row"><div>{esc(r["agent"])}'
                   f'<div class="muted small">{r["decisions"]} decisions · {r["actions"]} events</div></div>'
                   f'<span class="muted small">{esc(tv)} · last seen {esc(r["last_seen"])}</span></div>')
    if not ros:
        out.append('<div class="muted small">no agents on the record yet.</div>')
    out.append('</div>')
    return "".join(out)


def _activity_body(led: Ledger) -> str:
    feed = views.activity_feed(led, limit=200)
    out = [_pagehead("Activity", "Every recorded event, newest first — the debug log you can copy and hand to someone.")]
    out.append('<div class="panel"><ul class="feed">')
    for f in feed:
        out.append(f'<li><span class="muted small" style="min-width:70px">{esc(f["age"])}</span>'
                   f'<span><span class="who">{esc(f["who"])}</span> {esc(f["story"])} '
                   f'<span class="muted small">· {esc(f["kind"])}</span></span></li>')
    if not feed:
        out.append('<li class="muted small">the ledger is empty.</li>')
    out.append('</ul></div>')
    return "".join(out)


def _conf_pill(conf) -> str:
    if conf is None:
        return '<span class="pill hn">unproven</span>'
    pct = int(conf * 100)
    cls = "Y" if conf >= 0.66 else "T" if conf >= 0.4 else "hn"
    return f'<span class="pill {cls}">{pct}% sure</span>'


def _map_body(led: Ledger) -> str:
    rows = views.observations_map(led)
    out = [_pagehead("The Map",
                     "What the room decided, as the agent understood it — and, beside each, "
                     "the agent's own opinion. Confidence is stated; the transcript may be "
                     "wrong; click any to see exactly how it got there.")]
    out.append('<div class="legend">Each card is a <b>decision the agent observed</b> in the '
               'record, attributed to the people in the room — <b>not</b> the agent\'s own '
               'ruling. Its own take sits beside it. Low confidence and machine-transcribed '
               'sources are flagged, never hidden.</div>')
    if not rows:
        out.append('<div class="panel"><div class="muted small">Nothing ingested yet — the '
                   'Map fills in as transcripts and Discord come through Ingestion.</div></div>')
    for r in rows:
        who = ", ".join(r["attributed_to"]) or "—"
        machine = ' <span class="pill hn">machine-heard</span>' if r["machine"] else ""
        aff = f' · <span class="good small">✓ affirmed ×{r["affirmed"]}</span>' if r["affirmed"] else ""
        op = ""
        if r["opinion_verdict"]:
            op = (f'<div class="muted small" style="margin-top:6px">'
                  f'<b>my take [{esc(r["opinion_verdict"])}]:</b> {esc(r["opinion"])[:150]}</div>')
        out.append(f'<div class="panel"><div class="row"><div>'
                   f'<span class="pill {esc(r["verdict"])}">{esc(r["verdict"])}</span> '
                   f'<a href="/observation/{esc(r["id"])}">{esc(r["subject"])}</a>{machine}'
                   f'<div class="muted small">the room: {esc(who)}{aff}</div>{op}</div>'
                   f'<div>{_conf_pill(r["confidence"])}<div class="muted small" '
                   f'style="text-align:right;margin-top:4px">how it got here →</div></div></div></div>')
    return "".join(out)


def _observation_body(led: Ledger, obs_id: str) -> str:
    lin = views.observation_lineage(led, obs_id)
    if lin is None:
        return _pagehead("Not found", "No observation with that id.") + \
               '<div class="panel"><a href="/map">← the Map</a></div>'
    out = [_pagehead(f"How I got here · {lin['subject']}",
                     "The full lineage: what the room decided, what I think about it, the "
                     "moments it rests on, and how sure I am — with the honest caveats.")]
    out.append('<div class="panel"><a href="/map">← the Map</a></div>')
    # the observation
    out.append('<div class="panel"><h3>What the room decided (attributed to them)</h3>')
    out.append(f'<div class="kv" style="margin-bottom:8px"><span class="pill {esc(lin["verdict"])}">'
               f'{esc(lin["verdict"])}</span> {_conf_pill(lin["confidence"])}'
               + (' <span class="pill hn">machine-heard</span>' if lin["machine"] else '') + '</div>')
    out.append(f'<div>{esc(lin["rationale"])}</div>')
    out.append(f'<div class="muted small" style="margin-top:6px">the room: '
               f'{esc(", ".join(lin["attributed_to"]) or "—")}</div>')
    # affirm
    out.append('<form method="post" action="/affirm" style="margin-top:12px;display:flex;gap:8px;align-items:center">'
               f'<input type="hidden" name="decision_id" value="{esc(lin["id"])}">'
               '<input name="human" placeholder="your name" required>'
               '<button>✓ yes, that\'s right</button>'
               f'<span class="muted small">affirming compounds confidence — it never gates the agent'
               + (f' · already affirmed ×{lin["affirmed"]}' if lin["affirmed"] else '') + '</span></form>')
    out.append('</div>')
    # honesty caveats
    out.append('<div class="legend"><b>Honesty:</b> I only had the words — the transcript '
               'can be wrong, sarcastic, or out of order. '
               + ('The time is the transcript\'s claim, not ground truth. ' if lin["event_time_reconstructed"] else '')
               + ('This rests on machine transcription (lower confidence). ' if lin["machine"] else '')
               + 'Confidence above is my honest estimate, stated not felt.</div>')
    # the agent's opinion
    if lin["opinion"]:
        o = lin["opinion"]
        out.append('<div class="panel"><h3>What I think about it (my own opinion)</h3>'
                   f'<div class="kv" style="margin-bottom:8px"><span class="pill {esc(o.get("verdict"))}">'
                   f'{esc(o.get("verdict"))}</span></div><div>{esc(o.get("rationale"))}</div></div>')
    # cited moments
    out.append('<div class="panel"><h3>The moments it rests on</h3>')
    for c in lin["cited"]:
        m = ' · machine-transcribed' if c["machine"] else ''
        out.append(f'<div class="row"><span class="small">{esc(c["source"])} · {esc(c["channel"])} '
                   f'<span class="muted">({esc(c["kind"])}{m})</span></span>'
                   f'<span class="muted small"><code>{esc(c["ref"])}</code></span></div>')
    if not lin["cited"]:
        out.append('<div class="muted small">no source refs recorded.</div>')
    out.append('</div>')
    return "".join(out)


def _curiosities_body(led: Ledger) -> str:
    c = views.curiosities(led)
    out = [_pagehead("Assumptions & Curiosities",
                     "Where the agent knows it's assuming, and what it's actively trying to "
                     "learn. This is the contemplating mind, made watchable.")]
    out.append('<div class="legend">An open question that sits <b class="attn">past its '
               'revisit date</b> lights up — a curiosity can\'t be emitted and forgotten. '
               'A <b>dry streak</b> means it keeps looking and nothing moves: a signal to '
               'ask a human, not to declare victory. "I searched" is never "I understand."</div>')
    if c["stale_count"]:
        out.append(f'<div class="attn small" style="margin-bottom:10px">⚠ {c["stale_count"]} '
                   'question(s) overdue — surface these before anything else.</div>')
    for q in c["open"]:
        badge = '<span class="pill hn">overdue</span> ' if q["stale"] else ""
        dry = (f' · <span class="warn small">dry streak {q["dry_streak"]}</span>'
               if q["dry_streak"] else "")
        reask = f' · re-asked ×{q["reasked"]}' if q["reasked"] else ""
        out.append(f'<div class="panel"><div>{badge}<b>{esc(q["title"])}</b></div>'
                   f'<div class="muted small" style="margin-top:4px">assuming: '
                   f'{esc(q["assumption"])}</div>'
                   f'<div class="muted small">would resolve it: {esc(q["what_would_resolve"])}</div>'
                   f'<div class="muted small">owner: {esc(q["owner"])}{dry}{reask}</div></div>')
    if not c["open"]:
        out.append('<div class="panel"><div class="muted small">No open questions — either '
                   'nothing\'s puzzling, or the agent hasn\'t contemplated yet today.</div></div>')
    return "".join(out)


def _ingestion_body(led: Ledger) -> str:
    s = views.ingestion_status(led)
    out = [_pagehead("Ingestion",
                     "What's been taken in and understood — our own ledger as the truth of "
                     "what we know, honest about how much rests on machine transcription.")]
    out.append(f'<div class="panel"><div class="kv">'
               f'<span class="chip">{s["items_ingested"]} items ingested</span>'
               f'<span class="chip">{s["observations"]} decisions understood</span>'
               f'<span class="chip">{s["machine_transcribed"]} machine-transcribed</span></div></div>')
    out.append('<div class="panel"><h3>By source</h3>')
    for src, n in (s.get("by_source") or {}).items():
        out.append(f'<div class="row"><span>{esc(src)}</span><span class="muted small">{n} items</span></div>')
    if not s.get("by_source"):
        out.append('<div class="muted small">nothing ingested yet — point the adapters at '
                   'the Atlas dumps to begin.</div>')
    out.append('</div>')
    return "".join(out)


# ---- routes ----------------------------------------------------------------

def _respond(active: str, body: str, frag: bool) -> HTMLResponse:
    return HTMLResponse(body if frag else _shell(active, body))


@app.get("/", response_class=HTMLResponse)
def home(frag: int = 0):
    return _respond("/", _overview_body(_ledger()), bool(frag))


@app.get("/map", response_class=HTMLResponse)
def the_map(frag: int = 0):
    return _respond("/map", _map_body(_ledger()), bool(frag))


@app.get("/observation/{obs_id}", response_class=HTMLResponse)
def observation_detail(obs_id: str, frag: int = 0):
    body = _observation_body(_ledger(), obs_id)
    if frag:
        return HTMLResponse(body)
    return HTMLResponse(SHELL.format(
        title="The Map", style=STYLE, ledger=esc(Path(LEDGER_PATH).name),
        nav=_nav_html("/map"), path=f"/observation/{obs_id}", body=body))


@app.get("/curiosities", response_class=HTMLResponse)
def curiosities_page(frag: int = 0):
    return _respond("/curiosities", _curiosities_body(_ledger()), bool(frag))


@app.get("/ingestion", response_class=HTMLResponse)
def ingestion_page(frag: int = 0):
    return _respond("/ingestion", _ingestion_body(_ledger()), bool(frag))


@app.post("/affirm")
def affirm(decision_id: str = Form(...), human: str = Form(...)):
    from trellis.identity import is_effectively_blank
    if is_effectively_blank(human):
        raise HTTPException(status_code=400, detail="an affirmation needs a named human")
    led = _ledger()
    led.append(kind="affirmation", author=human,
               body={"decision_id": decision_id, "via": "web-ui"},
               tags=("affirm", decision_id))
    return RedirectResponse(f"/observation/{decision_id}", status_code=303)


@app.get("/decisions", response_class=HTMLResponse)
def decisions(frag: int = 0):
    return _respond("/decisions", _decisions_body(_ledger()), bool(frag))


@app.get("/decisions/{decision_id}", response_class=HTMLResponse)
def decision_detail(decision_id: str, frag: int = 0):
    # detail pages refresh themselves in place; keep the nav highlight on Decisions
    body = _decision_walk_body(_ledger(), decision_id)
    if frag:
        return HTMLResponse(body)
    title = "Decisions"
    return HTMLResponse(SHELL.format(
        title=esc(title), style=STYLE, ledger=esc(Path(LEDGER_PATH).name),
        nav=_nav_html("/decisions"), path=f"/decisions/{decision_id}", body=body))


@app.get("/reflection", response_class=HTMLResponse)
def reflection_page(frag: int = 0):
    return _respond("/reflection", _reflection_body(_ledger()), bool(frag))


@app.get("/loops", response_class=HTMLResponse)
def loops_page(frag: int = 0):
    return _respond("/loops", _loops_body(_ledger()), bool(frag))


@app.get("/verification", response_class=HTMLResponse)
def verification_page(frag: int = 0):
    return _respond("/verification", _verification_body(_ledger()), bool(frag))


@app.get("/agents", response_class=HTMLResponse)
def agents_page(frag: int = 0):
    return _respond("/agents", _agents_body(_ledger()), bool(frag))


@app.get("/activity", response_class=HTMLResponse)
def activity_page(frag: int = 0):
    return _respond("/activity", _activity_body(_ledger()), bool(frag))


@app.get("/glyph", response_class=HTMLResponse)
def glyph():
    return render_glyph(GlyphStats.from_growth(views.growth_stats(_ledger())))


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
    inbox reads. (Firing the action itself is the harness's job, not the UI's.)

    The independence gate lives here too, not only in stage.Outbox: this endpoint
    writes the authoritative lifecycle event, so without the guard the staging
    agent could self-approve on the UI even though the library refuses it
    (refusal #5). approval_guard enforces named-human + maker != approver."""
    led = _ledger()
    problem = views.approval_guard(led, action_id, human)
    if problem:
        raise HTTPException(status_code=403, detail=problem)
    led.append(kind="staged_action", author=human,
               body={"action_id": action_id, "event": "approved" if approve else "denied",
                     "status": "approved" if approve else "denied", "via": "web-ui"},
               tags=("outbox", "approved" if approve else "denied"))


@app.get("/stream")
async def stream():
    """SSE: tail the ledger file; emit a 'tick' whenever it grows so the current
    page refreshes. Simple size-poll — no broker, works over any filesystem."""
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
