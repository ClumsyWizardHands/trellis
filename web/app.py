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

from trellis import config
from trellis.clock import TimeGround
from trellis.ledger import Ledger

from . import views
from .glyph import GlyphStats, reflection, render_glyph

# Codex#9: the ledger/auth globals below are created at IMPORT, so the .env that
# `trellis init` wrote must be loaded FIRST — otherwise `trellis web` AND the
# direct `trellis-web` entry point both boot ephemeral (default human/ledger,
# a fresh login token each run), silently ignoring the operator's configuration.
# load_dotenv never overrides an already-set env var, so an explicit env still wins.
config.load_dotenv()

LEDGER_PATH = os.environ.get("TRELLIS_LEDGER", "state/ledger.jsonl")

app = FastAPI(title="trellis")

# --- authentication (Codex Critical 1): the approver is derived from a SIGNED
# SESSION, never a form field. Set TRELLIS_APPROVER_SECRET + TRELLIS_HUMAN for a
# stable credential, or the server mints an ephemeral one and prints a one-time
# login token to the console (see main()). ---
from trellis.auth import Authenticator, Principal
_AUTH, _LOGIN_TOKEN = Authenticator.from_env_or_ephemeral()
SESSION_COOKIE = "trellis_session"


def _ledger() -> Ledger:
    return Ledger(LEDGER_PATH, TimeGround())


def _principal(request: Request) -> "Principal | None":
    """The authenticated human this request is acting as, or None — read from the
    signed session cookie, NEVER from a form field."""
    return _AUTH.verify_session(request.cookies.get(SESSION_COOKIE))


@app.exception_handler(HTTPException)
async def _friendly_auth_redirect(request: Request, exc: HTTPException):
    """A signed-out human clicking a Y/N/T button must land on the LOGIN page,
    not a black screen of raw JSON (Alex hit exactly that, 2026-07-22). Only
    401s redirect; every other error keeps its honest JSON."""
    from fastapi.responses import JSONResponse
    if exc.status_code == 401:
        # a failed LOGIN must say so, not silently re-show the form
        if request.url.path == "/login":
            return RedirectResponse("/login?bad=1", status_code=303)
        return RedirectResponse("/login", status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def _require_human(request: Request) -> str:
    """The canonical id of the authenticated approver, or 401. This replaces the
    old caller-supplied `human` form field: authority is now server-verified.

    FableG8(ii): run the authenticated id through require_identity at this single
    choke point, so EVERY web write seat (approve/deny/ratify/reject/affirm) refuses
    a homoglyph/exotic id rather than guessing it — the library human seats
    (selfimprove.ratify/reject) don't fold confusables, so we refuse loud here."""
    from trellis.identity import InvalidIdentityError, require_identity
    p = _principal(request)
    if p is None or not p.authenticated:
        raise HTTPException(status_code=401,
                            detail="not signed in — visit /login and enter the approver token")
    try:
        return require_identity(p.id, "approver")
    except InvalidIdentityError:
        raise HTTPException(status_code=400,
                            detail="approver identity is not a plain ASCII id — refused, not guessed")


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


# ---- the nav: plainly-named, self-describing pages -------------------------

NAV = [
    ("/", "Overview", "the one-screen read: what's live right now"),
    ("/map", "The Map", "what the room decided — and what the agent thinks about it"),
    ("/curiosities", "Assumptions", "where it knows it's assuming, and what it's chasing"),
    ("/days", "Day walk", "history read one day at a time, newest first — each day checked by you"),
    ("/ingestion", "Ingestion", "what's been taken in and understood — coverage and gaps"),
    ("/sessions", "Sessions", "every conversation on the record — who, where, and what was said"),
    ("/decisions", "Decisions", "every Yes / No / Triangulate — click one to walk its reasoning"),
    ("/reflection", "Reflection", "once a day, the agent looks at itself in the mirror of its record"),
    ("/improvement", "Improvement", "how it wants to get better at its own job — proposals you ratify"),
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
button.good{background:var(--ok);color:#03180a}
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
<style>{style}
#livedot{{display:inline-block;width:.55em;height:.55em;border-radius:50%;background:#3a5;
margin-right:.35em;opacity:.35;transition:opacity .2s}}
#livedot.pulse{{opacity:1;box-shadow:0 0 6px #3a5}}</style></head><body>
<header><h1>🌱 trellis</h1><span class="tag">a comprehension &amp; reflection portal — not an ops console</span>
<span class="tag" style="margin-left:auto"><span id="livedot"></span><span id="livetxt">live</span> · {ledger} · <a href="/login" style="color:var(--acc)">sign in</a></span></header>
<main>
<nav>{nav}</nav>
<section>
  <div id="live" data-frag="{path}?frag=1">{body}</div>
</section>
</main>
<script>
/* Live updates, dependency-free: the server emits an SSE 'tick' whenever the
   ledger grows; each tick re-fetches this page's fragment and swaps it in.
   (The htmx SSE *extension* silently failed to fire hx-trigger="sse:tick" —
   a raw EventSource works everywhere, so the portal drives itself.) */
(function () {{
  var live = document.getElementById('live');
  var dot = document.getElementById('livedot');
  var txt = document.getElementById('livetxt');
  var last = Date.now();
  var busy = false;
  function refresh() {{
    if (busy) return;
    busy = true;
    fetch(live.dataset.frag, {{credentials: 'same-origin'}})
      .then(function (r) {{ return r.ok ? r.text() : null; }})
      .then(function (html) {{
        if (html !== null) {{
          live.innerHTML = html;
          if (window.htmx) htmx.process(live);
          last = Date.now();
          dot.classList.add('pulse');
          setTimeout(function () {{ dot.classList.remove('pulse'); }}, 400);
        }}
      }})
      .finally(function () {{ busy = false; }});
  }}
  var es = new EventSource('/stream');
  es.addEventListener('tick', refresh);
  setInterval(function () {{
    txt.textContent = 'live · updated ' + Math.round((Date.now() - last) / 1000) + 's ago';
  }}, 1000);
}})();
</script>
</body></html>"""


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

#: write-activity → a human stage label. The overview's "Latest activity" feed
#: sorts by EVENT time (history), so during a backfill it shows the past being
#: read, not the work being done — this panel is the WRITE-time view: what the
#: agent's hands are doing this second.
_STAGES = {
    "ingest_marker":       ("SWALLOWING", "bulk-reading the record — documents and history go in first; understanding comes after, and takes many sessions"),
    "source_document":     ("SWALLOWING", "reading documents into the ledger, one attributed entry each"),
    "discord_message":     ("SWALLOWING", "ingesting Discord history, oldest first"),
    "discord_poll_cursor": ("SWALLOWING", "checkpointing its place in the history (a restart resumes here)"),
    "discord_backfill":    ("SWALLOWING", "backfilling Discord history in bounded chunks"),
    "question":            ("WONDERING", "minting curiosity nodes — terms and people it refuses to assume"),
    "seek":                ("TRACING", "pursuing an open question through the record"),
    "term_observation":    ("TRACING", "recording a traced understanding, with provenance and capped confidence"),
    "verification":        ("VERIFYING", "an independent seat is judging a claim — the maker never grades its own work"),
    "panel_verdict":       ("VERIFYING", "the Haiku panel is voting, refute-by-default"),
    "memory_write":        ("MAPPING", "writing the navigable map beside the record"),
    "onboard_pass":        ("RESTING", "learning pass recorded — the next one runs on the half-hour"),
    "context_manifest":    ("THINKING", "compiling the context packet a model will reason over"),
    "onboard_stage":       ("WORKING", "a learning-pass stage is underway (detail in the tail)"),
    "day_digest":          ("READING", "reading one day of the record as a unit, newest first"),
}


def _describe_event(e) -> str:
    b = e.body
    k = e.kind
    if k == "discord_message":
        return f"{e.author} in #{b.get('channel_name') or b.get('channel','?')}: “{str(b.get('content',''))[:60]}”"
    if k == "source_document":
        return f"read “{str(b.get('title','?'))[:70]}” ({b.get('source','?')})"
    if k == "ingest_marker":
        return f"{b.get('phase','?')} ingesting {b.get('source','?')} item"
    if k == "question":
        return f"now curious: {str(b.get('title','?'))[:70]}"
    if k == "seek":
        return f"pursued: {str(b.get('searched','?'))[:70]}"
    if k == "term_observation":
        return f"traced the term “{b.get('term','?')}” (confidence {b.get('confidence')})"
    if k in ("verification", "panel_verdict"):
        return f"{e.author} → {b.get('status','?')} on {str(b.get('task') or b.get('claim_id') or '?')[:50]}"
    if k == "memory_write":
        return f"wrote {b.get('path','?')}"
    if k == "onboard_pass":
        return f"pass: {b.get('status','?')} · {len(b.get('terms_pursued') or [])} term(s) pursued"
    if k == "discord_poll_cursor":
        return f"checkpointed #{str(b.get('channel','?'))[:24]}"
    if k == "onboard_stage":
        return f"stage: {b.get('stage','?')} — {str(b.get('detail',''))[:80]}"
    if k == "day_digest":
        return (f"read day {b.get('day','?')} as a unit — "
                f"“{str(b.get('summary',''))[:60]}”")
    return k.replace("_", " ")


def _now_panel(led: Ledger) -> str:
    entries = led.entries()
    now = led.ground.now()
    recent = [x for x in entries[-120:]
              if (now - x.stamp.write_time).total_seconds() <= 90]
    if recent:
        from collections import Counter
        dominant = Counter(x.kind for x in recent).most_common(1)[0][0]
        stage, phrase = _STAGES.get(dominant, ("WORKING", f"writing {dominant} entries"))
        sub = f"{esc(phrase)} · <b>{len(recent)}</b> ledger writes in the last 90s"
    elif entries and entries[-1].kind in ("onboard_stage", "context_manifest"):
        # the LAST thing written was a stage marker — a compute/model stretch
        # is underway; ledger silence here is thinking, not death.
        age = int((now - entries[-1].stamp.write_time).total_seconds())
        stage = "THINKING"
        sub = (f"{esc(_describe_event(entries[-1]))} — in progress, started "
               f"{age}s ago (model and compute stages write nothing until "
               "they land; this marker is how you can tell)")
    elif entries:
        age = int((now - entries[-1].stamp.write_time).total_seconds())
        stage = "QUIET"
        sub = (f"nothing being written right now — last activity {age}s ago; "
               "the learning pass runs on its cadence, and quiet is honest, not stuck")
    else:
        stage, sub = "EMPTY", "no record yet — run <code>trellis begin</code>"
    out = ['<div class="panel"><h3>Right now — what the agent is actually doing</h3>',
           f'<div class="legend"><span class="pill hn">{esc(stage)}</span> {sub}</div>',
           '<ul class="feed">']
    for e in entries[-10:][::-1]:
        ago = max(0, int((now - e.stamp.write_time).total_seconds()))
        out.append(f'<li><span class="muted small" style="min-width:58px">{ago}s ago</span>'
                   f'<span>{esc(_describe_event(e))}</span></li>')
    out.append('</ul><div class="muted small">write-time view: this is the work being '
               'done this second — the “Latest activity” feed below is the history '
               'being read (event time), which is why it can look old.</div></div>')
    return "".join(out)


def _days_chip(led: Ledger) -> str:
    """Comprehension-in-time, on the front page: days read as units vs days in
    the record — the honest 'how much of the past is actually understood'."""
    try:
        from trellis.onboard import comprehension
        c = comprehension(led)
        return (f'<a class="chip" href="/days" style="text-decoration:none">'
                f'{c["days_digested"]}/{c["days_total"]} days walked</a>')
    except Exception:
        return ""


def _overview_body(led: Ledger) -> str:
    stats = views.growth_stats(led)
    gs = GlyphStats.from_growth(stats)
    inbox = views.inbox(led)
    openq = views.open_questions_view(led)
    loops = views.loop_health(led)
    feed = views.activity_feed(led, limit=8)
    out = [_pagehead("Overview", "What the agent is doing right now, in one screen.")]

    # the live "what am I doing" view — stage + write-time tail (asked for by
    # Alex, 2026-07-22: "a blank canvas with occasional numbers going up" is
    # not legibility; the work itself must be visible)
    out.append(_now_panel(led))

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
               f'<span class="chip">{stats["age_days"]:.0f}d on the record</span>'
               f'{_days_chip(led)}</div>')
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
    # D54: the day-walk's human gate is a first-class "waiting on you"
    try:
        from trellis.onboard import latest_day_digest, pending_review_day
        pd = pending_review_day(led)
    except Exception:
        pd = None
    if pd:
        b = (latest_day_digest(led, pd) or type("E", (), {"body": {}})).body
        out.append(
            f'<div class="row"><div><span class="pill hn">day check</span> '
            f'my reading of <b>{esc(pd)}</b> awaits your Y/N/T '
            f'<div class="muted small">“{esc(str(b.get("summary",""))[:140])}”</div>'
            f'<div class="muted small"><a class="good" href="/days">answer with '
            f'the Y/N/T buttons on the Day-walk page →</a> or in a terminal: '
            f'<code>trellis day {esc(pd)} yes|no|triangulate "note"</code>'
            f'</div></div></div>')
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
        # FableG8(iv): the human vouches for the FULL payload, not a ≤280-char
        # preview — the preview is exactly the injection window staging exists to
        # close. Render the whole persisted payload (expandable) on the approval card.
        content = a.get("content", a["preview"])
        truncated = len(content) > len(a["preview"])
        full = (f'<details{"" if not truncated else " open"}>'
                f'<summary class="muted small">full payload ({len(content)} chars) — '
                f'this is what your yes vouches for</summary>'
                f'<pre style="white-space:pre-wrap;word-break:break-word;margin:6px 0 0">'
                f'{esc(content)}</pre></details>')
        out.append(f'<div class="row"><div><b>{esc(a["kind"])}</b> → {esc(a["target"])}'
                   f'<div class="muted small">{esc(a["preview"])}</div>{full}'
                   f'<div class="muted small">staged by {esc(a["by"])} · {esc(a["age"])}</div></div>'
                   f'<form method="post" action="/approve" style="display:flex;gap:6px;align-items:center">'
                   f'<input type="hidden" name="action_id" value="{esc(a["action_id"])}">'
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
    from trellis.decisions import question_key
    from trellis.onboard import TERM_OBSERVATION_KIND, term_from_assumption
    obs_by_key = {e.body.get("term_key"): e
                  for e in led.active(TERM_OBSERVATION_KIND)}
    # SPLIT (Alex, 2026-07-22): questions that genuinely need the human's
    # Y/N/T float to the TOP; everything else is the agent's OWN research
    # agenda — listed, never presented as the human's homework.
    from trellis.onboard import term_review_for
    needs_you, in_hand, researching = [], [], []
    for q in c["open"]:
        term = term_from_assumption(q.get("assumption") or "")
        obs = obs_by_key.get("term:" + question_key(term)) if term else None
        if term and obs is not None and (obs.body.get("meaning") or "").strip():
            r = term_review_for(led, term)
            if r is not None and r.body.get("verdict") in ("N", "T"):
                in_hand.append((q, term, r))     # answered — back with the agent
            else:
                needs_you.append(q)
        else:
            researching.append(q)
    if needs_you:
        out.append(f'<h3 style="margin-top:14px">Needs your Y/N/T '
                   f'<span class="muted small">({len(needs_you)} reading(s) '
                   'I have brought you)</span></h3>')
    if in_hand:
        out.append(f'<h3 style="margin-top:18px">Back in my hands '
                   f'<span class="muted small">({len(in_hand)} — you answered; '
                   'I am re-reading and will bring a deeper version)</span></h3>')
        for q, term, r in in_hand:
            v = r.body.get("verdict")
            if v == "T":
                note = (r.body.get("note") or "").strip()
                line = ('△ you triangulated'
                        + (f': “{esc(note[:160])}”' if note else "")
                        + ' — re-reading with this folded in on the coming pass')
            else:
                line = ('✗ you said no — re-reading on my own '
                        '(your reason deliberately not shown to me)')
            out.append(f'<div class="panel"><div><b>{esc(q["title"])}</b></div>'
                       f'<div class="muted small" style="margin-top:4px">{line}'
                       '</div></div>')
    for q in needs_you + [None] + researching:
        if q is None:
            out.append(
                f'<h3 style="margin-top:18px">On my mind '
                f'<span class="muted small">({len(researching)} question(s) '
                'I am researching on my own — I will bring you a reading; '
                'nothing here needs you)</span></h3>')
            continue
        badge = '<span class="pill hn">overdue</span> ' if q["stale"] else ""
        dry = (f' · <span class="warn small">dry streak {q["dry_streak"]}</span>'
               if q["dry_streak"] else "")
        reask = f' · re-asked ×{q["reasked"]}' if q["reasked"] else ""
        term = term_from_assumption(q.get("assumption") or "")
        out.append(f'<div class="panel"><div>{badge}<b>{esc(q["title"])}</b>'
                   f'<span class="muted small"> · owner {esc(q["owner"])}'
                   f'{dry}{reask}</span></div>')
        if not term:
            # non-term curiosities (presence etc.) keep the full question shape
            out.append(f'<div class="muted small" style="margin-top:4px">'
                       f'{esc(q["what_would_resolve"])}</div>')
        else:
            # TERM curiosity: LEAD WITH TRELLIS'S OWN ATTEMPT (Alex, 2026-07-22:
            # "trellis should have plenty of agency to come up with a good try"
            # — the human's job is confirm-or-correct, never write-from-scratch).
            obs = obs_by_key.get("term:" + question_key(term))
            b = obs.body if obs is not None else {}
            meaning = (b.get("meaning") or "").strip()
            if meaning:
                out.append(
                    f'<div style="margin-top:6px">my read '
                    f'<span class="muted small">(confidence {b.get("confidence")} '
                    '— unconfirmed until the panel or you)</span>: '
                    f'<b>{esc(meaning)}</b></div>')
                if b.get("unsure"):
                    out.append(f'<div class="muted small">still unsure: '
                               f'{esc(b["unsure"])}</div>')
                if b.get("evidence_window"):
                    out.append(f'<div class="muted small">{esc(b["evidence_window"])}</div>')
                # full Y/N/T (Alex: "not only a yes"): N sends it back to dig
                # on its own; T carries the note; Y confirms (the note, when
                # given, is the human's own wording).
                out.append(
                    '<form method="post" action="/term-review" '
                    'style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
                    f'<input type="hidden" name="term" value="{esc(term)}">'
                    '<button name="verdict" value="yes" class="good">✓ Yes — that\'s right</button>'
                    '<button name="verdict" value="no">✗ No — keep digging (I won\'t say why)</button>'
                    '<button name="verdict" value="triangulate">△ Triangulate with note →</button>'
                    '<input name="note" placeholder="clarifying note (steers the re-read on T; '
                    'your own wording on Y; recorded but withheld on N)" '
                    'style="flex:1;min-width:240px"></form></div>')
                continue
            else:
                # the agent's OWN research agenda — status only, no input box
                # soliciting the human (the form hides behind a details toggle
                # for the rare case the human simply knows and wants to say).
                lin = (b.get("lineage") or {}) if obs is not None else {}
                status = (f'traced ({lin.get("occurrences", "?")} use(s)) — '
                          'reading in progress'
                          if obs is not None else
                          'researching — I will trace it and bring you a reading')
                out.append(f'<div class="muted small" style="margin-top:4px">'
                           f'{status}</div>')
                out.append(
                    '<details class="small" style="margin-top:6px">'
                    '<summary class="muted">I already know this one — tell it</summary>'
                    '<form method="post" action="/confirm-term" '
                    'style="margin-top:6px;display:flex;gap:8px;align-items:center">'
                    f'<input type="hidden" name="term" value="{esc(term)}">'
                    f'<input name="meaning" required placeholder="what '
                    f'\'{esc(term)}\' means here" style="flex:1;min-width:240px">'
                    '<button class="good">✓ Confirm</button></form></details>')
        out.append('</div>')
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


def _sessions_body(led: Ledger) -> str:
    from trellis.registry import IdentityRegistry
    rows = views.session_log(led, IdentityRegistry(led))
    out = [_pagehead("Sessions",
                     "Every conversation the agent is on the record for — DMs individuated "
                     "per person, threads on their own, each channel as one rolling session.")]
    out.append('<div class="legend">Transparency is the operating principle: <b>everything is '
               'recorded within sessions</b>, and anyone who speaks to this agent should know '
               'they are being recorded. A <b>DM stays private to the person it is with</b> — it '
               'never crosses into a channel. Click a session to read its transcript.</div>')
    out.append('<div class="panel">')
    if not rows:
        out.append('<div class="muted small">No conversations on the record yet — sessions '
                   'appear here as Discord messages come through.</div>')
    for r in rows:
        pill = {"dm": "T", "thread": "N", "channel": "Y"}.get(r["surface"], "N")
        out.append(f'<div class="row"><div>'
                   f'<span class="pill {pill}">{esc(r["surface"])}</span> '
                   f'<a href="/session/{esc(r["session_id"])}">{esc(r["who"])}</a>'
                   f'<div class="muted small">#{esc(r["channel"])}'
                   + (f' · id {esc(r["person_id"])}' if r["person_id"] else '')
                   + f'</div></div>'
                   f'<span class="muted small">{r["count"]} message(s) · {esc(r["age"])}</span></div>')
    out.append('</div>')
    return "".join(out)


def _session_detail_body(led: Ledger, session_id: str) -> str:
    from trellis.registry import IdentityRegistry
    d = views.session_detail(led, IdentityRegistry(led), session_id)
    if d is None:
        return _pagehead("Session not found", "No session with that id.") + \
               '<div class="panel"><a href="/sessions">← all sessions</a></div>'
    out = [_pagehead(f"Session · {d['who']}",
                     "The full transcript, oldest first — the legible record of who said what. "
                     "A DM is shown only here, scoped to the person it is with; it never crosses "
                     "into a channel context.")]
    out.append('<div class="panel"><a href="/sessions">← all sessions</a></div>')
    out.append(f'<div class="panel"><div class="kv">'
               f'<span class="chip">{esc(d["surface"])}</span>'
               f'<span class="chip">#{esc(d["channel"])}</span>'
               + (f'<span class="chip">id {esc(d["person_id"])}</span>' if d["person_id"] else '')
               + f'<span class="chip">{d["count"]} message(s)</span>'
               f'<span class="chip">last {esc(d["age"])}</span></div></div>')
    out.append('<div class="panel"><ul class="feed">')
    for m in d["messages"]:
        out.append(f'<li><span class="muted small" style="min-width:62px">{esc(m["age"])}</span>'
                   f'<span><span class="who">{esc(m["author"])}</span> {esc(m["content"])}</span></li>')
    if not d["messages"]:
        out.append('<li class="muted small">no messages in this session.</li>')
    out.append('</ul></div>')
    return "".join(out)


def _require_login_redirect(request: Request):
    """A page that requires the owner's login. Unlike the write seats (which 401),
    an unauthenticated GET redirects to /login — friendlier for a browsed page.
    The Sessions surface shows DM CONTENT, so it is owner-only even on localhost
    (Alex, 2026-07-21), unlike the other read pages which are open comprehension."""
    p = _principal(request)
    if p is None or not p.authenticated:
        return RedirectResponse("/login", status_code=303)
    return None


@app.get("/sessions", response_class=HTMLResponse)
def sessions_page(request: Request, frag: int = 0):
    gate = _require_login_redirect(request)
    if gate is not None:
        return gate
    return _respond("/sessions", _sessions_body(_ledger()), bool(frag))


@app.get("/session/{session_id}", response_class=HTMLResponse)
def session_detail_page(request: Request, session_id: str, frag: int = 0):
    gate = _require_login_redirect(request)
    if gate is not None:
        return gate
    body = _session_detail_body(_ledger(), session_id)
    if frag:
        return HTMLResponse(body)
    return HTMLResponse(SHELL.format(
        title="Sessions", style=STYLE, ledger=esc(Path(LEDGER_PATH).name),
        nav=_nav_html("/sessions"), path=f"/session/{session_id}", body=body))


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    who = _principal(request)
    if who is not None:
        return _shell("/", f'{_pagehead("Signed in", f"You are signed in as {esc(who.id)}.")}'
                      '<div class="panel"><form method="post" action="/logout">'
                      '<button class="deny">sign out</button></form></div>')
    bad = ('<div class="attn small" style="margin-bottom:8px">✗ that token was '
           'not right — try again</div>'
           if request.query_params.get("bad") else "")
    body = (f'{_pagehead("Sign in", "Approvals are the human seat — they must be authenticated, not typed in. Your token is TRELLIS_APPROVER_SECRET in the repo .env (or the console line printed at server start).")}'
            f'<div class="panel">{bad}'
            '<form method="post" action="/login" style="display:flex;gap:8px;align-items:center">'
            '<input name="token" type="password" placeholder="approver token" required autofocus>'
            '<button>sign in</button></form></div>')
    return _shell("/", body)


@app.post("/login")
def login(request: Request, token: str = Form(...)):
    from trellis.auth import AuthError
    try:
        principal = _AUTH.authenticate(token)
    except AuthError:
        raise HTTPException(status_code=401, detail="invalid approver token")
    resp = RedirectResponse("/", status_code=303)
    # Secure only when actually served over TLS — setting it on plaintext localhost
    # would stop the cookie being stored at all. HttpOnly + SameSite=strict always.
    over_tls = request.url.scheme == "https"
    resp.set_cookie(SESSION_COOKIE, _AUTH.issue_session(principal),
                    httponly=True, samesite="strict", secure=over_tls,
                    max_age=_AUTH.SESSION_TTL)
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


def _days_body(led: Ledger) -> str:
    """The day-walk as a visible timeline (D53/D54): newest first, each day's
    reading with its state — and the pending day's Y/N/T as BUTTONS, the same
    authenticated seat the other web writes use."""
    from trellis.onboard import (DAY_DIGEST_KIND, day_review_state,
                                 pending_review_day)
    out = [_pagehead("Day walk",
                     "comprehension walks backward through time, one checkable "
                     "day at a time — the panel refutes first, then you check")]
    digests = [e for e in led.active(DAY_DIGEST_KIND) if e.body.get("day")]
    digests.sort(key=lambda e: e.body["day"], reverse=True)
    if not digests:
        out.append('<div class="panel"><div class="muted">no days read yet — '
                   'the walk begins with the newest day of the record.</div></div>')
        return "".join(out)

    comp_days = {e.body["day"] for e in digests}
    pd = pending_review_day(led)
    state_pill = {
        "approved": ('good', '✓ approved by you'),
        "pending": ('hn', '⏸ awaiting your Y/N/T'),
        "rejected": ('hn', '↻ re-reading (you said no — reason withheld)'),
        "triangulating": ('hn', '↻ re-reading with your note'),
        "refuted_by_panel": ('hn', '✗ panel refuted — machine re-read queued'),
    }
    out.append(f'<div class="legend">{len(comp_days)} day(s) read as units · '
               'newest first · a day advances only past the panel AND your check</div>')
    for e in digests:
        b = e.body
        day = b["day"]
        state = day_review_state(led, day)
        cls, label = state_pill.get(state, ('good', state))
        if state == "refuted_by_panel" and int(b.get("rework", 0)) >= 2:
            label = '✗ panel refuted twice — your call now'
        out.append('<div class="panel">')
        out.append(f'<h3>{esc(day)} <span class="pill {cls}">{esc(label)}</span> '
                   f'<span class="muted small">confidence {b.get("confidence")} · '
                   f'{b.get("items", 0)} item(s) · rework {b.get("rework", 0)}</span></h3>')
        out.append(f'<div>{esc(b.get("summary") or "(counts only — no model reading)")}</div>')
        if b.get("notable"):
            out.append('<div class="small" style="margin-top:6px"><b>notable:</b> '
                       + " · ".join(esc(n) for n in b["notable"]) + '</div>')
        if b.get("unclear"):
            out.append('<div class="small muted" style="margin-top:4px"><b>unclear:</b> '
                       + " · ".join(esc(u) for u in b["unclear"]) + '</div>')
        if b.get("human_note"):
            out.append(f'<div class="small" style="margin-top:4px"><b>your note:</b> '
                       f'{esc(b["human_note"])}</div>')
        if day == pd:
            out.append(
                '<form method="post" action="/day-review" '
                'style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
                f'<input type="hidden" name="day" value="{esc(day)}">'
                '<button name="verdict" value="yes" class="good">✓ Yes — walk on</button>'
                '<button name="verdict" value="no">✗ No — look again (I won\'t say why)</button>'
                '<button name="verdict" value="triangulate">△ Triangulate with note →</button>'
                '<input name="note" placeholder="clarifying note (rides the re-read on T; '
                'recorded but withheld on N)" style="flex:1;min-width:240px">'
                '</form>')
        out.append('</div>')
    return "".join(out)


@app.get("/days", response_class=HTMLResponse)
def days_page(frag: int = 0):
    return _respond("/days", _days_body(_ledger()), bool(frag))


@app.post("/term-review")
def term_review_post(request: Request, term: str = Form(...),
                     verdict: str = Form(...), note: str = Form("")):
    human = _require_human(request)      # server-verified, not a form field
    from pathlib import Path as _P
    from trellis.curiosity import QuestionLog
    from trellis.memory import Workspace
    from trellis.onboard import review_term
    led = _ledger()
    vp = os.environ.get("TRELLIS_VAULT_PATH", "").strip()
    root = _P(vp).expanduser() if vp else _P(LEDGER_PATH).parent / "workspace"
    try:
        review_term(led, Workspace(root, led), QuestionLog(led),
                    term, verdict, human, note)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/curiosities", status_code=303)


@app.post("/confirm-term")
def confirm_term_post(request: Request, term: str = Form(...),
                      meaning: str = Form(...)):
    human = _require_human(request)      # server-verified, not a form field
    from pathlib import Path as _P
    from trellis.curiosity import QuestionLog
    from trellis.memory import Workspace
    from trellis.onboard import confirm_term_meaning
    led = _ledger()
    vp = os.environ.get("TRELLIS_VAULT_PATH", "").strip()
    root = _P(vp).expanduser() if vp else _P(LEDGER_PATH).parent / "workspace"
    try:
        confirm_term_meaning(led, Workspace(root, led), QuestionLog(led),
                             term, human, meaning, led.ground)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/curiosities", status_code=303)


@app.post("/day-review")
def day_review_post(request: Request, day: str = Form(...),
                    verdict: str = Form(...), note: str = Form("")):
    human = _require_human(request)      # server-verified, not a form field
    from trellis.onboard import review_day
    try:
        review_day(_ledger(), day, verdict, human, note)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse("/days", status_code=303)


@app.post("/affirm")
def affirm(request: Request, decision_id: str = Form(...)):
    human = _require_human(request)      # server-verified, not a form field
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


def _improvement_body(led: Ledger) -> str:
    v = views.improvement_view(led)
    out = [_pagehead("Improvement",
                     "How the agent wants to get better at its own job. It watches its own "
                     "record for stumbles and proposes fixes — but it can never change itself "
                     "alone: every proposal is independently verified and waits for your yes.")]
    out.append(f'<div class="legend">It has recorded <b>{v["burns"]}</b> burn(s) about itself, '
               f'and is nagging on <b>{len(v["questions"])}</b> open improvement question(s)'
               + (f' — <span class="attn">{v["stale_count"]} overdue</span>' if v["stale_count"] else '')
               + '. A question closes only when you ratify a fix; noticing a stumble is not improving.</div>')
    # the improvement questions (staleness rail)
    if v["questions"]:
        out.append('<div class="panel"><h3>What it thinks it should change about how it works</h3>')
        for q in v["questions"]:
            pill = '<span class="pill hn">overdue</span> ' if q["stale"] else ''
            out.append(f'<div class="row"><div>{pill}{esc(q["title"])}'
                       f'<div class="muted small">assuming: {esc(q["assumption"])}</div></div></div>')
        out.append('</div>')
    # the proposals awaiting the human
    out.append('<div class="panel"><h3>Proposed self-changes — your call</h3>')
    if not v["proposals"]:
        out.append('<div class="muted small">No proposals waiting. When the agent proposes a '
                   'change to itself, it appears here for you to ratify or deny.</div>')
    for p in v["proposals"]:
        vpill = ('<span class="pill Y">independently verified</span>' if p["verified"]
                 else f'<span class="pill hn">unverified ({esc(p["verdict"] or "—")})</span>')
        w1 = (f' · <span class="pill T">external — default N</span>' if p["disposition"] == "N" else '')
        sc = (f'<div class="muted small">supply-chain note: {esc(p["supply_chain"])}</div>'
              if p["supply_chain"] else '')
        out.append(f'<div class="row"><div><b>{esc(p["target"])}</b> {vpill}{w1}'
                   f'<div>{esc(p["proposal"])}</div>'
                   f'<div class="muted small">why: {esc(p["rationale"])} · source: {esc(p["source"])} '
                   f'· evidence: {len(p["evidence"])} entr(y/ies)</div>{sc}</div>'
                   f'<form method="post" action="/ratify" style="display:flex;gap:6px;align-items:center">'
                   f'<input type="hidden" name="entry_id" value="{esc(p["entry_id"])}">'
                   f'<button>ratify</button>'
                   f'<button class="deny" formaction="/reject_improvement">deny</button></form></div>')
    out.append('</div>')
    return "".join(out)


@app.get("/improvement", response_class=HTMLResponse)
def improvement_page(frag: int = 0):
    return _respond("/improvement", _improvement_body(_ledger()), bool(frag))


def _proposal_verified(led: Ledger, entry_id: str) -> "bool | None":
    """Re-derive from the append-only record whether a proposal carries an
    INDEPENDENT verified verdict (author != the proposing agent) for its exact
    claim. None if there is no such proposal. Never trusts the body's own
    `verified` flag — the record is the authority (parity with can_take_effect)."""
    from trellis.identity import is_independent
    from trellis.selfimprove import PROPOSAL_KIND
    e = led.get(entry_id)
    if e is None or e.kind != PROPOSAL_KIND:
        return None
    claim_id = e.body.get("claim_id")
    if not claim_id:
        return False
    for v in led.entries():
        if (v.kind == "verification" and v.body.get("claim_id") == claim_id
                and v.body.get("status") == "verified"
                and is_independent(e.author, v.author)):
            return True
    return False


@app.post("/ratify")
def ratify(request: Request, entry_id: str = Form(...)):
    from trellis.selfimprove import ImprovementEngine, UnverifiedProposalError
    human = _require_human(request)
    led = _ledger()
    # FableG8(i): refuse to ratify an UNVERIFIED proposal. Without this the human's
    # yes is a silent dead-end — the proposal leaves the queue but can never take
    # effect (can_take_effect still requires an independent verified verdict). Say so
    # loudly instead. Belt-and-suspenders: selfimprove.ratify should require this too.
    verified = _proposal_verified(led, entry_id)
    if verified is None:
        raise HTTPException(status_code=404, detail="no such proposal")
    if not verified:
        raise HTTPException(
            status_code=403,
            detail=("this proposal has no independent verified verdict on the record — "
                    "ratifying it would be a dead-end yes (it could never take effect). "
                    "It must be independently verified first."))
    try:
        ImprovementEngine(led, author="web").ratify(entry_id, human)
    except (UnverifiedProposalError, ValueError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="no such proposal")
    return RedirectResponse("/improvement", status_code=303)


@app.post("/reject_improvement")
def reject_improvement(request: Request, entry_id: str = Form(...)):
    from trellis.selfimprove import ImprovementEngine, UnverifiedProposalError
    human = _require_human(request)
    led = _ledger()
    try:
        ImprovementEngine(led, author="web").reject(entry_id, human, reason="declined in the portal")
    except (UnverifiedProposalError, ValueError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="no such proposal")
    return RedirectResponse("/improvement", status_code=303)


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
def approve(request: Request, action_id: str = Form(...)):
    _record_decision(action_id, _require_human(request), approve=True)
    return RedirectResponse("/", status_code=303)


@app.post("/deny")
def deny(request: Request, action_id: str = Form(...)):
    _record_decision(action_id, _require_human(request), approve=False)
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
    # Approvals require an authenticated session. If no TRELLIS_APPROVER_SECRET was
    # configured, an ephemeral login token was minted — print it here, once, to the
    # console the operator launched (only they can see it → only they can approve).
    if _LOGIN_TOKEN:
        print("\n" + "=" * 64, flush=True)
        print(f"  trellis approver login token (this session):\n\n      {_LOGIN_TOKEN}\n", flush=True)
        print(f"  visit http://{args.host}:{args.port}/login and paste it to approve.", flush=True)
        print(f"  (set TRELLIS_APPROVER_SECRET + TRELLIS_HUMAN for a stable one.)", flush=True)
        print("=" * 64 + "\n", flush=True)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
