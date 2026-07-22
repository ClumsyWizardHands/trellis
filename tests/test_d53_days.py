"""test_d53_days.py — D53: comprehension walks the record one day at a time.

Pins: days are digested NEWEST first, as units, folding (a re-pass reads the
next older day, never re-reads); the digest confidence is capped and its basis
honest; without a model seat the digest degrades to counts-only (never fake
prose); the day note lands in the vault; comprehension counts days-as-units;
and term evidence is RECENCY-WEIGHTED — the oldest-N evidence bug (an
assumption built on last year's usage) stays dead.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from trellis.ingest import DiscordMessage
from trellis.isolation import (AgentIdentity, Isolation, SurfaceAllowlist,
                               ingest_scoped_discord_idempotent)
from trellis.ledger import Ledger
from trellis.memory import Workspace
from trellis.onboard import (DAY_DIGEST_KIND, OnboardingRitual, comprehension,
                             propose_meaning, record_consent, term_lineage)
from trellis.providers.mock import MockProvider
from trellis.registry import IdentityRegistry

CHAN = "chan-d"
_T0 = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def _iso():
    return Isolation(identity=AgentIdentity(name="trellis"),
                     allow=SurfaceAllowlist(read=frozenset((CHAN,)),
                                            act=frozenset()))


def _seed_days(ledger, n_days, per_day=3, start_id=1000):
    msgs = []
    for d in range(n_days):
        for i in range(per_day):
            mid = start_id + d * per_day + i
            msgs.append(DiscordMessage(
                author="brett", content=f"day {d} msg {i} about the empire",
                posted_at=_T0 + timedelta(days=d, minutes=i),
                channel=CHAN, channel_name="d", message_id=str(mid),
                author_id="u-brett"))
    ingest_scoped_discord_idempotent(ledger, msgs, _iso(),
                                     IdentityRegistry(ledger))


def _day_json(summary="the team discussed the empire", conf=0.9):
    return json.dumps({"summary": summary,
                       "notable": ["empire came up repeatedly"],
                       "unclear": ["what 'empire' commits anyone to"],
                       "confidence": conf})


def _ritual(ledger, tmp_path, ground, provider=None, days_per_pass=2):
    record_consent(ledger, "alex", True)
    return OnboardingRitual(ledger, Workspace(tmp_path / "ws", ledger),
                            ground=ground, provider=provider,
                            registry=IdentityRegistry(ledger), seed_terms=[],
                            days_per_pass=days_per_pass)


def test_days_digest_newest_first_and_fold(ledger, tmp_path, ground):
    _seed_days(ledger, 4)                              # 2026-07-10..13
    maker = MockProvider(id="mock:sonnet")
    for _ in range(4):
        maker.enqueue_text(_day_json())
    ritual = _ritual(ledger, tmp_path, ground, provider=maker, days_per_pass=2)

    s1 = ritual.learning_pass()
    assert s1["days_digested"] == ["2026-07-13", "2026-07-12"]   # newest first
    s2 = ritual.learning_pass()
    assert s2["days_digested"] == ["2026-07-11", "2026-07-10"]   # walks backward
    s3 = ritual.learning_pass()
    assert s3["days_digested"] == []                             # nothing re-read
    assert len(ledger.active(DAY_DIGEST_KIND)) == 4

    # the digest is honest: capped confidence, model basis, unclear surfaced
    d = next(e for e in ledger.active(DAY_DIGEST_KIND)
             if e.body["day"] == "2026-07-13")
    assert d.body["confidence"] <= 0.7                           # capped
    assert "unconfirmed" in d.body["basis"]
    assert d.body["unclear"]
    note = ritual.workspace.read("map/days/2026-07-13.md")
    assert "What happened" in note and "leaves unclear" in note
    # comprehension now counts time understood, not just items swallowed
    comp = comprehension(ledger)
    assert comp["days_digested"] == 4 and comp["days_total"] == 4


def test_digest_without_model_is_counts_never_prose(ledger, tmp_path, ground):
    _seed_days(ledger, 1)
    ritual = _ritual(ledger, tmp_path, ground, provider=None, days_per_pass=1)
    s = ritual.learning_pass()
    assert s["days_digested"] == ["2026-07-10"]
    d = ledger.active(DAY_DIGEST_KIND)[0]
    assert d.body["summary"] == ""                     # no fabricated reading
    assert d.body["confidence"] == 0.3
    assert "counts only" in d.body["basis"]
    assert d.body["voices"] == ["brett"]


def test_malformed_day_reply_degrades_to_counts(ledger, tmp_path, ground):
    _seed_days(ledger, 1)
    bad = MockProvider(id="mock:sonnet")
    bad.enqueue_text("what a day it was!")             # no JSON
    ritual = _ritual(ledger, tmp_path, ground, provider=bad, days_per_pass=1)
    ritual.learning_pass()
    d = ledger.active(DAY_DIGEST_KIND)[0]
    assert d.body["summary"] == "" and "counts only" in d.body["basis"]


def test_term_evidence_is_recency_weighted(ledger, tmp_path, ground):
    _seed_days(ledger, 20, per_day=4)                  # 80 uses of "empire"
    lin = term_lineage(ledger, "empire")
    assert lin.occurrences == 80
    assert len(lin.entry_ids) == 50
    # the kept evidence = 5 earliest (the anchor) + 45 MOST RECENT — the bulk
    # of what the model reads is current usage, not last year's
    by_id = {e.id: e for e in ledger.entries()}
    times = [by_id[i].stamp.event_time for i in lin.entry_ids]
    assert times[:5] == sorted(times[:5])              # the anchor, oldest
    assert min(times[5:]) > times[4]                   # everything else is newer
    assert max(times) == max(by_id[i].stamp.event_time
                             for i in lin.entry_ids)   # includes the very newest

    # and the excerpts the model actually reads lean newest
    probe = MockProvider(id="mock:probe")
    probe.enqueue_text(json.dumps({"meaning": "x", "confidence": 0.5,
                                   "unsure": ""}))
    propose_meaning(probe, "empire", lin, ledger, max_excerpts=8)
    prompt = probe.calls[0]["messages"][0]["content"]
    assert "day 19" in prompt                          # the most recent day is read
    assert prompt.count("day 0 ") <= 2                 # the ancient past is anchor-only
