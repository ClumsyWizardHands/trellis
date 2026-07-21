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
from trellis.verify import trust_record


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
        # Trust comes from the ONE canonical function (Codex#18 / Fable four-
        # formulas): verify.trust_record — which counts PRECONDITIONS_PASSED in the
        # denominator so "evidence openable" can't inflate trust, and makes /agents
        # agree with /verification. Never recompute trust here.
        ratio = trust_record(ledger, r["agent"])["verified_ratio"]
        r["trust"] = round(ratio, 2) if ratio is not None else None
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
            # the FULL payload the human actually vouches for (D26, VISUAL-TOUR):
            # the preview alone is the injection window staging exists to close, so
            # the approval card must render this, not just the ≤280-char preview.
            "content": e.body.get("content", e.body.get("content_preview", "")),
            "event": e.body.get("event", "staged"),
            "status": e.body.get("status", "staged"),
            "by": e.author,
            "when": e.stamp.event_time.isoformat(),
            "age": g.age_phrase(e.stamp.event_time),
        }
    return [r for r in latest.values()
            if r["status"] == "staged" and r["event"] in ("staged", None)]


def staging_author(ledger: Ledger, action_id: str) -> Optional[str]:
    """The agent that STAGED an action (the author of its 'staged' event) — the
    party the independence gate must keep out of its own approval seat."""
    for e in ledger.entries():
        if (e.kind == "staged_action" and e.body.get("action_id") == action_id
                and e.body.get("event", "staged") in ("staged", None)
                and e.body.get("status") == "staged"):
            return e.author
    return None


def approval_guard(ledger: Ledger, action_id: str, human: str) -> Optional[str]:
    """Return an error string if this approve/deny must be REFUSED, else None.

    The web endpoint writes the authoritative staged_action lifecycle event that
    `inbox()` reads back as truth, so it must enforce the SAME guard the library
    `stage.Outbox.approve` does — otherwise refusal #5 (the staging agent cannot
    approve itself) holds in the core but is bypassable on the actual human-facing
    surface. Checks: a named human, a real staged action, and maker != approver
    (identity-normalized, so 'WITNESS:A'/'witness:a' can't disguise a self-yes)."""
    from trellis.identity import (InvalidIdentityError, is_effectively_blank,
                                  require_identity, same_identity)
    if is_effectively_blank(human):
        return "approval requires a named human — a blank yes is not a yes"
    # ASCII-identity allowlist (parity with stage.Outbox and verify): a homoglyph
    # of the staging agent's id (Cyrillic 'witnеss' for 'witness') would slip past
    # same_identity, which does not fold confusables. Refuse an exotic id outright.
    try:
        require_identity(human, "approver")
    except InvalidIdentityError:
        return ("approval requires a plain ASCII identity — an exotic/homoglyph id "
                "is refused, not guessed (that was a self-approval bypass)")
    stager = staging_author(ledger, action_id)
    if stager is None:
        return f"no staged action {action_id!r} is waiting — nothing to act on"
    if same_identity(human, stager):
        return ("the staging agent cannot approve or deny its own action — "
                "approval is the human seat, the last step before the world")
    # Lifecycle-state gate (parity with stage.Outbox._require_status): a DENIED,
    # FIRED, FIRING or UNKNOWN action must never be re-approved. staging_author
    # only proves a 'staged' event once EXISTED; without this check a denied
    # action is resurrectable straight through the human seat (a raw POST to
    # /approve after a deny — the deny→approve exploit). The current status is
    # folded from the ledger by the library, so this cannot be spoofed by cache.
    from trellis.stage import ActionStatus, Outbox
    action = Outbox(ledger).get(action_id)
    if action is not None and action.status in (
            ActionStatus.DENIED, ActionStatus.FIRING,
            ActionStatus.FIRED, ActionStatus.UNKNOWN):
        return (f"action {action_id!r} is {action.status.value} — a decided or "
                "in-flight action cannot be resurrected to approved")
    return None


# ---- trust panel: verification outcomes per maker --------------------------

def trust_panel(ledger: Ledger, ground: Optional[TimeGround] = None) -> list[dict]:
    # One trust source of truth (Codex#18 / Fable four-formulas): every count AND
    # the ratio come from verify.trust_record, so /verification cannot disagree
    # with /agents and PRECONDITIONS_PASSED sits honestly in the denominator.
    makers = {e.body.get("maker") for e in ledger.entries()
              if e.kind == "verification"}
    out = []
    for m in makers:
        rec = trust_record(ledger, m)
        ratio = rec["verified_ratio"]
        out.append({
            "maker": m,
            "verified": rec["verified"],
            "refuted": rec["refuted"],
            "insufficient": rec["insufficient"],
            "preconditions_passed": rec["preconditions_passed"],
            "total": rec["total"],
            "trust": round(ratio, 2) if ratio is not None else None,
        })
    return sorted(out, key=lambda x: x["total"], reverse=True)


# ---- memory map: titles only (memory is navigation) ------------------------

def memory_map(ledger: Ledger, ground: Optional[TimeGround] = None) -> list[dict]:
    g = _ground(ledger, ground)
    rows = []
    active_ids = {e.id for e in ledger.active("memory_write")}
    for e in ledger.entries():
        if e.kind == "memory_write" and e.id in active_ids:   # titles of live memory only
            rows.append({"path": e.body.get("path"),
                         "title": e.body.get("title") or e.body.get("path"),
                         "author": e.author,
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
    "memory_write": lambda b: f"wrote memory “{b.get('title') or b.get('path')}”",
    "pass": lambda b: "coordinated a pass",
    "declassification": lambda b: "a human declassified content across a boundary",
    "discord_message": lambda b: f"ingested a message in {b.get('channel_name') or b.get('channel')}",
    "reflection_log": lambda b: (f"reflected on the day (cited {b.get('cited_count', 0)} events"
                                 + (", proposed a self-change" if b.get('self_change') else "") + ")"),
    "reopen": lambda b: f"re-opened “{b.get('subject')}” — {b.get('trigger')}",
    "retirement": lambda b: f"retired an entry from the current picture ({b.get('reason') or 'no reason given'})",
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


# ---- the reflection portal: today's self-image beside yesterday's ----------

def reflection_view(ledger: Ledger, ground: Optional[TimeGround] = None) -> Optional[dict]:
    """The Reflection page's data — produced by the harness's reflection ritual
    (trellis.reflect), never mocked. Today's grounded self-image, the cited
    'why I look like this', the day's deltas vs yesterday, and any self-change
    shown as a VERIFIED proposal. None if the ritual hasn't run yet."""
    from trellis.reflect import REFLECTION_KIND
    from web.glyph import GlyphStats, reflection as glyph_reflection
    g = _ground(ledger, ground)
    refls = sorted((e for e in ledger.entries() if e.kind == REFLECTION_KIND),
                   key=lambda e: e.stamp.event_time)
    if not refls:
        return None
    today, yest = refls[-1], (refls[-2] if len(refls) > 1 else None)
    t = today.body.get("self_image", {}) or {}
    y = (yest.body.get("self_image", {}) if yest else {}) or {}
    deltas = {}
    for k in ("entries", "decisions", "verified", "checked", "memories", "open_ts", "age_days"):
        if k in t:
            now_v = t.get(k)
            prev_v = y.get(k) if yest else None
            d = None
            if yest and isinstance(now_v, (int, float)) and isinstance(prev_v, (int, float)):
                d = round(now_v - prev_v, 2)
            deltas[k] = {"now": now_v, "prev": prev_v, "delta": d}
    return {
        "when": today.stamp.event_time.isoformat(),
        "age": g.age_phrase(today.stamp.event_time),
        "narrative": today.body.get("narrative"),
        "learned": today.body.get("learned"),
        "self_image": t,
        "why": glyph_reflection(GlyphStats.from_growth(t)) if t else [],
        "cites": today.body.get("cites", []),
        "cited_count": today.body.get("cited_count", 0),
        "self_change": today.body.get("self_change"),
        "deltas": deltas,
        "has_yesterday": yest is not None,
        "yesterday_age": g.age_phrase(yest.stamp.event_time) if yest else None,
    }


# ---- a decision that OPENS UP: the WALK reconstruction ---------------------

def decision_walk(ledger: Ledger, decision_id: str,
                  ground: Optional[TimeGround] = None) -> Optional[dict]:
    """Re-inhabit one decision (read-only): its verdict-on-record, the why, the
    named POVs, and the breadcrumbs upstream toward the EMP node. This is the
    'decisions that open up' view — memory as navigation, made visible."""
    from trellis.decisions import DecisionLog
    from trellis.navigate import Navigator
    g = _ground(ledger, ground)
    w = Navigator(DecisionLog(ledger, g)).walk(decision_id)
    if w is None:
        return None
    return {"decision_id": w.decision_id, "subject": w.subject,
            "verdict": w.as_recorded, "rationale": w.rationale,
            "povs": w.povs, "upstream": w.upstream, "reopened": w.reopened,
            "related_titles": [{"title": t, "path": p} for t, p in w.related_titles]}


# ---- open questions: the one attention rail (hidden-nos + reopened) --------

def open_questions_view(ledger: Ledger, ground: Optional[TimeGround] = None) -> list[dict]:
    from trellis.decisions import DecisionLog
    g = _ground(ledger, ground)
    log = DecisionLog(ledger, g)
    hidden_ids = {e.id for e in log.hidden_nos()}
    out = []
    for e in log.open_questions():
        out.append({
            "id": e.body.get("decision_id"),
            "subject": e.body.get("subject"),
            "verdict": e.body.get("verdict"),
            "kind": "hidden-no" if e.id in hidden_ids else "reopened",
            "owner": e.body.get("owner"),
            "missing": e.body.get("missing"),
        })
    return out


# ==== the contemplative-ingestion surfaces (Phase E) ========================

def observations_map(ledger: Ledger, ground: Optional[TimeGround] = None) -> list[dict]:
    """The vault as a navigable list: what the room decided (observations),
    each with the agent's own opinion and its confidence. Click one for the
    full lineage (how the agent got there)."""
    g = _ground(ledger, ground)
    active = ledger.active("decision")
    opinions = {e.body.get("opinion_of"): e for e in active if e.body.get("opinion_of")}
    rows = []
    for e in active:
        if not str(e.author).startswith("observer:"):
            continue
        op = opinions.get(e.body.get("decision_id"))
        rows.append({
            "id": e.body.get("decision_id"),
            "subject": e.body.get("subject"),
            "verdict": e.body.get("verdict"),
            "attributed_to": e.body.get("attributed_to") or [],
            "confidence": e.body.get("confidence"),
            "machine": (e.body.get("provenance") or {}).get("machine_transcribed", False),
            "opinion_verdict": op.body.get("verdict") if op else None,
            "opinion": op.body.get("rationale") if op else None,
            "affirmed": _affirmations(ledger).get(e.body.get("decision_id"), 0),
            "age": g.age_phrase(e.stamp.event_time),
        })
    rows.sort(key=lambda r: (r["confidence"] if r["confidence"] is not None else 1))
    return rows


def _affirmations(ledger: Ledger) -> dict:
    out: dict = {}
    for e in ledger.entries():
        if e.kind == "affirmation":
            did = e.body.get("decision_id")
            out[did] = out.get(did, 0) + 1
    return out


def observation_lineage(ledger: Ledger, observation_id: str,
                        ground: Optional[TimeGround] = None) -> Optional[dict]:
    """The one-click 'how you got here': the observation, the agent's opinion,
    the cited source moments it rests on, the confidence and its honest caveats,
    and the lineage upstream. Extends the decision WALK for observed decisions."""
    g = _ground(ledger, ground)
    obs = None
    for e in ledger.entries():
        if e.kind == "decision" and e.body.get("decision_id") == observation_id:
            obs = e
            break
    if obs is None:
        return None
    b = obs.body
    opinion = next((e.body for e in ledger.active("decision")
                    if e.body.get("opinion_of") == observation_id), None)
    # resolve the cited source moments via the ingest markers
    prov = b.get("provenance") or {}
    marker_by_key = {}
    for e in ledger.entries():
        if e.kind == "ingest_marker" and e.body.get("phase") == "complete":
            marker_by_key[e.body.get("identity_key")] = e.body
    cited = []
    for ref in prov.get("source_refs", []):
        m = marker_by_key.get(ref, {})
        cited.append({"ref": ref, "source": m.get("source", "?"),
                      "channel": m.get("channel", "?"), "kind": m.get("kind", "?"),
                      "machine": m.get("machine_transcribed", False)})
    return {
        "id": observation_id,
        "subject": b.get("subject"),
        "verdict": b.get("verdict"),
        "rationale": b.get("rationale"),
        "attributed_to": b.get("attributed_to") or [],
        "confidence": b.get("confidence"),
        "machine": prov.get("machine_transcribed", False),
        "transcript_fallible": prov.get("transcript_fallible", True),
        "event_time_reconstructed": prov.get("event_time_reconstructed", True),
        "cited": cited,
        "opinion": opinion,
        "affirmed": _affirmations(ledger).get(observation_id, 0),
        "age": g.age_phrase(obs.stamp.event_time),
    }


def curiosities(ledger: Ledger, ground: Optional[TimeGround] = None) -> dict:
    """The Assumptions & Curiosities board: where the agent knows it's assuming
    and what it's actively trying to learn — with the staleness rail visible."""
    from trellis.curiosity import QuestionLog
    g = _ground(ledger, ground)
    ql = QuestionLog(ledger, g)
    stale_ids = {e.id for e in ql.stale()}
    rows = []
    for e in ql.open_questions():
        ak = e.body.get("assumption_key")
        rows.append({
            "title": e.body.get("title"),
            "assumption": e.body.get("assumption"),
            "what_would_resolve": e.body.get("what_would_resolve"),
            "owner": e.body.get("owner"),
            "stale": e.id in stale_ids,
            "dry_streak": ql.dry_streak(ak) if ak else 0,
            "reasked": e.body.get("reasked", 0),
        })
    rows.sort(key=lambda r: (not r["stale"], -r["dry_streak"]))
    return {"open": rows, "stale_count": len(stale_ids)}


def ingestion_status(ledger: Ledger, ground: Optional[TimeGround] = None) -> dict:
    """What has been taken in and understood — our ledger as truth, honest about
    how much rests on machine transcription."""
    from trellis.sources import Ingestor
    cov = Ingestor(ledger, _ground(ledger, ground)).coverage()
    observations = sum(1 for e in ledger.active("decision")
                       if str(e.author).startswith("observer:"))
    return {**cov, "observations": observations}


def improvement_view(ledger: Ledger, ground: Optional[TimeGround] = None) -> dict:
    """The self-improvement surface: the recurring stumbles the agent is flagging
    about ITSELF (staleness-railed), and the self-change proposals awaiting the
    human — each with its evidence, its independent verdict, and whether it may yet
    take effect. Pure view over the ledger; the ratify/deny actions are auth-gated
    in the app."""
    from trellis.selfimprove import ImprovementEngine, ImprovementLoop, PROPOSAL_KIND
    g = _ground(ledger, ground)
    loop = ImprovementLoop(ledger, ground=g)
    eng = ImprovementEngine(ledger, author="witness", ground=g)
    stale_ids = {e.id for e in loop.stale_improvements()}
    questions = [{
        "title": e.body.get("title", ""),
        "assumption": e.body.get("assumption", ""),
        "stale": e.id in stale_ids,
        "reasked": e.body.get("reasked", 0),
    } for e in loop.open_improvements()]
    # proposals awaiting the human (not yet ratified/rejected)
    proposals = []
    for e in eng.open_proposals():
        # FableG8(iii): a REJECTED proposal (disposition "N") must not keep live
        # ratify/deny buttons. The library open_proposals only excludes "Y", so
        # defend here too (belt-and-suspenders on the one human-write surface).
        if e.body.get("disposition") == "N":
            continue
        pid = e.body.get("proposal_id")
        try:
            eng.can_take_effect(e.id)
            effect = True
        except Exception:
            effect = False
        proposals.append({
            "entry_id": e.id,
            "proposal_id": pid,
            "target": e.body.get("target"),
            "proposal": e.body.get("proposal"),
            "rationale": e.body.get("rationale"),
            "source": e.body.get("source"),
            "verified": bool(e.body.get("verified")),
            "verdict": e.body.get("verdict"),
            "disposition": e.body.get("disposition"),
            "evidence": e.body.get("evidence_ids", []),
            "supply_chain": e.body.get("supply_chain_note", ""),
            "can_take_effect": effect,
        })
    # count the friction burns on the record (what it learned about itself)
    burns = len(ledger.active("friction"))
    return {"questions": questions, "stale_count": len(stale_ids),
            "proposals": proposals, "burns": burns}
