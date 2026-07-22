"""test_backfill.py — the Discord HISTORY catch-up (onboarding, brief §3).

Nothing here touches the network — a paging mock stands in for the transport.
The properties pinned (do NOT weaken):

  * history is ingested OLDEST→NEWEST, all pages, through the idempotent bridge;
  * a re-run after catch-up is a NO-OP (state fold, no re-fetch of history);
  * the cursor is the SAME ledger event the live poll reads, so the handoff to
    the tick poll is structural — the poll resumes exactly where backfill ended;
  * a restart resumes from the persisted cursor with zero duplicates;
  * a rate limit stops ONE surface for the run (with retry_after surfaced) and
    never kills the others;
  * a non-allowlisted surface is never even fetched;
  * the per-run budget bounds a pass and is honestly reported.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trellis.backfill import BACKFILL_STATE_KIND, DiscordBackfill
from trellis.discord_api import DiscordRateLimited, MessageBatch
from trellis.ingest import DiscordMessage
from trellis.isolation import AgentIdentity, Isolation, SurfaceAllowlist
from trellis.ledger import Ledger
from trellis.registry import IdentityRegistry
from trellis.runner import POLL_CURSOR_KIND, DiscordPoll

CHAN = "chan-history"
CHAN2 = "chan-second"
FOREIGN = "chan-not-mine"
BOT = "bot-self-000"

_T0 = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso(read=(CHAN,)):
    return Isolation(identity=AgentIdentity(name="trellis"),
                     allow=SurfaceAllowlist(read=frozenset(read), act=frozenset()))


class PagingClient:
    """Honors `after` + `limit` like the real API, so pagination is real."""

    def __init__(self):
        self.messages: dict = {}       # channel -> [(mid:int, author, author_id, content)]
        self.fetched: list = []        # channel ids fetched (in order)
        self.rate_limited: set = set()  # channels that 429 on fetch
        self.bot_id = BOT

    def add_history(self, channel: str, n: int, author="brett", author_id="u-brett"):
        rows = self.messages.setdefault(channel, [])
        start = len(rows) + 1
        for i in range(start, start + n):
            rows.append((i, author, author_id, f"{channel} msg {i}"))

    def fetch_messages(self, channel_id, after=None, limit=50, *, channel_name="",
                       is_thread=False, parent_channel=None, is_dm=False):
        self.fetched.append(channel_id)
        if channel_id in self.rate_limited:
            raise DiscordRateLimited(retry_after=2.5)
        rows = self.messages.get(channel_id, [])
        floor = int(after) if after is not None else -1
        window = [r for r in rows if r[0] > floor][:limit]
        out = [DiscordMessage(
                   author=a, content=c, posted_at=_T0 + timedelta(minutes=mid),
                   channel=channel_id, channel_name=channel_name,
                   thread_id=None, message_id=str(mid), is_dm=is_dm,
                   author_id=aid)
               for mid, a, aid, c in window]
        cursor = out[-1].message_id if out else after
        return MessageBatch(messages=out, cursor=cursor)

    def current_user_id(self):
        return self.bot_id


def _backfill(ledger, client, iso=None, **kw):
    iso = iso or _iso()
    return DiscordBackfill(client, iso, IdentityRegistry(ledger), ledger, **kw)


def _contents(ledger):
    return [e.body["content"] for e in ledger.entries()
            if e.kind == "discord_message"]


# --------------------------------------------------------------------------- #
# oldest→newest, all pages, idempotent                                         #
# --------------------------------------------------------------------------- #

def test_backfill_walks_all_history_oldest_first(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    client = PagingClient()
    client.add_history(CHAN, 250)
    bf = _backfill(ledger, client, page_limit=100)

    report = bf.run()
    assert report.all_caught_up
    got = _contents(ledger)
    assert len(got) == 250
    assert got[0] == f"{CHAN} msg 1" and got[-1] == f"{CHAN} msg 250"
    # oldest first, in true snowflake order
    assert got == [f"{CHAN} msg {i}" for i in range(1, 251)]


def test_rerun_after_catch_up_is_a_noop(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    client = PagingClient()
    client.add_history(CHAN, 30)
    bf = _backfill(ledger, client)
    bf.run()
    fetches_before = len(client.fetched)

    report2 = bf.run()
    assert report2.surfaces[0].caught_up
    assert len(client.fetched) == fetches_before      # no history re-fetched
    assert len(_contents(ledger)) == 30               # nothing double-ingested


# --------------------------------------------------------------------------- #
# the handoff: one cursor contract with the live poll                          #
# --------------------------------------------------------------------------- #

def test_cursor_hands_off_to_live_poll(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso()
    client = PagingClient()
    client.add_history(CHAN, 40)
    _backfill(ledger, client, iso=iso).run()
    assert len(_contents(ledger)) == 40

    # a new message lands AFTER backfill; the live poll picks up exactly it
    client.add_history(CHAN, 1)
    poll = DiscordPoll(client, iso, IdentityRegistry(ledger), ledger, ground)
    summary = poll.poll()
    assert summary["admitted"] == 1
    assert _contents(ledger)[-1] == f"{CHAN} msg 41"
    assert len(_contents(ledger)) == 41               # zero duplicates


def test_restart_resumes_from_persisted_cursor(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    client = PagingClient()
    client.add_history(CHAN, 120)
    _backfill(ledger, client, page_limit=50, max_messages_per_run=50).run()
    assert len(_contents(ledger)) == 50               # bounded first pass

    # a FRESH instance (a restarted process) folds the cursor off the ledger
    bf2 = _backfill(ledger, client, page_limit=50, max_messages_per_run=500)
    report = bf2.run()
    assert report.all_caught_up
    got = _contents(ledger)
    assert len(got) == 120
    assert got == [f"{CHAN} msg {i}" for i in range(1, 121)]


# --------------------------------------------------------------------------- #
# resilience + isolation                                                       #
# --------------------------------------------------------------------------- #

def test_rate_limit_stops_one_surface_not_the_run(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso(read=(CHAN, CHAN2))
    client = PagingClient()
    client.add_history(CHAN, 10)
    client.add_history(CHAN2, 10)
    client.rate_limited.add(CHAN)

    report = _backfill(ledger, client, iso=iso).run()
    by_chan = {s.channel_id: s for s in report.surfaces}
    assert by_chan[CHAN].error and by_chan[CHAN].retry_after == 2.5
    assert not by_chan[CHAN].caught_up
    assert by_chan[CHAN2].caught_up                    # the other surface finished
    assert len(_contents(ledger)) == 10

    # once the limit clears, the SAME state resumes the stopped surface
    client.rate_limited.clear()
    report2 = _backfill(ledger, client, iso=iso).run()
    assert report2.all_caught_up
    assert len(_contents(ledger)) == 20


def test_non_allowlisted_surface_is_never_fetched(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    client = PagingClient()
    client.add_history(FOREIGN, 5)
    bf = DiscordBackfill(client, _iso(read=(CHAN,)), IdentityRegistry(ledger),
                         ledger, surfaces=None)
    # even if someone hands the backfill a foreign surface explicitly:
    from trellis.runner import PollSurface
    bf.surfaces.append(PollSurface(FOREIGN))
    bf.run()
    assert FOREIGN not in client.fetched               # never even fetched (D30)
    assert _contents(ledger) == []


def test_bot_own_messages_are_skipped(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    client = PagingClient()
    client.add_history(CHAN, 3)
    client.messages[CHAN].append((4, "trellis-bot", BOT, "my own post"))
    _backfill(ledger, client).run()
    assert "my own post" not in _contents(ledger)
    assert len(_contents(ledger)) == 3


def test_run_budget_is_bounded_and_reported(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso(read=(CHAN, CHAN2))
    client = PagingClient()
    client.add_history(CHAN, 100)
    client.add_history(CHAN2, 100)
    report = _backfill(ledger, client, iso=iso, page_limit=50,
                       max_messages_per_run=100).run()
    assert report.budget_exhausted
    assert len(_contents(ledger)) == 100
    # progress state is on the ledger — resumable, queryable
    states = [e for e in ledger.entries() if e.kind == BACKFILL_STATE_KIND]
    assert states
