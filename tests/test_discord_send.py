"""test_discord_send.py — the LIVE Discord send transport + the `trellis discord`
and `trellis run` wiring. (DECISIONS.md D38, D30, D26, D37)

The last mile: `urllib_discord_sender` actually POSTs an approved action's content
to its target surface via the stdlib-only `DiscordClient`, and the CLI wires the
hardened `DiscordExecutor` (defense-in-depth ledger re-check) into the approval
gateway. The safety floor must hold end to end:

  * NOTHING hits the network in these tests — the DiscordClient is a mock, or a real
    client with an injected `urlopen`. Not one byte leaves the machine.
  * An approved CHANNEL action posts exactly once, with the content, carrying the
    idempotency key as the Discord nonce.
  * A Surface.DM action opens a DM channel (open_dm) FIRST, then posts there.
  * A guard_act failure (non-allowlisted surface) means NO post — the surface gate
    fires before the transport.
  * The bot token NEVER appears in the send's return value or a raised error.
  * `trellis discord` refuses LOUD when unarmed/misconfigured; fully configured it
    constructs the gateway behind a DiscordExecutor and stops at the live seam.
  * `trellis run` constructs the DiscordClient from env only when configured.
"""

import argparse
import json

import pytest

from trellis import cli
from trellis.executor import (DiscordExecutor, ExecutorNotArmed,
                              urllib_discord_sender)
from trellis.isolation import Isolation, SurfaceAllowlist, SurfaceNotAllowed
from trellis.ledger import Ledger
from trellis.stage import ActionStatus, Outbox, StagedAction
from trellis.surfaces import ConversationKey, Surface


# ----- helpers ---------------------------------------------------------------


def _iso(act=("chan-1",), read=()):
    return Isolation(allow=SurfaceAllowlist(read=frozenset(read), act=frozenset(act)))


class FakeClient:
    """A stand-in DiscordClient: records post_message / open_dm calls, never a
    single byte on the wire."""

    def __init__(self):
        self.posts = []          # (channel_id, content, nonce)
        self.dms_opened = []     # user_ids

    def post_message(self, channel_id, content, nonce=None):
        self.posts.append((channel_id, content, nonce))
        return {"id": "m-1", "channel_id": channel_id}

    def open_dm(self, user_id):
        self.dms_opened.append(user_id)
        return f"dm-channel-for-{user_id}"


class _FakeResp:
    """Minimal urlopen() context-manager stand-in for the real-client path."""

    def __init__(self, body):
        self._b = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


# ----- an approved channel action posts exactly once -------------------------


def test_channel_action_posts_once_with_content_and_nonce():
    """The core send: an action's content is POSTed to its target channel exactly
    once, carrying the idempotency key as the nonce; no DM channel is opened."""
    fake = FakeClient()
    send = urllib_discord_sender(_iso(act=("chan-1",)), client=fake)
    action = StagedAction("discord_post", "chan-1", "hello world", created_by="trellis")
    resp = send(action)
    assert fake.posts == [("chan-1", "hello world", action.idempotency_key)]
    assert fake.dms_opened == []                 # a channel post never opens a DM
    assert resp["channel_id"] == "chan-1"


def test_full_approved_path_posts_exactly_once(tmp_path, ground):
    """Through the whole ratified path — stage → human approve → fire — the mock
    client is the only thing that touches the world, exactly once, and the action
    lands FIRED."""
    iso = _iso(act=("chan-1",))
    led = Ledger(str(tmp_path / "l.jsonl"), ground)
    box = Outbox(led, ground, iso=iso)
    fake = FakeClient()
    ex = DiscordExecutor(iso, send_fn=urllib_discord_sender(iso, client=fake), ledger=led)
    aid = box.stage(StagedAction("discord_post", "chan-1", "ship it", created_by="witness:a"))
    box.approve(aid, human="alex")
    box.fire(aid, executor=ex.execute)
    assert box.get(aid).status == ActionStatus.FIRED
    assert fake.posts == [("chan-1", "ship it", box.get(aid).idempotency_key)]


# ----- a DM action opens a DM channel, then posts ----------------------------


def test_dm_action_opens_dm_channel_then_posts():
    """A Surface.DM action is addressed by the owner's USER id (the allowlistable
    surface). The sender resolves it to a concrete DM channel via open_dm FIRST,
    then posts there."""
    fake = FakeClient()
    send = urllib_discord_sender(_iso(act=("user-42",)), client=fake)
    dest = ConversationKey("trellis", Surface.DM, "user-42", "owner")
    action = StagedAction("discord_dm", "user-42", "psst — a private update",
                          created_by="trellis", destination=dest)
    send(action)
    assert fake.dms_opened == ["user-42"]        # opened first
    assert fake.posts == [("dm-channel-for-user-42", "psst — a private update",
                           action.idempotency_key)]


def test_dm_full_path_through_executor(tmp_path, ground):
    """A DM through the executor: the user id is guard_act-allowlisted, open_dm
    resolves the channel, the post lands there — exactly once."""
    iso = _iso(act=("user-42",))
    led = Ledger(str(tmp_path / "l.jsonl"), ground)
    box = Outbox(led, ground, iso=iso)
    fake = FakeClient()
    ex = DiscordExecutor(iso, send_fn=urllib_discord_sender(iso, client=fake), ledger=led)
    dest = ConversationKey("trellis", Surface.DM, "user-42", "owner")
    aid = box.stage(StagedAction("discord_dm", "user-42", "hey", created_by="witness:a",
                                 destination=dest))
    box.approve(aid, human="alex")
    box.fire(aid, executor=ex.execute)
    assert fake.dms_opened == ["user-42"]
    assert fake.posts == [("dm-channel-for-user-42", "hey", box.get(aid).idempotency_key)]


# ----- a guard_act failure means NO post -------------------------------------


def test_guard_act_failure_means_no_post():
    """A non-allowlisted target surface is refused (SurfaceNotAllowed) by the
    executor's guard BEFORE the transport is reached — nothing is posted."""
    fake = FakeClient()
    iso = _iso(act=("chan-1",))
    ex = DiscordExecutor(iso, send_fn=urllib_discord_sender(iso, client=fake))
    action = StagedAction("discord_post", "chan-OTHER", "must not send", created_by="trellis")
    with pytest.raises(SurfaceNotAllowed):
        ex.execute(action)
    assert fake.posts == []
    assert fake.dms_opened == []


def test_unapproved_action_through_executor_does_not_post(tmp_path, ground):
    """Defense in depth: an armed executor holding the ledger refuses to post a
    STAGED-but-unapproved action even called directly — no post."""
    from trellis.executor import UnapprovedSendError
    iso = _iso(act=("chan-1",))
    led = Ledger(str(tmp_path / "l.jsonl"), ground)
    box = Outbox(led, ground, iso=iso)
    fake = FakeClient()
    ex = DiscordExecutor(iso, send_fn=urllib_discord_sender(iso, client=fake), ledger=led)
    aid = box.stage(StagedAction("discord_post", "chan-1", "hi", created_by="witness:a"))
    with pytest.raises(UnapprovedSendError):
        ex.execute(box.get(aid))
    assert fake.posts == []


# ----- the token never appears in output -------------------------------------


def test_token_used_to_auth_but_never_in_output(monkeypatch):
    """With a REAL DiscordClient (injected urlopen), the token authenticates the
    request (Authorization: Bot <token>) but NEVER leaks into the send's return
    value."""
    monkeypatch.setenv("TRELLIS_DISCORD_TOKEN", "SUPER-SECRET-abc123")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.headers.get("Authorization")
        return _FakeResp(json.dumps({"id": "m-9", "channel_id": "chan-1"}))

    send = urllib_discord_sender(_iso(act=("chan-1",)), urlopen=fake_urlopen)
    action = StagedAction("discord_post", "chan-1", "hi", created_by="trellis")
    resp = send(action)
    # the token WAS used to authenticate
    assert "SUPER-SECRET-abc123" in captured["auth"]
    # ...but it is nowhere in what the sender hands back
    assert "SUPER-SECRET-abc123" not in json.dumps(resp)


def test_token_never_in_raised_error(monkeypatch):
    """When the transport fails, the raised error carries no token."""
    monkeypatch.setenv("TRELLIS_DISCORD_TOKEN", "SUPER-SECRET-xyz789")
    import urllib.error

    def boom_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    send = urllib_discord_sender(_iso(act=("chan-1",)), urlopen=boom_urlopen)
    action = StagedAction("discord_post", "chan-1", "hi", created_by="trellis")
    with pytest.raises(Exception) as ei:
        send(action)
    assert "SUPER-SECRET-xyz789" not in str(ei.value)


def test_unarmed_executor_still_refuses():
    """No send_fn at all: the executor refuses (ExecutorNotArmed), never a phantom
    success — unchanged by the new transport."""
    ex = DiscordExecutor(_iso(act=("chan-1",)), send_fn=None)
    action = StagedAction("discord_post", "chan-1", "hi", created_by="trellis")
    with pytest.raises(ExecutorNotArmed):
        ex.execute(action)


# ----- `trellis discord` wiring ----------------------------------------------


def _clear_discord_env(monkeypatch):
    for k in ("TRELLIS_DISCORD_TOKEN", "TRELLIS_APPROVER_DISCORD_ID",
              "TRELLIS_ACT_SURFACES", "TRELLIS_READ_SURFACES", "TRELLIS_LEDGER"):
        monkeypatch.delenv(k, raising=False)


def test_cmd_discord_refuses_loud_when_unarmed(monkeypatch, tmp_path):
    """No token / owner / act allowlist → refuse loud (exit 1), construct nothing,
    send nothing."""
    monkeypatch.chdir(tmp_path)
    _clear_discord_env(monkeypatch)
    rc = cli.cmd_discord(argparse.Namespace())
    assert rc == 1


def test_cmd_discord_refuses_when_act_allowlist_empty(monkeypatch, tmp_path):
    """Token + owner set but no ACT allowlist → still refuse (nowhere to send)."""
    monkeypatch.chdir(tmp_path)
    _clear_discord_env(monkeypatch)
    monkeypatch.setenv("TRELLIS_DISCORD_TOKEN", "tok")
    monkeypatch.setenv("TRELLIS_APPROVER_DISCORD_ID", "999")
    monkeypatch.setenv("TRELLIS_LEDGER", str(tmp_path / "l.jsonl"))
    rc = cli.cmd_discord(argparse.Namespace())
    assert rc == 1


def test_cmd_discord_configured_wires_hardened_executor(monkeypatch, tmp_path):
    """Fully configured: construct the gateway behind a DiscordExecutor (the
    defense-in-depth ledger re-check present) and stop at the live seam — no network,
    no send. The live connection is injected here so no socket opens."""
    monkeypatch.chdir(tmp_path)
    _clear_discord_env(monkeypatch)
    monkeypatch.setenv("TRELLIS_DISCORD_TOKEN", "tok")
    monkeypatch.setenv("TRELLIS_APPROVER_DISCORD_ID", "999")
    monkeypatch.setenv("TRELLIS_ACT_SURFACES", "chan-1")
    monkeypatch.setenv("TRELLIS_LEDGER", str(tmp_path / "l.jsonl"))

    captured = {}

    class FakeConn:
        def __init__(self, gateway, bot_token=None):
            captured["gateway"] = gateway
            captured["token"] = bot_token

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr("trellis.discord_gateway.DiscordGatewayConnection", FakeConn)
    rc = cli.cmd_discord(argparse.Namespace())
    assert rc == 0
    assert captured["ran"] is True
    assert captured["token"] == "tok"
    gw = captured["gateway"]
    assert gw.approver_discord_id == "999"
    # the executor bound into the gateway is the hardened DiscordExecutor, holding
    # the ledger (the defense-in-depth approval re-check the task requires active)
    bound = getattr(gw.executor, "__self__", None)
    assert isinstance(bound, DiscordExecutor)
    assert bound.ledger is not None


# ----- `trellis run` / `trellis discord` client construction -----------------


def test_discord_client_from_env_none_when_unconfigured(monkeypatch):
    """No token → no client → the runner's poll step stays inert."""
    monkeypatch.delenv("TRELLIS_DISCORD_TOKEN", raising=False)
    assert cli._discord_client_from_env() is None


def test_discord_client_from_env_constructs_when_configured(monkeypatch):
    """Token set → a DiscordClient is constructed from env (no network on
    construction — the token is only fetched at request time)."""
    monkeypatch.setenv("TRELLIS_DISCORD_TOKEN", "tok")
    monkeypatch.setenv("TRELLIS_ACT_SURFACES", "chan-1")
    client = cli._discord_client_from_env()
    from trellis.discord_api import DiscordClient
    assert isinstance(client, DiscordClient)
