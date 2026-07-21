"""test_p2_sessions.py — the session model + the portal Session Log (D32, D36).

A live Discord message folds into a session keyed on (agent, surface, person,
thread). DMs are individuated per interlocutor and stay legible; a thread is its
own session; a channel's non-threaded messages are one rolling per-channel
session. Deterministic, ledger-derived, no model. The portal exposes it as a
transparency surface (D36): who, what surface, how many messages, last activity.

These tests append `discord_message` entries directly in the exact body shape the
live D31 bridge produces (surface, channel, storage_key, and the stable
`author_id` snowflake) — so the session model is exercised without coupling to
ingest.py, which another agent owns (see cross_file_needs).
"""

from datetime import timedelta

from trellis.registry import IdentityRegistry
from trellis.sessions import Session, derive_sessions, session_transcript
from trellis.surfaces import ConversationKey, Surface, ThreadRef


def _emit(ledger, ground, *, author, content, minutes=0, agent="ingest",
          surface=Surface.CHANNEL, channel="C1", channel_name="general",
          thread_id=None, author_id="", is_dm=False, message_id=""):
    """Append one discord_message entry the way the live bridge does."""
    at = ground.now().replace(microsecond=0) + timedelta(minutes=minutes)
    if is_dm:
        surface = Surface.DM
    elif thread_id:
        surface = Surface.THREAD
    key = ConversationKey(
        agent=agent, surface=surface, scope=channel,
        human=author if is_dm else "",
        thread=ThreadRef(thread_id, channel) if thread_id else None)
    ledger.append(
        kind="discord_message", author=author,
        body={"content": content, "channel": channel, "channel_name": channel_name,
              "message_id": message_id or f"{author}-{minutes}", "surface": surface.value,
              "author_id": author_id, "thread_id": thread_id or "",
              "storage_key": key.storage_key()},
        event_time=at, tags=("discord", channel_name, author))


def test_two_dms_same_person_fold_into_one_session(ledger, ground):
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    _emit(ledger, ground, author="Alice", content="hi", is_dm=True, author_id="111", minutes=0)
    _emit(ledger, ground, author="Alice", content="still me", is_dm=True, author_id="111", minutes=5)
    dms = [s for s in derive_sessions(ledger, reg) if s.surface == "dm"]
    assert len(dms) == 1
    assert dms[0].message_count == 2
    assert dms[0].last_at > dms[0].first_at


def test_two_different_dm_partners_are_two_sessions(ledger, ground):
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice"); reg.resolve("222", "Bob")
    _emit(ledger, ground, author="Alice", content="hi", is_dm=True, author_id="111")
    _emit(ledger, ground, author="Bob", content="yo", is_dm=True, author_id="222", minutes=1)
    dms = [s for s in derive_sessions(ledger, reg) if s.surface == "dm"]
    assert len(dms) == 2
    assert {s.person_id for s in dms} == {reg.canonical_for("111"), reg.canonical_for("222")}


def test_a_thread_is_its_own_session(ledger, ground):
    reg = IdentityRegistry(ledger)
    _emit(ledger, ground, author="Alice", content="in thread", thread_id="T9", author_id="111")
    _emit(ledger, ground, author="Bob", content="me too", thread_id="T9", author_id="222", minutes=1)
    threads = [s for s in derive_sessions(ledger, reg) if s.surface == "thread"]
    assert len(threads) == 1                 # ONE session for the thread, both posters
    assert threads[0].thread == "T9"
    assert threads[0].message_count == 2


def test_channel_is_one_rolling_session(ledger, ground):
    reg = IdentityRegistry(ledger)
    for i in range(3):
        _emit(ledger, ground, author="Alice", content=f"m{i}", author_id="111", minutes=i)
    chans = [s for s in derive_sessions(ledger, reg) if s.surface == "channel"]
    assert len(chans) == 1                   # rolling: all non-threaded fold into one
    assert chans[0].message_count == 3
    assert chans[0].scope == "C1"


def test_rename_keeps_same_session_shows_new_label(ledger, ground):
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    _emit(ledger, ground, author="Alice", content="hi", is_dm=True, author_id="111", minutes=0)
    sid_before = [s for s in derive_sessions(ledger, reg) if s.surface == "dm"][0].session_id
    reg.resolve("111", "Alice Renamed")      # a rename — same snowflake
    _emit(ledger, ground, author="Alice Renamed", content="still me", is_dm=True,
          author_id="111", minutes=5)
    dms = [s for s in derive_sessions(ledger, reg) if s.surface == "dm"]
    assert len(dms) == 1                      # identity did not move → one session
    assert dms[0].session_id == sid_before    # stable across the rename
    assert dms[0].label == "Alice Renamed"    # the current label follows the rename
    assert dms[0].message_count == 2


def test_transcript_is_time_ordered(ledger, ground):
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    _emit(ledger, ground, author="Alice", content="first", is_dm=True, author_id="111", minutes=0)
    _emit(ledger, ground, author="Alice", content="second", is_dm=True, author_id="111", minutes=10)
    sid = [s for s in derive_sessions(ledger, reg) if s.surface == "dm"][0].session_id
    msgs = session_transcript(ledger, sid)
    assert [m["content"] for m in msgs] == ["first", "second"]


def test_derive_is_deterministic(ledger, ground):
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    _emit(ledger, ground, author="Alice", content="hi", is_dm=True, author_id="111")
    a = [s.session_id for s in derive_sessions(ledger, reg)]
    b = [s.session_id for s in derive_sessions(ledger, IdentityRegistry(ledger))]
    assert a == b


def test_dm_never_folds_with_channel(ledger, ground):
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    _emit(ledger, ground, author="Alice", content="dm", is_dm=True, author_id="111")
    _emit(ledger, ground, author="Alice", content="chan", author_id="111", channel="C1", minutes=1)
    surfaces = sorted(s.surface for s in derive_sessions(ledger, reg))
    assert surfaces == ["channel", "dm"]     # a DM and a channel post never share a session


# ---- the portal surfaces (web/views.py + web/app.py) -----------------------

def test_session_log_view_lists_sessions(ledger, ground):
    from web import views
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    _emit(ledger, ground, author="Alice", content="hi", is_dm=True, author_id="111")
    for i in range(2):
        _emit(ledger, ground, author="Bob", content=f"m{i}", author_id="222", minutes=i)
    rows = views.session_log(ledger, reg, ground)
    assert len(rows) == 2
    assert all("who" in r and "surface" in r and "count" in r and "age" in r for r in rows)


def test_session_detail_view_returns_transcript(ledger, ground):
    from web import views
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    _emit(ledger, ground, author="Alice", content="hello", is_dm=True, author_id="111")
    sid = [s for s in derive_sessions(ledger, reg) if s.surface == "dm"][0].session_id
    detail = views.session_detail(ledger, reg, sid)
    assert detail is not None
    assert detail["messages"][0]["content"] == "hello"


def test_sessions_route_200(ledger, ground, monkeypatch):
    from fastapi.testclient import TestClient
    from web import app as webapp
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    _emit(ledger, ground, author="Alice", content="hi", is_dm=True, author_id="111")
    monkeypatch.setattr(webapp, "LEDGER_PATH", str(ledger.path))
    client = TestClient(webapp.app)
    r = client.get("/sessions")
    assert r.status_code == 200
    assert "Alice" in r.text


def test_session_route_200(ledger, ground, monkeypatch):
    from fastapi.testclient import TestClient
    from web import app as webapp
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    _emit(ledger, ground, author="Alice", content="hello there", is_dm=True, author_id="111")
    sid = [s for s in derive_sessions(ledger, reg) if s.surface == "dm"][0].session_id
    monkeypatch.setattr(webapp, "LEDGER_PATH", str(ledger.path))
    client = TestClient(webapp.app)
    r = client.get(f"/session/{sid}")
    assert r.status_code == 200
    assert "hello there" in r.text
