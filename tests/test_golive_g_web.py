"""Go-live hardening — group G (the portal / web seats).

TEST-FIRST regressions for the confirmed defects on the ONE live human-write
surface. Owned files: web/app.py, web/views.py.

Covered:
  * Codex#9  — `trellis web` ignored the .env `trellis init` wrote (import-time
               globals never loaded config).
  * Codex#18 — the portal inflated trust by dropping PRECONDITIONS_PASSED from
               the denominator; /agents and /verification disagreed for the same
               maker. Every trust display must come from verify.trust_record().
  * FableG8  — web seats: (i) /ratify accepted UNVERIFIED proposals (silent
               dead-end yes); (ii) human seats never ran require_identity (a
               homoglyph passed); (iii) rejected proposals stayed in the open
               queue with live buttons; (iv) the approval card showed only a
               ≤280-char preview while the full payload was persisted, unshown.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from trellis.clock import TimeGround
from trellis.ledger import Ledger
from trellis.selfimprove import (ImprovementEngine, ImprovementProposal,
                                 ProposalTarget)
from trellis.stage import Outbox, StagedAction
from trellis.verify import RuleVerifier, trust_record
from web import views

REPO = Path(__file__).resolve().parents[1]


# ---- Codex#9: web.app must load .env BEFORE its import-time globals ----------

def test_web_reads_dotenv_at_import(tmp_path):
    """A dir with a .env (stable secret, human alice, custom ledger). Importing
    web.app in that dir must yield a STABLE authenticator (not ephemeral), human
    'alice', and the custom ledger — proof config is loaded before the globals."""
    (tmp_path / ".env").write_text(
        "TRELLIS_APPROVER_SECRET=stable-portal-secret\n"
        "TRELLIS_HUMAN=alice\n"
        "TRELLIS_LEDGER=custom/led.jsonl\n",
        encoding="utf-8")
    script = textwrap.dedent(f"""
        import sys, json
        sys.path.insert(0, {str(REPO)!r})
        import web.app as app
        print(json.dumps({{
            "ephemeral": app._LOGIN_TOKEN is not None,
            "human": app._AUTH.human_id,
            "ledger": app.LEDGER_PATH,
        }}))
    """)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TRELLIS_")}
    r = subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["ephemeral"] is False        # a stable secret was configured in .env
    assert out["human"] == "alice"          # not the "operator" default
    assert out["ledger"] == "custom/led.jsonl"


# ---- Codex#18 + Fable four-formulas: one canonical trust everywhere ----------

def test_trust_displays_agree_and_do_not_inflate(ledger, ground):
    """1 verified + 99 preconditions-passed → trust 0.01, NOT 1.0. Both /agents
    (roster) and /verification (trust_panel) must equal verify.trust_record()."""
    ledger.append("decision", "witness:a", {"decision_id": "d1", "subject": "x", "verdict": "Y"})
    for _ in range(99):
        ledger.append("verification", "verifier:v",
                      {"maker": "witness:a", "status": "preconditions_passed"})
    ledger.append("verification", "verifier:v", {"maker": "witness:a", "status": "verified"})

    canonical = trust_record(ledger, "witness:a")["verified_ratio"]
    assert canonical == pytest.approx(0.01)

    ros = {r["agent"]: r for r in views.roster(ledger, ground)}
    tp = {t["maker"]: t for t in views.trust_panel(ledger, ground)}
    assert ros["witness:a"]["trust"] == pytest.approx(round(canonical, 2))
    assert tp["witness:a"]["trust"] == pytest.approx(round(canonical, 2))
    assert ros["witness:a"]["trust"] == tp["witness:a"]["trust"]   # agree, page-to-page
    assert ros["witness:a"]["trust"] != pytest.approx(1.0)         # not inflated


# ---- FableG8(iv): the approval card renders the FULL payload -----------------

def test_inbox_carries_full_payload_not_only_preview(ledger, ground):
    long = "X" * 400
    Outbox(ledger, ground).stage(StagedAction("discord_post", "#c", long, created_by="witness:a"))
    box = views.inbox(ledger, ground)
    assert box and box[0]["content"] == long          # full payload available
    assert len(box[0]["preview"]) <= 280              # preview is still bounded


def test_approval_card_html_shows_the_full_payload(ledger, ground):
    import web.app as app
    long = "PAYLOAD-" + "Z" * 400
    Outbox(ledger, ground).stage(StagedAction("discord_post", "#c", long, created_by="witness:a"))
    html = app._inbox_rows(views.inbox(ledger, ground))
    assert long in html               # the whole thing the human vouches for is shown


# ---- FableG8(iii): rejected proposals leave the open queue -------------------

def test_rejected_proposal_is_excluded_from_open_list(ledger, ground):
    eng = ImprovementEngine(ledger, "witness", ground=ground)
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "tweak", "because"))
    eng.reject(p.id, "alex", reason="declined")
    v = views.improvement_view(ledger, ground)
    pid = p.body["proposal_id"]
    assert all(pr["proposal_id"] != pid for pr in v["proposals"])   # gone from open queue


# ---- web-endpoint seats (auth + ratify gate) --------------------------------

def _login(client, webapp):
    r = client.post("/login", data={"token": webapp._LOGIN_TOKEN}, follow_redirects=False)
    assert r.status_code == 303


def _fresh_ledger(tmp_path, name="l.jsonl"):
    path = tmp_path / name
    return Ledger(path, TimeGround()), path


# FableG8(i): /ratify must refuse an UNVERIFIED proposal (no silent dead-end)

def test_ratify_refuses_unverified_proposal(tmp_path):
    import web.app as webapp
    led, path = _fresh_ledger(tmp_path)
    eng = ImprovementEngine(led, "witness")
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "no evidence", "hunch"))
    assert p.body["verified"] is False
    webapp.LEDGER_PATH = str(path)
    client = TestClient(webapp.app)
    _login(client, webapp)
    r = client.post("/ratify", data={"entry_id": p.id}, follow_redirects=False)
    assert r.status_code == 403                    # loud refusal, not a silent yes
    # and the proposal is still in the open queue — the human isn't left with a ghost
    assert any(pr["entry_id"] == p.id for pr in views.improvement_view(Ledger(path, TimeGround()))["proposals"])


# FableG8(i): a VERIFIED proposal still ratifies

def test_ratify_accepts_verified_proposal(tmp_path):
    import web.app as webapp
    g = TimeGround()
    led, path = _fresh_ledger(tmp_path, "l2.jsonl")
    ev = [led.append("decision", "witness", {"decision_id": "d", "subject": "burn"}).id]
    eng = ImprovementEngine(led, "witness",
                            verifier=RuleVerifier("verifier:check", ledger=led, ground=g), ground=g)
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "write typed outcome",
                                        "recurred", evidence_ids=ev))
    assert p.body["verified"] is True
    webapp.LEDGER_PATH = str(path)
    client = TestClient(webapp.app)
    _login(client, webapp)
    r = client.post("/ratify", data={"entry_id": p.id}, follow_redirects=False)
    assert r.status_code == 303
    ratified = [e for e in Ledger(path, TimeGround()).entries()
                if e.kind == "improvement_proposal" and e.body.get("disposition") == "Y"]
    assert ratified and ratified[-1].author == webapp._AUTH.human_id


# FableG8(ii): a homoglyph principal is refused at a web write seat

def test_web_write_seat_refuses_homoglyph_identity(tmp_path, monkeypatch):
    import web.app as webapp
    from trellis.auth import Principal
    led, path = _fresh_ledger(tmp_path, "l3.jsonl")
    aid = Outbox(led).stage(StagedAction("discord_post", "#c", "draft", created_by="witness"))
    webapp.LEDGER_PATH = str(path)
    # a principal whose id carries a Cyrillic 'е' — the round-4 self-cert attack class
    monkeypatch.setattr(webapp, "_principal",
                        lambda request: Principal("witnеss", authenticated=True))
    client = TestClient(webapp.app)
    r = client.post("/approve", data={"action_id": aid}, follow_redirects=False)
    assert r.status_code == 400        # exotic id refused at the seat, not guessed
