"""test_discord_api.py — the stdlib-urllib Discord REST client (live plumbing).

Every test injects a FAKE urlopen; NOTHING here touches the network. The client
is exercised for: message mapping onto trellis.ingest.DiscordMessage (snowflake in
author_id, the right surface for dm/thread/channel), reaction reads, the nonce'd
post, DM channel opening, the bot's own id, rate-limit typing (HTTP 429 →
DiscordRateLimited with the retry delay), and the invariant that the bot token
NEVER appears in any exception string.
"""

import io
import json
import urllib.error

import pytest

from trellis.discord_api import (DiscordClient, DiscordAPIError,
                                 DiscordRateLimited, MessageBatch)
from trellis.ingest import DiscordMessage
from trellis.isolation import AgentIdentity, CredentialMissing
from trellis.surfaces import Surface


TOKEN = "super-secret-bot-token-DO-NOT-LOG-42"


# --------------------------------------------------------------------------- #
# a fake urlopen: records the last Request, returns canned JSON per URL/method  #
# --------------------------------------------------------------------------- #

class _Resp:
    def __init__(self, body, status=200):
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


class FakeHTTP:
    """A programmable stand-in for urllib.request.urlopen. `routes` maps a
    (method, path-prefix) to a JSON-able body; the last Request is captured so a
    test can assert on the headers/body/nonce actually sent."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.last_request = None
        self.requests = []

    def __call__(self, req, timeout=None):
        self.last_request = req
        self.requests.append(req)
        method = req.get_method()
        url = req.full_url
        for (m, needle), body in self.routes.items():
            if m == method and needle in url:
                if isinstance(body, Exception):
                    raise body
                payload = body(req) if callable(body) else body
                return _Resp(json.dumps(payload))
        raise AssertionError(f"no fake route for {method} {url}")


def _user(uid, username, global_name=None):
    return {"id": uid, "username": username, "global_name": global_name}


def _msg(mid, uid, username, content, ts="2026-07-22T12:00:00.000000+00:00"):
    return {"id": mid, "author": _user(uid, username), "content": content,
            "timestamp": ts}


def _client(routes, token=TOKEN, monkeypatch=None, api_base="https://discord.test/api/v10"):
    if monkeypatch is not None:
        monkeypatch.setenv("TRELLIS_DISCORD_TOKEN", token)
    fake = FakeHTTP(routes)
    return DiscordClient(urlopen=fake, api_base=api_base), fake


# --------------------------------------------------------------------------- #
# fetch_messages → DiscordMessage mapping                                       #
# --------------------------------------------------------------------------- #

def test_fetch_messages_maps_snowflake_into_author_id(monkeypatch):
    monkeypatch.setenv("TRELLIS_DISCORD_TOKEN", TOKEN)
    # Discord returns newest-first; the client must return oldest-first.
    routes = {("GET", "/channels/c-100/messages"): [
        _msg("300", "u-brett", "brett", "later", "2026-07-22T13:00:00+00:00"),
        _msg("100", "u-brett", "brett", "earlier", "2026-07-22T11:00:00+00:00"),
    ]}
    client, _ = _client(routes, monkeypatch=monkeypatch)
    batch = client.fetch_messages("c-100", channel_name="chiefs")

    assert isinstance(batch, MessageBatch)
    assert [m.content for m in batch.messages] == ["earlier", "later"]  # oldest-first
    m0 = batch.messages[0]
    assert isinstance(m0, DiscordMessage)
    assert m0.author == "brett"
    assert m0.author_id == "u-brett"        # the snowflake rode into author_id
    assert m0.message_id == "100"
    assert m0.channel == "c-100"
    assert m0.channel_name == "chiefs"
    assert m0.thread_id is None and m0.is_dm is False
    assert batch.cursor == "300"            # new cursor = newest id seen


def test_fetch_messages_prefers_global_name_for_attribution(monkeypatch):
    routes = {("GET", "/channels/c-1/messages"): [
        _msg("1", "u-1", "brett_raw", "hi", "2026-07-22T12:00:00+00:00"),
    ]}
    # inject a global_name
    routes[("GET", "/channels/c-1/messages")][0]["author"]["global_name"] = "Brett H"
    client, _ = _client(routes, monkeypatch=monkeypatch)
    [m] = client.fetch_messages("c-1").messages
    assert m.author == "Brett H"


def test_thread_message_carries_thread_id_and_parent_channel(monkeypatch):
    routes = {("GET", "/channels/t-999/messages"): [
        _msg("5", "u-sarah", "sarah", "in a thread", "2026-07-22T12:00:00+00:00"),
    ]}
    client, _ = _client(routes, monkeypatch=monkeypatch)
    [m] = client.fetch_messages("t-999", is_thread=True,
                                parent_channel="c-parent").messages
    assert m.thread_id == "t-999"
    assert m.channel == "c-parent"          # allowlisting keys on the PARENT (D32)
    # and it individuates as a THREAD surface downstream
    from trellis.ingest import discord_to_rawitem
    assert discord_to_rawitem(m).meta[0] == ("surface", Surface.THREAD.value)


def test_dm_message_is_marked_dm(monkeypatch):
    routes = {("GET", "/channels/dm-7/messages"): [
        _msg("9", "u-owner", "owner", "psst", "2026-07-22T12:00:00+00:00"),
    ]}
    client, _ = _client(routes, monkeypatch=monkeypatch)
    [m] = client.fetch_messages("dm-7", is_dm=True).messages
    assert m.is_dm is True
    from trellis.ingest import discord_to_rawitem
    assert discord_to_rawitem(m).meta[0] == ("surface", Surface.DM.value)


def test_fetch_messages_sends_after_and_limit(monkeypatch):
    routes = {("GET", "/channels/c-1/messages"): []}
    client, fake = _client(routes, monkeypatch=monkeypatch)
    client.fetch_messages("c-1", after="42", limit=25)
    url = fake.last_request.full_url
    assert "after=42" in url and "limit=25" in url


def test_fetch_messages_empty_keeps_prior_cursor(monkeypatch):
    routes = {("GET", "/channels/c-1/messages"): []}
    client, _ = _client(routes, monkeypatch=monkeypatch)
    batch = client.fetch_messages("c-1", after="77")
    assert batch.messages == [] and batch.cursor == "77"


# --------------------------------------------------------------------------- #
# fetch_reactions                                                               #
# --------------------------------------------------------------------------- #

def test_fetch_reactions_returns_reactor_ids(monkeypatch):
    routes = {("GET", "/reactions/"): [
        _user("u-owner", "owner"), _user("u-other", "other"),
    ]}
    client, fake = _client(routes, monkeypatch=monkeypatch)
    ids = client.fetch_reactions("c-1", "m-1", "✅")
    assert ids == ["u-owner", "u-other"]
    # the emoji is URL-encoded into the path, not dropped
    assert "/reactions/" in fake.last_request.full_url


# --------------------------------------------------------------------------- #
# post_message — token header + idempotency nonce                               #
# --------------------------------------------------------------------------- #

def test_post_message_sends_bot_token_and_nonce(monkeypatch):
    routes = {("POST", "/channels/c-1/messages"): {"id": "new-1", "content": "hello"}}
    client, fake = _client(routes, monkeypatch=monkeypatch)
    created = client.post_message("c-1", "hello", nonce="nonce-abc")
    assert created["id"] == "new-1"

    req = fake.last_request
    assert req.get_header("Authorization") == f"Bot {TOKEN}"
    body = json.loads(req.data.decode("utf-8"))
    assert body["content"] == "hello"
    assert body["nonce"] == "nonce-abc"     # idempotency nonce present


def test_post_message_generates_a_nonce_when_absent(monkeypatch):
    routes = {("POST", "/channels/c-1/messages"): {"id": "x"}}
    client, fake = _client(routes, monkeypatch=monkeypatch)
    client.post_message("c-1", "hi")
    body = json.loads(fake.last_request.data.decode("utf-8"))
    assert body.get("nonce")                # a nonce was auto-generated


# --------------------------------------------------------------------------- #
# open_dm + current_user_id                                                      #
# --------------------------------------------------------------------------- #

def test_open_dm_returns_channel_id(monkeypatch):
    routes = {("POST", "/users/@me/channels"): {"id": "dm-channel-55"}}
    client, fake = _client(routes, monkeypatch=monkeypatch)
    cid = client.open_dm("u-owner")
    assert cid == "dm-channel-55"
    body = json.loads(fake.last_request.data.decode("utf-8"))
    assert body["recipient_id"] == "u-owner"


def test_current_user_id(monkeypatch):
    routes = {("GET", "/users/@me"): {"id": "bot-id-1", "username": "trellisbot"}}
    client, _ = _client(routes, monkeypatch=monkeypatch)
    assert client.current_user_id() == "bot-id-1"


# --------------------------------------------------------------------------- #
# rate-limit + error typing                                                     #
# --------------------------------------------------------------------------- #

def _http_error(url, code, body, headers=None):
    return urllib.error.HTTPError(url, code, "err", headers or {},
                                  io.BytesIO(json.dumps(body).encode("utf-8")))


def test_429_surfaces_as_rate_limited_with_retry_delay(monkeypatch):
    err = _http_error("https://discord.test/api/v10/channels/c-1/messages", 429,
                      {"message": "You are being rate limited.", "retry_after": 2.5,
                       "global": False})
    routes = {("GET", "/channels/c-1/messages"): err}
    client, _ = _client(routes, monkeypatch=monkeypatch)
    with pytest.raises(DiscordRateLimited) as ei:
        client.fetch_messages("c-1")
    assert ei.value.retry_after == 2.5


def test_429_reads_retry_after_header_when_no_body(monkeypatch):
    err = _http_error("https://discord.test/api/v10/channels/c-1/messages", 429,
                      {}, headers={"Retry-After": "1.0"})
    routes = {("GET", "/channels/c-1/messages"): err}
    client, _ = _client(routes, monkeypatch=monkeypatch)
    with pytest.raises(DiscordRateLimited) as ei:
        client.fetch_messages("c-1")
    assert ei.value.retry_after == 1.0


def test_http_error_becomes_typed_api_error_not_traceback(monkeypatch):
    err = _http_error("https://discord.test/api/v10/channels/c-1/messages", 403,
                      {"message": "Missing Access", "code": 50001})
    routes = {("GET", "/channels/c-1/messages"): err}
    client, _ = _client(routes, monkeypatch=monkeypatch)
    with pytest.raises(DiscordAPIError) as ei:
        client.fetch_messages("c-1")
    assert "403" in str(ei.value)


def test_malformed_json_becomes_typed_api_error(monkeypatch):
    monkeypatch.setenv("TRELLIS_DISCORD_TOKEN", TOKEN)

    class BadJSON(FakeHTTP):
        def __call__(self, req, timeout=None):
            self.last_request = req
            return _Resp("this-is-not-json{{{")

    client = DiscordClient(urlopen=BadJSON(), api_base="https://discord.test/api/v10")
    with pytest.raises(DiscordAPIError):
        client.fetch_messages("c-1")


def test_network_error_becomes_typed_api_error(monkeypatch):
    routes = {("GET", "/channels/c-1/messages"):
              urllib.error.URLError("connection refused")}
    client, _ = _client(routes, monkeypatch=monkeypatch)
    with pytest.raises(DiscordAPIError):
        client.fetch_messages("c-1")


# --------------------------------------------------------------------------- #
# the token NEVER appears in an exception string                                #
# --------------------------------------------------------------------------- #

def test_token_never_leaks_into_exception_strings(monkeypatch):
    # a 500 whose body echoes text — assert the secret is never in the raised error
    for code in (403, 429, 500):
        err = _http_error("https://discord.test/api/v10/channels/c-1/messages", code,
                          {"message": "boom", "retry_after": 1.0})
        routes = {("GET", "/channels/c-1/messages"): err}
        client, _ = _client(routes, monkeypatch=monkeypatch)
        try:
            client.fetch_messages("c-1")
        except (DiscordAPIError, DiscordRateLimited) as e:
            assert TOKEN not in str(e)
            assert TOKEN not in repr(e)


def test_missing_credential_fails_loud_without_leaking(monkeypatch):
    monkeypatch.delenv("TRELLIS_DISCORD_TOKEN", raising=False)
    client = DiscordClient(urlopen=FakeHTTP({}), api_base="https://discord.test/api/v10")
    with pytest.raises(CredentialMissing):
        client.fetch_messages("c-1")


def test_accepts_an_agent_identity_with_custom_env(monkeypatch):
    monkeypatch.setenv("OTHER_BOT_TOKEN", "other-secret")
    routes = {("GET", "/users/@me"): {"id": "bot-2"}}
    client = DiscordClient(AgentIdentity(name="trellis", token_env="OTHER_BOT_TOKEN"),
                           urlopen=FakeHTTP(routes),
                           api_base="https://discord.test/api/v10")
    assert client.current_user_id() == "bot-2"
