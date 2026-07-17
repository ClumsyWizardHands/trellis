"""views.py — PURE transforms: the ledger → human-legible view models.

Every function here takes a Ledger (and a TimeGround) and returns plain dicts/
lists the templates render. No FastAPI, no I/O beyond reading the ledger — so
every view is unit-testable and deterministic. This is the "comprehend tier":
the story of what the agent did, in the operator's language, not raw spans.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from trellis.clock import TimeGround
from trellis.ledger import Ledger


def _ground(ledger: Ledger, ground: Optional[TimeGround]) -> TimeGround:
    return ground or ledger.ground


# ---- roster: who's alive, and how much you trust them ----------------------

def roster(ledger: Ledger, ground: Optional[TimeGround] = None) -> list[dict]:
    """One row per agent seen in the ledger: activity, trust, last-seen."""
    g = _ground(ledger, ground)
    entries = ledger.entries()
    agents: dict[str, dict] = {}
    for e in entries:
        a = e.author
        r = agents.setdefault(a, {"agent": a, "actions": 0, "last": e.stamp.event_time,
                                  "verified": 0, "refuted": 0, "decisions": 0})
        r["actions"] += 1
        if e.stamp.event_time > r["last"]:
            r["last"] = e.stamp.event_time
        if e.kind == "decision":
            r["decisions"] += 1
    # attach verification outcomes per maker
    for e in entries:
        if e.kind == "verification":
            maker = e.body.get("maker")
            if maker in agents:
                st = e.body.get("status")
                if st == "verified":
                    agents[maker]["verified"] += 1
                elif st == "refuted":
                    agents[maker]["refuted"] += 1
    out = []
    for r in agents.values():
        checked = r["verified"] + r["refuted"]
        r["trust"] = round(r["verified"] / checked, 2) if checked else None
        r["last_seen"] = g.age_phrase(r["last"])
        r["last"] = r["last"].isoformat()
        out.append(r)
    return sorted(out, key=lambda x: x["actions"], reverse=True)


# ---- decision timeline: Y/N/T with lineage + hidden nos --------------------

def decision_timeline(ledger: Ledger, ground: Optional[TimeGround] = None,
                      limit: int = 50) -> list[dict]:
    g = _ground(ledger, ground)
    now = g.now()
    current = ledger.current("decision")
    rows = []
    for e in current:
        b = e.body
        revisit = b.get("revisit_at")
        hidden_no = bool(b.get("verdict") == "T" and revisit
                         and datetime.fromisoformat(revisit) < now)
        rows.append({
            "id": b.get("decision_id"),
            "subject": b.get("subject"),
            "verdict": b.get("verdict"),
            "rationale": b.get("rationale"),
            "lineage": b.get("emp_lineage"),
            "author": e.author,
            "when": e.stamp.event_time.isoformat(),
            "age": g.age_phrase(e.stamp.event_time),
            "owner": b.get("owner"),
            "missing": b.get("missing"),
            "revisit": revisit,
            "hidden_no": hidden_no,
            "povs": b.get("povs", []),
        })
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows[:limit]


def hidden_no_count(ledger: Ledger, ground: Optional[TimeGround] = None) -> int:
    return sum(1 for r in decision_timeline(ledger, ground, limit=10000)
               if r["hidden_no"])


# ---- loop health -----------------------------------------------------------

def loop_health(ledger: Ledger, ground: Optional[TimeGround] = None) -> list[dict]:
    specs = ledger.current("loop_spec")
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    by_loop: dict[str, list] = {}
    for e in ends:
        by_loop.setdefault(e.body.get("loop"), []).append(e)
    rows = []
    for s in specs:
        name = s.body["name"]
        runs = by_loop.get(name, [])
        last = runs[-1].body.get("outcome") if runs else "NEVER RAN"
        rows.append({
            "loop": name,
            "purpose": s.body.get("purpose", ""),
            "runs": len(runs),
            "last_outcome": last,
            "attention": last not in ("ok", "nothing_new"),
        })
    return rows


# ---- inbox: staged actions awaiting a human yes ----------------------------

def inbox(ledger: Ledger, ground: Optional[TimeGround] = None) -> list[dict]:
    """Reconstruct the staged-action lifecycle from the ledger. Anything whose
    latest event is 'staged' (not approved/denied/fired) is pending."""
    g = _ground(ledger, ground)
    latest: dict[str, dict] = {}
    for e in ledger.entries():
        if e.kind != "staged_action":
            continue
        aid = e.body.get("action_id")
        if not aid:
            continue
        latest[aid] = {
            "action_id": aid,
            "kind": e.body.get("kind"),
            "target": e.body.get("target"),
            "preview": e.body.get("content_preview", ""),
            "event": e.body.get("event", "staged"),
            "status": e.body.get("status", "staged"),
            "by": e.author,
            "when": e.stamp.event_time.isoformat(),
            "age": g.age_phrase(e.stamp.event_time),
        }
    return [r for r in latest.values()
            if r["status"] == "staged" and r["event"] in ("staged", None)]


# ---- trust panel: verification outcomes per maker --------------------------

def trust_panel(ledger: Ledger, ground: Optional[TimeGround] = None) -> list[dict]:
    makers: dict[str, dict] = {}
    for e in ledger.entries():
        if e.kind != "verification":
            continue
        m = e.body.get("maker")
        r = makers.setdefault(m, {"maker": m, "verified": 0, "refuted": 0,
                                  "insufficient": 0})
        st = e.body.get("status")
        if st in r:
            r[st] += 1
    out = []
    for r in makers.values():
        total = r["verified"] + r["refuted"] + r["insufficient"]
        r["total"] = total
        r["trust"] = round(r["verified"] / total, 2) if total else None
        out.append(r)
    return sorted(out, key=lambda x: x["total"], reverse=True)


# ---- memory map: titles only (memory is navigation) ------------------------

def memory_map(ledger: Ledger, ground: Optional[TimeGround] = None) -> list[dict]:
    g = _ground(ledger, ground)
    rows = []
    for e in ledger.entries():
        if e.kind == "memory_write":
            rows.append({"path": e.body.get("path"), "author": e.author,
                         "when": e.stamp.event_time.isoformat(),
                         "age": g.age_phrase(e.stamp.event_time),
                         "why": e.body.get("synthesis_justification", "")[:120]})
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows


# ---- activity feed: the story, newest first --------------------------------

_KIND_STORY = {
    "decision": lambda b: f"decided [{b.get('verdict')}] {b.get('subject')}",
    "verification": lambda b: f"{b.get('status')} {b.get('maker')}'s work",
    "panel_verdict": lambda b: f"panel {b.get('status')} a claim by {b.get('maker')}",
    "loop_run_end": lambda b: f"loop {b.get('loop')} → {b.get('outcome')}",
    "staged_action": lambda b: f"{b.get('event','staged')} a {b.get('kind')} to {b.get('target')}",
    "memory_write": lambda b: f"wrote memory {b.get('path')}",
    "pass": lambda b: "coordinated a pass",
    "declassification": lambda b: "a human declassified content across a boundary",
    "discord_message": lambda b: f"ingested a message in {b.get('channel_name') or b.get('channel')}",
}


def activity_feed(ledger: Ledger, ground: Optional[TimeGround] = None,
                  limit: int = 40) -> list[dict]:
    g = _ground(ledger, ground)
    rows = []
    for e in ledger.entries():
        teller = _KIND_STORY.get(e.kind)
        if not teller:
            continue
        try:
            story = teller(e.body)
        except Exception:
            story = e.kind
        rows.append({"who": e.author, "story": story, "kind": e.kind,
                     "when": e.stamp.event_time.isoformat(),
                     "age": g.age_phrase(e.stamp.event_time)})
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows[:limit]


# ---- growth stats: the honest inputs to the self-image glyph ---------------

def growth_stats(ledger: Ledger, ground: Optional[TimeGround] = None) -> dict:
    """Every number here is a real ledger fact. The glyph is a deterministic
    function of these — so the creature is an honest data-viz, never a fiction.
    Delegates to the CORE (trellis.reflect.self_image_stats) so the harness's
    reflection ritual and the UI compute the self-image the same way — one
    source of truth."""
    from trellis.reflect import self_image_stats
    return self_image_stats(ledger, _ground(ledger, ground))
