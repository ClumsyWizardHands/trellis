"""Web approval is authenticated (Codex Critical 1): the approver comes from a
signed session, never a form field. Uses FastAPI's TestClient."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from trellis.clock import TimeGround
from trellis.ledger import Ledger
from trellis.stage import Outbox, StagedAction


def _client_with_staged_action(tmp_path):
    from web import app as webapp
    path = tmp_path / "l.jsonl"
    led = Ledger(path, TimeGround())
    aid = Outbox(led).stage(StagedAction("discord_post", "#c", "draft", created_by="witness"))
    webapp.LEDGER_PATH = str(path)
    return TestClient(webapp.app), webapp, aid


def test_approve_without_a_session_is_401(tmp_path):
    client, webapp, aid = _client_with_staged_action(tmp_path)
    r = client.post("/approve", data={"action_id": aid}, follow_redirects=False)
    assert r.status_code == 401                       # no form-field authority


def test_login_then_approve_records_the_authenticated_id(tmp_path):
    client, webapp, aid = _client_with_staged_action(tmp_path)
    # wrong token → 401
    assert client.post("/login", data={"token": "wrong"}, follow_redirects=False).status_code == 401
    # right token (the server's ephemeral login token) → session cookie
    r = client.post("/login", data={"token": webapp._LOGIN_TOKEN}, follow_redirects=False)
    assert r.status_code == 303
    # now approve works, and the LEDGER records the authenticated principal id
    r = client.post("/approve", data={"action_id": aid}, follow_redirects=False)
    assert r.status_code == 303
    led = Ledger(webapp.LEDGER_PATH, TimeGround())
    approved = [e for e in led.entries()
                if e.kind == "staged_action" and e.body.get("event") == "approved"]
    assert approved and approved[-1].author == webapp._AUTH.human_id   # not a form field


def test_a_forged_session_cookie_is_rejected(tmp_path):
    client, webapp, aid = _client_with_staged_action(tmp_path)
    client.cookies.set(webapp.SESSION_COOKIE, "bWFsbG9yeS45OTk5.deadbeefdeadbeefdeadbeefdeadbeef")
    r = client.post("/approve", data={"action_id": aid}, follow_redirects=False)
    assert r.status_code == 401                       # tamper → not authenticated
