"""test_discord_poll.py — the stdlib POLL that wires the live Discord REST client
into the tick loop (D37 + D38 + D30 + D11).

The last mile: each tick polls the allowlisted surfaces for new messages and polls
staged proposals for the owner's approval reaction. NOTHING here hits the network —
a MOCK DiscordClient stands in for the transport, so every safety property is
exercised offline.

The properties these tests pin (do NOT weaken):
  * a tick ingests new allowlisted messages ONCE — a re-tick is a no-op via the
    persisted cursor AND the idempotent bridge;
  * a NON-allowlisted channel is never polled and never ingested;
  * the resume cursor persists on the ledger and a FRESH runner resumes from it;
  * an OWNER ✅ on a staged proposal approves AND fires through the hardened Outbox;
  * a NON-owner ✅ does nothing (no approve, no fire);
  * an owner ❌ denies; a double-poll never double-fires.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trellis.discord_api import DiscordRateLimited, MessageBatch
from trellis.discord_gateway import (ApprovalGateway, client_proposal_sender,
                                     client_send_executor)
from trellis.ingest import DiscordMessage
from trellis.isolation import (AgentIdentity, Isolation, SurfaceAllowlist)
from trellis.ledger import Ledger
from trellis.registry import IdentityRegistry
from trellis.runner import DiscordPoll, PollSurface, Runner
from trellis.stage import ActionStatus, Outbox, StagedAction

OWNER = "111111111111111111"          # the owner's Discord snowflake
OTHER = "999999999999999999"          # some other member
BOT = "bot-self-000"                  # the trellis bot's own snowflake
READ_CHAN = "chan-read"               # a READ-allowlisted channel
OTHER_CHAN = "chan-not-mine"          # NOT on any allowlist
ACT_CHAN = "chan-act"                 # an ACT-allowlisted channel
DM_SURFACE = "owner-dm"               # the proposal surface (act-allowlisted)
AGENT = "trellis-witness"


def _iso(read=(READ_CHAN,), act=(ACT_CHAN, DM_SURFACE)):
    return Isolation(identity=AgentIdentity(name="trellis"),
                     allow=SurfaceAllowlist(read=frozenset(read), act=frozenset(act)))


_TS = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


class MockDiscordClient:
    """A network-free stand-in for trellis.discord_api.DiscordClient, honouring the
    exact surface: fetch_messages(after=...) filters by snowflake so cursor resume
    is real; fetch_reactions/post_message/open_dm/current_user_id are programmable.
    Every call is recorded so a test can assert what was (and was not) polled."""

    def __init__(self):
        # channel_id -> list of (message_id, author, author_id, content)
        self.messages: dict[str, list] = {}
        # (channel_id, message_id, emoji) -> [reactor ids]
        self.reactions: dict[tuple, list] = {}
        self.bot_id = BOT
        self.fetched_channels: list = []
        self.posts: list = []           # (channel_id, content, nonce)
        self._next_post = 1

    # ----- reads -----
    def fetch_messages(self, channel_id, after=None, limit=50, *, channel_name="",
                       is_thread=False, parent_channel=None, is_dm=False):
        self.fetched_channels.append(channel_id)
        rows = self.messages.get(channel_id, [])
        thread_id = channel_id if is_thread else None
        channel = (parent_channel or channel_id) if is_thread else channel_id
        out = []
        for mid, author, author_id, content in rows:
            if after is not None and int(mid) <= int(after):
                continue
            out.append(DiscordMessage(
                author=author, content=content, posted_at=_TS, channel=channel,
                channel_name=channel_name, thread_id=thread_id, message_id=str(mid),
                is_dm=is_dm, author_id=author_id))
        out.sort(key=lambda m: int(m.message_id))
        cursor = out[-1].message_id if out else after
        return MessageBatch(messages=out, cursor=cursor)

    def fetch_reactions(self, channel_id, message_id, emoji, limit=100):
        return list(self.reactions.get((channel_id, str(message_id), emoji), []))

    def current_user_id(self):
        return self.bot_id

    # ----- writes -----
    def post_message(self, channel_id, content, nonce=None):
        mid = f"posted-{self._next_post}"
        self._next_post += 1
        self.posts.append((channel_id, content, nonce))
        return {"id": mid, "content": content}

    def open_dm(self, user_id):
        return DM_SURFACE


def _msg(mid, content, author="brett", author_id="u-brett"):
    return (str(mid), author, author_id, content)


# --------------------------------------------------------------------------- #
# 1. a tick ingests new allowlisted messages ONCE — re-tick is a no-op         #
# --------------------------------------------------------------------------- #

def test_tick_ingests_allowlisted_messages_once(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso()
    client = MockDiscordClient()
    client.messages[READ_CHAN] = [_msg(100, "hello"), _msg(200, "world")]
    poll = DiscordPoll(client, iso, IdentityRegistry(ledger), ledger, ground)
    r = Runner(ledger, ground, discord=poll)

    report = r.tick(handlers={})
    assert report["poll"]["admitted"] == 2
    ingested = [e for e in ledger.entries() if e.kind == "discord_message"]
    assert {e.body["content"] for e in ingested} == {"hello", "world"}

    # a second tick re-polls; cursor + bridge idempotency make it a no-op
    report2 = r.tick(handlers={})
    assert report2["poll"]["admitted"] == 0
    ingested2 = [e for e in ledger.entries() if e.kind == "discord_message"]
    assert len(ingested2) == 2                      # nothing double-ingested


def test_retick_is_noop_even_if_client_ignores_after(tmp_path, ground):
    # belt-and-suspenders: even a client that re-serves the SAME messages every poll
    # ingests each exactly once, because the bridge is message-id idempotent.
    class DumbClient(MockDiscordClient):
        def fetch_messages(self, channel_id, after=None, **kw):
            return super().fetch_messages(channel_id, after=None, **kw)  # ignore cursor

    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso()
    client = DumbClient()
    client.messages[READ_CHAN] = [_msg(100, "hello")]
    poll = DiscordPoll(client, iso, IdentityRegistry(ledger), ledger, ground)
    r = Runner(ledger, ground, discord=poll)
    r.tick(handlers={})
    r.tick(handlers={})
    assert len([e for e in ledger.entries() if e.kind == "discord_message"]) == 1


# --------------------------------------------------------------------------- #
# 2. a non-allowlisted channel is never polled or ingested                     #
# --------------------------------------------------------------------------- #

def test_non_allowlisted_channel_is_never_polled_or_ingested(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso(read=(READ_CHAN,))
    client = MockDiscordClient()
    client.messages[READ_CHAN] = [_msg(100, "mine")]
    client.messages[OTHER_CHAN] = [_msg(500, "not mine")]
    # explicitly list BOTH surfaces — the non-allowlisted one must be filtered out
    surfaces = [PollSurface(READ_CHAN), PollSurface(OTHER_CHAN)]
    poll = DiscordPoll(client, iso, IdentityRegistry(ledger), ledger, ground,
                       surfaces=surfaces)
    Runner(ledger, ground, discord=poll).tick(handlers={})

    assert client.fetched_channels == [READ_CHAN]           # OTHER_CHAN never fetched
    contents = {e.body["content"] for e in ledger.entries()
                if e.kind == "discord_message"}
    assert contents == {"mine"}                             # "not mine" never ingested


# --------------------------------------------------------------------------- #
# 3. the cursor persists on the ledger and a FRESH runner resumes              #
# --------------------------------------------------------------------------- #

def test_cursor_persists_and_a_fresh_runner_resumes(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    iso = _iso()
    client = MockDiscordClient()
    client.messages[READ_CHAN] = [_msg(100, "one"), _msg(200, "two")]

    ledger1 = Ledger(path, ground)
    poll1 = DiscordPoll(client, iso, IdentityRegistry(ledger1), ledger1, ground)
    Runner(ledger1, ground, discord=poll1).tick(handlers={})
    cursors = [e.body["cursor"] for e in ledger1.entries()
               if e.kind == "discord_poll_cursor"]
    assert cursors[-1] == "200"                             # newest id persisted

    # a new message arrives; DROP the process and start a FRESH runner over the ledger
    client.messages[READ_CHAN].append(_msg(300, "three"))
    ledger2 = Ledger(path, ground)
    poll2 = DiscordPoll(client, iso, IdentityRegistry(ledger2), ledger2, ground)
    report = Runner(ledger2, ground, discord=poll2).tick(handlers={})

    assert report["poll"]["admitted"] == 1                 # only the NEW message
    # the fresh runner polled after=200, so it fetched exactly the tail
    contents = [e.body["content"] for e in ledger2.entries()
                if e.kind == "discord_message"]
    assert contents == ["one", "two", "three"]


# --------------------------------------------------------------------------- #
# 4. an OWNER ✅ on a staged proposal approves AND fires — through the Outbox    #
# --------------------------------------------------------------------------- #

def _gateway_and_poll(ledger, ground, iso, client, owner=OWNER):
    outbox = Outbox(ledger, ground)
    registry = IdentityRegistry(ledger)
    gw = ApprovalGateway(
        ledger=ledger, iso=iso, registry=registry, outbox=outbox,
        executor=client_send_executor(iso, client),
        approver_discord_id=owner,
        proposal_surface=DM_SURFACE, proposal_sender=client_proposal_sender(client))
    poll = DiscordPoll(client, iso, registry, ledger, ground, gateway=gw)
    return outbox, gw, poll


def test_owner_reaction_polled_approves_and_fires(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso()
    client = MockDiscordClient()
    outbox, gw, poll = _gateway_and_poll(ledger, ground, iso, client)
    aid = outbox.stage(StagedAction(kind="discord_post", target=ACT_CHAN,
                                    content="July framing adopted.", created_by=AGENT))
    ref = gw.post_proposal(outbox.get(aid))                # posts to DM_SURFACE
    # the owner reacts ✅ on the proposal message
    client.reactions[(DM_SURFACE, ref, "✅")] = [OWNER]

    report = Runner(ledger, ground, discord=poll).tick(handlers={})

    assert outbox.get(aid).status == ActionStatus.FIRED
    assert any(a["status"] == "approved_and_fired" for a in report["poll"]["approvals"])
    # the action content was actually POSTed to the ACT channel, exactly once
    act_posts = [p for p in client.posts if p[0] == ACT_CHAN]
    assert act_posts == [(ACT_CHAN, "July framing adopted.", outbox.get(aid).idempotency_key)]


def test_double_poll_does_not_double_fire(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso()
    client = MockDiscordClient()
    outbox, gw, poll = _gateway_and_poll(ledger, ground, iso, client)
    aid = outbox.stage(StagedAction(kind="discord_post", target=ACT_CHAN,
                                    content="x", created_by=AGENT))
    ref = gw.post_proposal(outbox.get(aid))
    client.reactions[(DM_SURFACE, ref, "✅")] = [OWNER]
    r = Runner(ledger, ground, discord=poll)
    r.tick(handlers={})
    r.tick(handlers={})                                    # poll again
    assert outbox.get(aid).status == ActionStatus.FIRED
    assert len([p for p in client.posts if p[0] == ACT_CHAN]) == 1   # fired once


# --------------------------------------------------------------------------- #
# 5. a NON-owner ✅ does nothing                                                #
# --------------------------------------------------------------------------- #

def test_non_owner_reaction_polled_does_nothing(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso()
    client = MockDiscordClient()
    outbox, gw, poll = _gateway_and_poll(ledger, ground, iso, client)
    aid = outbox.stage(StagedAction(kind="discord_post", target=ACT_CHAN,
                                    content="x", created_by=AGENT))
    ref = gw.post_proposal(outbox.get(aid))
    client.reactions[(DM_SURFACE, ref, "✅")] = [OTHER]     # a non-owner reacted

    Runner(ledger, ground, discord=poll).tick(handlers={})

    assert outbox.get(aid).status == ActionStatus.STAGED   # still awaiting the owner
    assert [p for p in client.posts if p[0] == ACT_CHAN] == []


def test_owner_deny_polled_denies(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso()
    client = MockDiscordClient()
    outbox, gw, poll = _gateway_and_poll(ledger, ground, iso, client)
    aid = outbox.stage(StagedAction(kind="discord_post", target=ACT_CHAN,
                                    content="x", created_by=AGENT))
    ref = gw.post_proposal(outbox.get(aid))
    client.reactions[(DM_SURFACE, ref, "❌")] = [OWNER]

    Runner(ledger, ground, discord=poll).tick(handlers={})

    assert outbox.get(aid).status == ActionStatus.DENIED
    assert [p for p in client.posts if p[0] == ACT_CHAN] == []


# --------------------------------------------------------------------------- #
# 6. the proposal-post record is DURABLE — a fresh gateway resumes polling      #
# --------------------------------------------------------------------------- #

def test_proposal_post_record_survives_a_restart(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    iso = _iso()
    client = MockDiscordClient()

    ledger1 = Ledger(path, ground)
    outbox1, gw1, _ = _gateway_and_poll(ledger1, ground, iso, client)
    aid = outbox1.stage(StagedAction(kind="discord_post", target=ACT_CHAN,
                                     content="resume me", created_by=AGENT))
    ref = gw1.post_proposal(outbox1.get(aid))

    # DROP the process: a fresh gateway rebuilds the proposal map from the ledger
    ledger2 = Ledger(path, ground)
    outbox2, gw2, poll2 = _gateway_and_poll(ledger2, ground, iso, client)
    assert (aid, DM_SURFACE, ref) in gw2.staged_proposal_posts()
    client.reactions[(DM_SURFACE, ref, "✅")] = [OWNER]
    Runner(ledger2, ground, discord=poll2).tick(handlers={})
    assert outbox2.get(aid).status == ActionStatus.FIRED


# --------------------------------------------------------------------------- #
# 7. resilience: a rate-limited surface does not kill the tick                  #
# --------------------------------------------------------------------------- #

def test_rate_limited_surface_is_recorded_and_tick_survives(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso(read=(READ_CHAN, "chan-b"))

    class RateLimitedOnB(MockDiscordClient):
        def fetch_messages(self, channel_id, after=None, **kw):
            if channel_id == "chan-b":
                raise DiscordRateLimited(retry_after=1.5)
            return super().fetch_messages(channel_id, after=after, **kw)

    client = RateLimitedOnB()
    client.messages[READ_CHAN] = [_msg(100, "still ingested")]
    poll = DiscordPoll(client, iso, IdentityRegistry(ledger), ledger, ground)
    report = Runner(ledger, ground, discord=poll).tick(handlers={})

    # the good channel still ingested; the rate limit is recorded, not raised
    assert report["poll"]["admitted"] == 1
    assert any(e.get("retry_after") == 1.5 for e in report["poll"]["errors"])


# --------------------------------------------------------------------------- #
# 8. the bot never re-ingests its OWN messages                                  #
# --------------------------------------------------------------------------- #

def test_bot_own_messages_are_not_reingested(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso()
    client = MockDiscordClient()
    client.messages[READ_CHAN] = [
        _msg(100, "from a human", author="brett", author_id="u-brett"),
        _msg(200, "from the bot", author="trellisbot", author_id=BOT),
    ]
    poll = DiscordPoll(client, iso, IdentityRegistry(ledger), ledger, ground)
    report = Runner(ledger, ground, discord=poll).tick(handlers={})
    assert report["poll"]["admitted"] == 1                 # only the human message
    contents = {e.body["content"] for e in ledger.entries()
                if e.kind == "discord_message"}
    assert contents == {"from a human"}


# --------------------------------------------------------------------------- #
# 9. an unconfigured tick is unchanged (the 541-test guarantee)                 #
# --------------------------------------------------------------------------- #

def test_tick_without_discord_has_no_poll_key(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    report = Runner(ledger, ground).tick(handlers={})
    assert "poll" not in report                            # nothing added when unconfigured
