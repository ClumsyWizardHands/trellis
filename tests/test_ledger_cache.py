"""The rebuildable ledger read-cache (D27): faster reads, same truth.

Pins that the cache is a pure performance layer over the file — the file stays the
sole source of truth. Every read reflects the current file (incrementally parsed,
each line once); an append by ANY instance is seen; a rewrite/shrink rebuilds; a
corrupt line still raises; concurrent appends on one instance lose nothing."""

import threading

import pytest

from trellis.clock import TimeGround
from trellis.ledger import Ledger, LedgerIntegrityError


def test_new_appends_are_reflected_incrementally(tmp_path, ground):
    led = Ledger(tmp_path / "l.jsonl", ground)
    led.append("fact", "w", {"i": 0})
    assert len(led.entries()) == 1
    led.append("fact", "w", {"i": 1})
    assert len(led.entries()) == 2          # the cache picked up the new line
    ids = {e.body["i"] for e in led.entries()}
    assert ids == {0, 1}


def test_an_append_by_another_instance_is_seen(tmp_path, ground):
    """The file is the source of truth: a second Ledger over the same file, and
    the first instance re-reading, both see each other's appends."""
    path = tmp_path / "l.jsonl"
    a = Ledger(path, ground)
    b = Ledger(path, ground)
    a.append("fact", "w", {"src": "a"})
    assert len(a.entries()) == 1
    b.append("fact", "w", {"src": "b"})     # a different instance writes
    assert len(a.entries()) == 2            # instance A re-reads and sees B's append
    assert {e.body["src"] for e in a.entries()} == {"a", "b"}


def test_a_rewrite_or_shrink_rebuilds_the_cache(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    led = Ledger(path, ground)
    led.append("fact", "w", {"i": 0})
    led.append("fact", "w", {"i": 1})
    assert len(led.entries()) == 2
    # the file is rewritten smaller (e.g. a git checkout / demo reseed)
    other = Ledger(tmp_path / "src.jsonl", ground)
    other.append("fact", "w", {"only": True})
    path.write_bytes((tmp_path / "src.jsonl").read_bytes())   # smaller content
    got = led.entries()
    assert len(got) == 1 and got[0].body == {"only": True}     # rebuilt from the file


def test_corrupt_line_still_raises_and_is_consistent(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    led = Ledger(path, ground)
    led.append("fact", "w", {"i": 0})
    assert len(led.entries()) == 1
    with path.open("a", encoding="utf-8") as f:
        f.write("{not valid json\n")
    with pytest.raises(LedgerIntegrityError):
        led.entries()
    with pytest.raises(LedgerIntegrityError):   # consistent across calls, not half-synced
        led.entries()


def test_entries_returns_a_fresh_list(tmp_path, ground):
    led = Ledger(tmp_path / "l.jsonl", ground)
    led.append("fact", "w", {"i": 0})
    a = led.entries()
    a.append("mutant")                       # caller mutation must not corrupt the cache
    assert len(led.entries()) == 1


def test_concurrent_appends_on_one_instance_lose_nothing(tmp_path, ground):
    """The concurrency-stress shape in miniature: one shared Ledger, many threads
    appending, the cache stays coherent and nothing is lost."""
    led = Ledger(tmp_path / "l.jsonl", ground)

    def writer(n):
        for i in range(200):
            led.append("fact", f"t{n}", {"n": n, "i": i})

    ts = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(led.entries()) == 1200        # 6 x 200, none lost, none double-counted


def test_as_of_and_active_still_correct_through_the_cache(tmp_path, clock, ground):
    from datetime import timedelta
    path = tmp_path / "l.jsonl"
    led = Ledger(path, ground)
    e1 = led.append("decision", "w", {"subject": "v1", "question_key": "q"})
    clock.advance(days=1)
    e2 = led.correct(e1.id, "w", {"subject": "v2", "question_key": "q"})
    # active() reflects the corrected head; as_of() reconstructs the past — through the cache
    active_ids = {e.id for e in led.active("decision")}
    assert e2.id in active_ids and e1.id not in active_ids
    past = {e.id for e in led.as_of(clock.t - timedelta(hours=12))}
    assert e1.id in past and e2.id not in past
