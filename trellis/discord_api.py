"""discord_api.py — the LIVE Discord REST client, stdlib-urllib only. (D11, D30, D37)

This is the last mile: the polling transport that lets trellis's already-built,
already-tested safety machinery talk to a real Discord server. The core stays
STDLIB-ONLY (D11) and the runner is TICK-based (D37), so the live integration is
POLLING over the Discord REST API — each tick asks "any new messages? any new
reactions?" — NOT a third-party websocket gateway library. Every HTTP call goes
through `urllib.request` with an INJECTABLE `urlopen`, so the whole client is
exercised in tests without a single byte leaving the machine.

What this module does NOT do (on purpose):

  * It never decides what trellis may read or send. That is isolation.py's
    allowlist (D30). This client is a dumb pipe; the runner scopes what it polls
    and the executor/gateway guard every send. A DiscordClient can fetch any
    channel id it is handed — the SAFETY is that callers only ever hand it
    allowlisted ids.

  * It never auto-posts on trellis's behalf as an "action". `post_message` is the
    raw transport the approved-and-fired Outbox path calls; approval lives
    upstream (D38). It is also used for the two staged-safe outbounds that are not
    "actions": opening a DM channel and posting a proposal for the owner to react
    on.

The bot credential (D30): read ON DEMAND from its env var via
`isolation.AgentIdentity.credential()`, sent as `Authorization: Bot <token>`,
and NEVER logged, NEVER stored on the object, NEVER placed in an exception
string. A malformed or rate-limited response normalizes to a TYPED error
(`DiscordAPIError` / `DiscordRateLimited`) carrying the retry delay — never a raw
traceback, never the token.

Rate limits (D26-adjacent honesty): an HTTP 429 becomes `DiscordRateLimited` with
the server's `retry_after`; the client does NOT busy-loop or sleep — it hands the
delay back to the tick runner, which decides when to poll again.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional, Union

from .clock import parse_iso
from .ingest import DiscordMessage
from .isolation import AgentIdentity

API_BASE = "https://discord.com/api/v10"
_USER_AGENT = "trellis (https://github.com/, 1.0)"


# ----- typed errors (never a raw traceback, never the token) ----------------


class DiscordAPIError(Exception):
    """A Discord API call failed (HTTP error, network error, or malformed body).
    Carries a safe, human-readable message and the HTTP status when known. The bot
    token is NEVER included."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class DiscordRateLimited(DiscordAPIError):
    """The server returned HTTP 429. `retry_after` is the delay (seconds) the tick
    runner should wait before polling again — the client itself does NOT sleep or
    busy-loop, it surfaces the signal and returns control."""

    def __init__(self, retry_after: float, is_global: bool = False):
        super().__init__(
            f"rate limited by Discord; retry after {retry_after:g}s"
            + (" (global)" if is_global else ""),
            status=429)
        self.retry_after = float(retry_after)
        self.is_global = bool(is_global)


# ----- the result of a message poll -----------------------------------------


@dataclass(frozen=True)
class MessageBatch:
    """One poll's worth of messages, OLDEST-FIRST (ingest order), plus the CURSOR
    to hand to the next `fetch_messages(after=...)`. The cursor is the newest
    message id seen this batch; on an empty batch it is the caller's prior cursor,
    so a quiet channel does not reset the poll position."""
    messages: List[DiscordMessage]
    cursor: Optional[str]


# ----- the client -----------------------------------------------------------


IdentityOrEnv = Union[AgentIdentity, str, None]


class DiscordClient:
    """A minimal, stdlib-only Discord REST client.

    `identity_or_token_env` is either an `AgentIdentity` (whose `token_env` names
    the credential var) or a plain env-var-name string, or None for the default
    trellis identity (`TRELLIS_DISCORD_TOKEN`). The token is fetched on demand for
    every request and never held on the object.

    `urlopen` is injected so tests never hit the network; production leaves it None
    and uses `urllib.request.urlopen`. `api_base` defaults to the real Discord v10
    API and is overridable for tests.
    """

    def __init__(self, identity_or_token_env: IdentityOrEnv = None,
                 urlopen: Optional[Callable] = None,
                 api_base: str = API_BASE, timeout: float = 15.0):
        if isinstance(identity_or_token_env, AgentIdentity):
            self._identity = identity_or_token_env
        elif isinstance(identity_or_token_env, str) and identity_or_token_env.strip():
            self._identity = AgentIdentity(token_env=identity_or_token_env.strip())
        else:
            self._identity = AgentIdentity()
        self._urlopen = urlopen or urllib.request.urlopen
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self._cached_user_id: Optional[str] = None

    # ----- the one HTTP chokepoint ------------------------------------------

    def _request(self, method: str, path: str,
                 query: Optional[dict] = None, body: Optional[dict] = None):
        """Perform one authenticated request and return the parsed JSON (dict or
        list), or {} for an empty body. All failure modes normalize to a typed
        error; the token is fetched here and never escapes into any message."""
        url = self.api_base + path
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        token = self._identity.credential()   # fails loud (CredentialMissing) if unset
        headers = {"Authorization": f"Bot {token}", "User-Agent": _USER_AGENT}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            self._raise_for_http(e)          # always raises
        except urllib.error.URLError as e:
            # network failure — reason is a safe string, never the token
            raise DiscordAPIError(f"network error contacting Discord: {e.reason}") from None
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            raise DiscordAPIError("malformed JSON in Discord response") from None

    @staticmethod
    def _raise_for_http(e: "urllib.error.HTTPError"):
        """Normalize an HTTPError into a typed error. Reads the body defensively;
        a Discord error body carries {message, code, retry_after, global} and never
        echoes the caller's token, so it is safe to surface the `message`."""
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        payload = {}
        if body:
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {}
        if e.code == 429:
            retry = payload.get("retry_after")
            if retry is None:
                hdr = None
                try:
                    hdr = e.headers.get("Retry-After") if e.headers else None
                except Exception:
                    hdr = None
                retry = float(hdr) if hdr else 0.0
            raise DiscordRateLimited(retry_after=float(retry),
                                     is_global=bool(payload.get("global"))) from None
        msg = ""
        if isinstance(payload, dict):
            msg = str(payload.get("message", "") or "")
        raise DiscordAPIError(
            f"Discord API error {e.code}" + (f": {msg}" if msg else ""),
            status=e.code) from None

    # ----- reads -------------------------------------------------------------

    def fetch_messages(self, channel_id: str, after: Optional[str] = None,
                       limit: int = 50, *, before: Optional[str] = None,
                       channel_name: str = "",
                       is_thread: bool = False, parent_channel: Optional[str] = None,
                       is_dm: bool = False) -> MessageBatch:
        """GET /channels/{id}/messages, mapping each to a `DiscordMessage`.

        Discord returns messages NEWEST-FIRST; this returns them OLDEST-FIRST (the
        order the ledger ingests) with a `cursor` = the newest id seen, so the next
        tick polls `after=cursor` and never re-reads.

        The SURFACE descriptors are supplied by the caller (the runner knows what it
        is polling — a channel, a thread, or a DM), because a bare message object
        cannot tell a thread from its parent:
          * `is_thread=True`  → the polled id is a thread; each message carries
            `thread_id=channel_id` and `channel=parent_channel` (the parent is what
            the D32 allowlist keys on, so pass it).
          * `is_dm=True`      → each message is marked `is_dm` (Surface.DM).
          * neither           → a plain channel message.
        """
        raw = self._request("GET", f"/channels/{channel_id}/messages",
                            query=self._message_query(after, limit, before))
        rows = raw if isinstance(raw, list) else []
        thread_id = channel_id if is_thread else None
        channel = (parent_channel or channel_id) if is_thread else channel_id
        messages = [self._to_discord_message(r, channel=channel,
                                             channel_name=channel_name,
                                             thread_id=thread_id, is_dm=is_dm)
                    for r in rows]
        # oldest-first by snowflake (ids are monotonically increasing over time)
        messages.sort(key=lambda m: _snowflake_key(m.message_id))
        cursor = messages[-1].message_id if messages else after
        return MessageBatch(messages=messages, cursor=cursor)

    @staticmethod
    def _message_query(after: Optional[str], limit: int,
                       before: Optional[str] = None) -> dict:
        """`after` walks history forward; `before` walks it BACKWARD (the D52
        recency-first descent). Never both — the caller picks a direction."""
        q: dict = {"limit": max(1, min(int(limit), 100))}
        if after:
            q["after"] = after
        elif before:
            q["before"] = before
        return q

    @staticmethod
    def _to_discord_message(row: dict, *, channel: str, channel_name: str,
                            thread_id: Optional[str], is_dm: bool) -> DiscordMessage:
        author_obj = row.get("author") or {}
        author_id = str(author_obj.get("id", "") or "")
        # attribution: prefer the display (global_name), fall back to username, and
        # never a blank — the ledger refuses a blank author downstream, but keep the
        # snowflake as a last resort so nothing is silently dropped here.
        author = (str(author_obj.get("global_name") or "").strip()
                  or str(author_obj.get("username") or "").strip()
                  or author_id)
        posted_at = parse_iso(str(row.get("timestamp")))
        return DiscordMessage(
            author=author, content=str(row.get("content", "") or ""),
            posted_at=posted_at, channel=channel, channel_name=channel_name,
            thread_id=thread_id, message_id=str(row.get("id", "") or ""),
            is_dm=is_dm, author_id=author_id)

    def list_guild_channels(self, guild_id: str) -> List[dict]:
        """GET /guilds/{id}/channels → [{'id','name','type'}, …]. RAW transport:
        it returns what the API lists — including channels the bot cannot open.
        What trellis may actually READ stays upstream (isolation + the D40
        discovery probe in backfill.discover_guild_read_surfaces)."""
        raw = self._request("GET", f"/guilds/{guild_id}/channels")
        rows = raw if isinstance(raw, list) else []
        out: List[dict] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            try:
                ctype = int(r.get("type", -1))
            except (TypeError, ValueError):
                ctype = -1
            cid = str(r.get("id", "") or "")
            if cid:
                out.append({"id": cid, "name": str(r.get("name", "") or ""),
                            "type": ctype})
        return out

    def fetch_reactions(self, channel_id: str, message_id: str,
                        emoji: str, limit: int = 100) -> List[str]:
        """GET the users who reacted to a message with `emoji`; return their
        snowflake ids (the approval poll: the owner's id among them is the yes).
        The emoji is URL-encoded into the path (a unicode glyph or a `name:id`
        custom emoji)."""
        enc = urllib.parse.quote(emoji, safe="")
        raw = self._request(
            "GET", f"/channels/{channel_id}/messages/{message_id}/reactions/{enc}",
            query={"limit": max(1, min(int(limit), 100))})
        rows = raw if isinstance(raw, list) else []
        return [str(u.get("id", "") or "") for u in rows if u.get("id")]

    def current_user_id(self) -> str:
        """GET /users/@me → the BOT's own snowflake, cached. Lets the runner ignore
        the bot's own messages and reactions (so it never approves itself or
        re-ingests what it just posted)."""
        if self._cached_user_id is None:
            raw = self._request("GET", "/users/@me")
            self._cached_user_id = str((raw or {}).get("id", "") or "")
        return self._cached_user_id

    # ----- writes (raw transport; approval/allowlisting live upstream) -------

    def post_message(self, channel_id: str, content: str,
                     nonce: Optional[str] = None) -> dict:
        """POST /channels/{id}/messages with an idempotency `nonce`, returning the
        created message dict (with its `id`). trellis guarantees fire-at-most-once
        upstream; the nonce lets a remote that dedups turn that into exactly-once
        (D26). A nonce is auto-generated when not supplied.

        This is the RAW transport. It carries no approval authority of its own — the
        approved-and-fired Outbox path (D38) and the D30 allowlist gate sit above it;
        it is also the transport for the two staged-safe outbounds (`open_dm`, and a
        proposal post) that are not themselves 'actions'."""
        payload = {"content": content, "nonce": nonce or uuid.uuid4().hex}
        raw = self._request("POST", f"/channels/{channel_id}/messages", body=payload)
        return raw if isinstance(raw, dict) else {}

    def open_dm(self, user_id: str) -> str:
        """POST /users/@me/channels → open (or get) a DM channel with `user_id` and
        return its channel id, so a Surface.DM proposal can be delivered to the
        owner. Idempotent server-side: repeated calls return the same channel."""
        raw = self._request("POST", "/users/@me/channels",
                            body={"recipient_id": user_id})
        cid = str((raw or {}).get("id", "") or "")
        if not cid:
            raise DiscordAPIError("open_dm: Discord returned no channel id")
        return cid


def _snowflake_key(message_id: str):
    """Sort key that orders by the integer snowflake when possible (true creation
    order), falling back to the raw string so a non-numeric id never crashes the
    sort."""
    try:
        return (0, int(message_id))
    except (TypeError, ValueError):
        return (1, str(message_id))
