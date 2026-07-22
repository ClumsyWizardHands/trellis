"""test_d55_continuity.py — D55: the walk and the intake coexist honestly.

Pins: TODAY is never read (a half-lived day must not freeze into a digest);
a day below the Discord descent frontier is not read until the descent passes
it (or bottoms); a day below the paced-doc backlog frontier waits likewise;
and a WALKED day that grows — late material after its reading — reopens,
re-reads with the growth named, and returns to the human's gate.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from trellis.backfill import DESCENT_CURSOR_KIND
from trellis.ingest import DiscordMessage
from trellis.isolation import (AgentIdentity, Isolation, SurfaceAllowlist,
                               ingest_scoped_discord_idempotent)
from trellis.ledger import Ledger
from trellis.memory import Workspace
from trellis.onboard import (DAY_DIGEST_KIND, OnboardingRitual,
                             day_review_state, latest_day_digest,
                             record_consent, review_day)
from trellis.providers.mock import MockProvider
from trellis.registry import IdentityRegistry

CHAN = "chan-c"
_T0 = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)   # clock: 2026-07-15


def _iso():
    return Isolation(identity=AgentIdentity(name="trellis"),
                     allow=SurfaceAllowlist(read=frozenset((CHAN,)),
                                            act=frozenset()))


def _seed(ledger, day_offset, n=2, start_id=None):
    start_id = start_id or (1000 + day_offset * 100)
    msgs = [DiscordMessage(author="brett", content=f"d{day_offset} m{i}",
                           posted_at=_T0 + timedelta(days=day_offset, minutes=i),
                           channel=CHAN, channel_name="c",
                           message_id=str(start_id + i), author_id="u-b")
            for i in range(n)]
    ingest_scoped_discord_idempotent(ledger, msgs, _iso(),
                                     IdentityRegistry(ledger))


def _day_json(s):
    return json.dumps({"summary": s, "notable": [], "unclear": [],
                       "confidence": 0.9})


def _ritual(ledger, tmp_path, ground, provider, gate=True):
    record_consent(ledger, "alex", True)
    return OnboardingRitual(ledger, Workspace(tmp_path / "ws", ledger),
                            ground=ground, provider=provider,
                            registry=IdentityRegistry(ledger), seed_terms=[],
                            days_per_pass=2, day_gate=gate)


def test_today_is_never_read(ledger, tmp_path, ground):
    _seed(ledger, 5)                    # 2026-07-15 == the FakeClock's TODAY
    _seed(ledger, 4)                    # 2026-07-14 — completed
    maker = MockProvider(id="m")
    maker.enqueue_text(_day_json("yesterday"))
    ritual = _ritual(ledger, tmp_path, ground, maker)
    s = ritual.learning_pass()
    assert s["days_digested"] == ["2026-07-14"]     # today skipped
    review_day(ledger, "2026-07-14", "yes", "alex")
    s2 = ritual.learning_pass()
    assert "2026-07-15" not in s2["days_digested"]  # still being lived


def test_descent_frontier_blocks_unacquired_days(ledger, tmp_path, ground):
    _seed(ledger, 0)
    _seed(ledger, 2)                    # 07-10 and 07-12 have material
    # the descent for CHAN has only reached midday 07-12 — 07-12 is partial,
    # 07-10 not yet delivered at all
    ledger.append(kind=DESCENT_CURSOR_KIND, author="t",
                  body={"channel": CHAN, "before": "500",
                        "oldest_time": "2026-07-12T09:00:00+00:00",
                        "bottom": False}, tags=("d",))
    maker = MockProvider(id="m")
    for _ in range(3):
        maker.enqueue_text(_day_json("x"))
    ritual = _ritual(ledger, tmp_path, ground, maker)
    s = ritual.learning_pass()
    assert s["days_digested"] == []                 # both below the frontier
    # the channel bottoms out → everything is delivered → the walk proceeds
    ledger.append(kind=DESCENT_CURSOR_KIND, author="t",
                  body={"channel": CHAN, "before": "1",
                        "oldest_time": "2026-07-10T09:00:00+00:00",
                        "bottom": True}, tags=("d",))
    s2 = ritual.learning_pass()
    assert s2["days_digested"] == ["2026-07-12"]


def test_walked_day_that_grows_reopens(ledger, tmp_path, ground):
    _seed(ledger, 1, n=2)                           # 07-11, two items
    maker = MockProvider(id="m")
    maker.enqueue_text(_day_json("first reading"))
    maker.enqueue_text(_day_json("fuller reading"))
    ritual = _ritual(ledger, tmp_path, ground, maker)
    ritual.learning_pass()
    review_day(ledger, "2026-07-11", "yes", "alex")
    assert day_review_state(ledger, "2026-07-11") == "approved"

    # late material lands in the approved day (a slower channel's descent)
    _seed(ledger, 1, n=3, start_id=9000)
    s = ritual.learning_pass()
    assert s["days_digested"] == ["2026-07-11"]     # reopened, re-read
    prompt = maker.calls[-1]["messages"][0]["content"]
    assert "NEW MATERIAL" in prompt and "3 new item(s)" in prompt
    d = latest_day_digest(ledger, "2026-07-11")
    assert d.body["items"] == 5
    assert "new material arrived" in d.body["basis"]
    assert day_review_state(ledger, "2026-07-11") == "pending"   # back to you


def test_doc_backlog_frontier_blocks_walk(ledger, tmp_path, ground):
    from trellis.transcripts import TranscriptFolderAdapter
    folder = tmp_path / "docs"; folder.mkdir()
    for off in (10, 11, 12, 13):
        (folder / f"2026-07-{off} note.md").write_text(f"n{off}",
                                                       encoding="utf-8")
    record_consent(ledger, "alex", True)
    maker = MockProvider(id="m")
    maker.enqueue_text(_day_json("x"))
    ritual = OnboardingRitual(ledger, Workspace(tmp_path / "ws", ledger),
                              ground=ground, provider=maker,
                              registry=IdentityRegistry(ledger), seed_terms=[],
                              days_per_pass=2, day_gate=False, docs_per_pass=2)
    # pass 1: comprehension runs FIRST (no corpus yet), then acquisition feeds
    # the 2 newest docs (07-13, 07-12) with a backlog → frontier = 07-12
    s1 = ritual.learning_pass(sources=[TranscriptFolderAdapter(folder)])
    assert s1["days_digested"] == []
    key = next(iter(s1["ingested"]))
    assert s1["ingested"][key]["deferred_for_pacing"] == 2
    # pass 2: the walk honors the frontier — only 07-13 is fully delivered
    s2 = ritual.learning_pass(sources=[TranscriptFolderAdapter(folder)])
    assert s2["days_digested"] == ["2026-07-13"]
