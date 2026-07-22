"""The /sessions surface shows DM content, so it is owner-only even on localhost
(Alex, 2026-07-21): an unauthenticated GET redirects to /login, unlike the open
comprehension pages. After the owner logs in, it renders."""

from fastapi.testclient import TestClient

from web import app as webapp


def test_sessions_requires_login(monkeypatch, tmp_path):
    monkeypatch.setattr(webapp, "LEDGER_PATH", str(tmp_path / "l.jsonl"))
    c = TestClient(webapp.app)
    r = c.get("/sessions", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    r2 = c.get("/session/whatever", follow_redirects=False)
    assert r2.status_code == 303 and r2.headers["location"] == "/login"


def test_sessions_renders_once_logged_in(monkeypatch, tmp_path):
    monkeypatch.setattr(webapp, "LEDGER_PATH", str(tmp_path / "l.jsonl"))
    c = TestClient(webapp.app)
    c.post("/login", data={"token": webapp._LOGIN_TOKEN}, follow_redirects=False)
    assert c.get("/sessions", follow_redirects=False).status_code == 200


def test_open_comprehension_pages_still_dont_require_login(monkeypatch, tmp_path):
    monkeypatch.setattr(webapp, "LEDGER_PATH", str(tmp_path / "l.jsonl"))
    c = TestClient(webapp.app)
    assert c.get("/decisions", follow_redirects=False).status_code == 200
