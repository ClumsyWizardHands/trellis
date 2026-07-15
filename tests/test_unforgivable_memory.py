"""Unforgivable #3 — context-loss / no-memory / misattribution.
The ledger is bitemporal, attributed, supersession-not-deletion; the workspace
is gated by the synthesis test; the agent dies and leaves an epitaph."""

from datetime import datetime, timezone

import pytest

from trellis.ledger import Ledger, LedgerIntegrityError
from trellis.memory import (CompactionOrderError, SynthesisTestError, Workspace)

GOOD_JUSTIFICATION = ("this synthesized judgment exists nowhere in transcripts "
                      "or logs and cannot be re-derived mechanically")


def test_no_anonymous_memory(ledger):
    with pytest.raises(LedgerIntegrityError, match="author"):
        ledger.append(kind="note", author="  ", body={"x": 1})


def test_supersession_keeps_lineage_no_gaslighting(ledger):
    """Clare, 2026-02-17: 'Atlas, you did some gaslighting gymnastics last
    night.' A corrected memory keeps the mistake AND the correction."""
    e1 = ledger.append("fact", "atlas", {"claim": "Lyra is lead"})
    e2 = ledger.correct(e1.id, "clare", {"claim": "Moro is lead"})
    current = ledger.current("fact")
    assert [e.id for e in current] == [e2.id]          # what we believe now
    chain = ledger.lineage(e2.id)
    assert [e.id for e in chain] == [e1.id, e2.id]     # history intact
    assert ledger.get(e1.id) is not None               # nothing deleted


def test_as_of_reads_what_was_known_then(ledger, clock):
    e1 = ledger.append("fact", "atlas", {"v": "old"})
    t_between = clock.advance(days=1)
    clock.advance(days=1)   # the correction is written a day AFTER t_between
    ledger.correct(e1.id, "atlas", {"v": "new"})
    then = ledger.as_of(t_between)
    assert any(e.body.get("v") == "old" for e in then)
    assert not any(e.body.get("v") == "new" for e in then)


def test_search_never_drifts_from_file(ledger):
    ledger.append("fact", "atlas", {"topic": "verification is the name of the game"})
    hits = ledger.search("verification")
    assert len(hits) == 1
    # superseded entries drop out of search because search reads current()
    ledger.correct(hits[0].id, "atlas", {"topic": "superseded thought"})
    assert ledger.search("name of the game") == []


def test_corrupt_line_is_loud_not_skipped(tmp_path, ground):
    led = Ledger(tmp_path / "l.jsonl", ground)
    led.append("fact", "a", {"x": 1})
    with led.path.open("a") as f:
        f.write("{corrupt\n")
    with pytest.raises(LedgerIntegrityError, match="unreadable"):
        led.entries()


def test_synthesis_test_gates_writes(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    with pytest.raises(SynthesisTestError):
        ws.write("notes/x.md", "hello", "atlas", "important")
    with pytest.raises(SynthesisTestError):
        ws.write("notes/x.md", "hello", "atlas", "for later just in case")
    receipt = ws.write("notes/x.md", "hello", "atlas", GOOD_JUSTIFICATION)
    assert ledger.get(receipt.ledger_entry) is not None


def test_flush_before_compact_enforced(tmp_path, ledger):
    """The OpenClaw lesson: compaction memory loss was the #1 reported
    failure. Here compaction refuses to run before the flush."""
    ws = Workspace(tmp_path / "ws", ledger)
    with pytest.raises(CompactionOrderError, match="has not flushed"):
        ws.compact_allowed("session-1")
    ws.flush("session-1", "atlas",
             survivors=[("pins/decision.md", "keep this", GOOD_JUSTIFICATION)])
    ws.compact_allowed("session-1")  # now fine


def test_empty_flush_is_legitimate_but_recorded(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    ws.flush("s2", "atlas", survivors=[])
    flushes = [e for e in ledger.entries() if e.kind == "memory_flush"]
    assert flushes[-1].body["explicit_nothing"] is True


def test_epitaph_the_agent_dies_the_record_survives(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    ws.epitaph("s3", "witness",
               what_happened="read three transcripts, formed two opinions",
               what_was_learned="Peter's ask pattern is findability, not features",
               open_threads=["confirm pricing canon with Brett"])
    latest = ws.latest_epitaphs(1)[0]
    assert "no longer exists" in latest
    assert "the record, not a memory" in latest
    assert "confirm pricing canon" in latest


def test_workspace_map_is_titles_not_content(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    ws.write("reads/a.md", "# The read on EAF\nlots of content " * 100, "x",
             GOOD_JUSTIFICATION)
    m = ws.map()
    assert len(m) == 1
    assert "The read on EAF" in m[0]
    assert "lots of content lots" not in m[0]  # map, not territory
