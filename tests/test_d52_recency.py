"""test_d52_recency.py — D52 (Alex, 2026-07-22): recency-first acquisition.

Pins: the first bite is the NEWEST page and it seeds the live poll's cursor
(the present is owned immediately, no gap and no duplication); each pass
descends roughly one day-slice per surface; curiosity focus descends first and
deeper; the bottom of history is a recorded fact and is never re-fetched; a
restart resumes the descent exactly; documents ingest newest-first with a
reported (never silent) deferral, and corrections are never deferred.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trellis.backfill import DESCENT_CURSOR_KIND, RecencyBackfill
from trellis.discord_api import MessageBatch
from trellis.ingest import DiscordMessage
from trellis.isolation import AgentIdentity, Isolation, SurfaceAllowlist
from trellis.ledger import Ledger
from trellis.registry import IdentityRegistry
from trellis.runner import POLL_CURSOR_KIND, DiscordPoll, PollSurface

CHAN = "chan-a"
CHAN2 = "chan-b"

_T0 = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso(read=(CHAN,)):
    return Isolation(identity=AgentIdentity(name="trellis"),
                     allow=SurfaceAllowlist(read=frozenset(read), act=frozenset()))


class DescentClient:
    """Honors after/before/limit like the real API. Messages are (id, day):
    id N is posted on day `N // 10` — ten messages per day."""

    def __init__(self):
        self.messages: dict = {}
        self.fetched: list = []

    def add_days(self, channel, days, per_day=10):
        rows = self.messages.setdefault(channel, [])
        start = len(rows) + 1
        for i in range(start, start + days * per_day):
            rows.append(i)

    def _to_msg(self, channel, mid, channel_name):
        posted = _T0 + timedelta(days=(mid - 1) // 10, minutes=mid % 10)
        return DiscordMessage(author="brett", content=f"{channel} msg {mid}",
                              posted_at=posted, channel=channel,
                              channel_name=channel_name, message_id=str(mid),
                              author_id="u-brett")

    def fetch_messages(self, channel_id, after=None, limit=50, *, before=None,
                       channel_name="", is_thread=False, parent_channel=None,
                       is_dm=False):
        self.fetched.append((channel_id, after, before))
        rows = self.messages.get(channel_id, [])
        if after is not None:
            window = [m for m in rows if m > int(after)][:limit]
        elif before is not None:
            window = [m for m in rows if m < int(before)][-limit:]
        else:
            window = rows[-limit:]                     # the newest page
        out = [self._to_msg(channel_id, m, channel_name) for m in sorted(window)]
        cursor = out[-1].message_id if out else after
        return MessageBatch(messages=out, cursor=cursor)

    def current_user_id(self):
        return "bot-self"


def _bf(ledger, client, iso=None, **kw):
    iso = iso or _iso()
    kw.setdefault("page_limit", 10)
    return RecencyBackfill(client, iso, IdentityRegistry(ledger), ledger, **kw)


def _ids(ledger):
    return [int(e.body["message_id"]) for e in ledger.entries()
            if e.kind == "discord_message"]


# --------------------------------------------------------------------------- #
# the present first, then day-sized descent                                    #
# --------------------------------------------------------------------------- #

def test_first_bite_is_newest_and_seeds_the_live_poll(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    client = DescentClient()
    client.add_days(CHAN, 5)                          # ids 1..50, day 0..4
    bf = _bf(ledger, client)

    bf.run()
    got = _ids(ledger)
    assert max(got) == 50                             # the NEWEST arrived first
    assert min(got) > 1                               # the deep past did NOT

    # the live poll owns the present from this moment — no gap, no duplicate
    cursors = [e.body for e in ledger.entries() if e.kind == POLL_CURSOR_KIND]
    assert cursors and cursors[0]["cursor"] == "50"
    client.add_days(CHAN, 1)                          # ids 51..60 arrive live
    poll = DiscordPoll(client, _iso(), IdentityRegistry(ledger), ledger, ground)
    summary = poll.poll()
    assert summary["admitted"] == 10
    assert max(_ids(ledger)) == 60


def test_descent_is_day_sliced_and_resumable(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    client = DescentClient()
    client.add_days(CHAN, 5)
    bf = _bf(ledger, client, slice_days=1.0)

    counts = []
    for _ in range(8):
        # a FRESH instance each pass — the descent cursor folds off the ledger
        report = _bf(ledger, client, slice_days=1.0).run()
        counts.append(len(_ids(ledger)))
        if report.all_caught_up:
            break
    assert counts[-1] == 50                           # all of history, eventually
    assert counts[0] < 50                             # but not in one gulp
    assert sorted(_ids(ledger)) == list(range(1, 51)) # nothing lost, nothing doubled

    # bottom is a recorded fact; a further run re-fetches NOTHING
    st = [e.body for e in ledger.entries() if e.kind == DESCENT_CURSOR_KIND]
    assert st[-1]["bottom"] is True
    fetches = len(client.fetched)
    _bf(ledger, client).run()
    assert len(client.fetched) == fetches


def test_curiosity_focus_descends_first_and_deeper(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    iso = _iso(read=(CHAN, CHAN2))
    client = DescentClient()
    client.add_days(CHAN, 4)
    client.add_days(CHAN2, 4)
    surfaces = [PollSurface(CHAN, "alpha"), PollSurface(CHAN2, "beta")]

    # tight budget: only the focus surface's slice fits this pass
    bf = _bf(ledger, client, iso=iso, max_messages_per_run=30,
             slice_days=1.0)
    bf.surfaces = surfaces
    bf.run(focus_channels={"beta"})
    fetched_order = [c for c, _, _ in client.fetched]
    assert fetched_order[0] == CHAN2                  # focus went first
    beta = [e for e in ledger.entries() if e.kind == "discord_message"
            and e.body["channel"] == CHAN2]
    alpha = [e for e in ledger.entries() if e.kind == "discord_message"
             and e.body["channel"] == CHAN]
    assert len(beta) > len(alpha)                     # and bit deeper


# --------------------------------------------------------------------------- #
# newest-first bounded documents                                               #
# --------------------------------------------------------------------------- #

def test_documents_ingest_newest_first_with_reported_deferral(
        tmp_path, ground):
    from trellis.memory import Workspace
    from trellis.onboard import OnboardingRitual, record_consent
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    record_consent(ledger, "alex", True)
    folder = tmp_path / "docs"; folder.mkdir()
    for i in range(8):
        (folder / f"2026-07-{i+1:02d} note.md").write_text(f"note {i+1}",
                                                           encoding="utf-8")
    from trellis.transcripts import TranscriptFolderAdapter
    ritual = OnboardingRitual(ledger, Workspace(tmp_path / "ws", ledger),
                              ground=ground, seed_terms=[], docs_per_pass=3)
    s1 = ritual.learning_pass(sources=[TranscriptFolderAdapter(folder)])
    key = next(iter(s1["ingested"]))
    assert s1["ingested"][key]["processed"] == 3
    assert s1["ingested"][key]["deferred_for_pacing"] == 5   # reported, not silent
    titles = [e.body["title"] for e in ledger.active("source_document")]
    assert titles and all("2026-07-0" not in t or t >= "2026-07-06" for t in titles)

    # a CORRECTION to an already-ingested doc is never deferred
    (folder / "2026-07-08 note.md").write_text("corrected!", encoding="utf-8")
    s2 = ritual.learning_pass(sources=[TranscriptFolderAdapter(folder)])
    key2 = next(iter(s2["ingested"]))
    assert s2["ingested"][key2]["corrected"] == 1
    live = [e.body["content"] for e in ledger.active("source_document")]
    assert "corrected!" in live

    # successive passes drain the backlog newest-first until done
    s3 = ritual.learning_pass(sources=[TranscriptFolderAdapter(folder)])
    key3 = next(iter(s3["ingested"]))
    assert s3["ingested"][key3]["deferred_for_pacing"] == 0
    assert len(ledger.active("source_document")) == 8
