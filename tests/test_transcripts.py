"""test_transcripts.py — the local transcript folder → the idempotent spine.

Pins: honest event_time (filename date beats mtime; never now()), ASR flagged,
unknown extensions counted not eaten, idempotent re-scan, edited file =
correction (retire + re-harvest), bounded content with an honest flag.
"""

from __future__ import annotations

from datetime import timezone

from trellis.ledger import Ledger
from trellis.sources import Ingestor
from trellis.transcripts import (MAX_DOCUMENT_CHARS, SOURCE_DOCUMENT_KIND,
                                 TranscriptFolderAdapter, bounded_content,
                                 document_harvester)


def _folder(tmp_path):
    d = tmp_path / "transcripts"
    d.mkdir()
    (d / "2026-07-10 chiefs sync.txt").write_text(
        "Brett: the overnight soak finished.", encoding="utf-8")
    (d / "meeting-notes.md").write_text("plain human notes", encoding="utf-8")
    (d / "whisper-standup.vtt").write_text("WEBVTT\nauto words", encoding="utf-8")
    (d / "photo.png").write_bytes(b"\x89PNG")
    return d


def test_discover_kinds_flags_and_times(tmp_path):
    adapter = TranscriptFolderAdapter(_folder(tmp_path))
    items = {i.item_id: i for i in adapter.discover()}
    assert set(items) == {"2026-07-10 chiefs sync.txt", "meeting-notes.md",
                          "whisper-standup.vtt"}
    assert adapter.skipped == ["photo.png"]            # counted, never eaten

    dated = items["2026-07-10 chiefs sync.txt"]
    assert dated.event_time.date().isoformat() == "2026-07-10"   # the file's OWN claim
    assert dated.event_time.tzinfo is not None
    assert dated.kind == "transcript"
    assert dated.machine_transcribed is False

    asr = items["whisper-standup.vtt"]
    assert asr.machine_transcribed is True             # ASR flagged loud

    notes = items["meeting-notes.md"]
    assert notes.event_time.tzinfo is timezone.utc     # mtime fallback, tz-aware


def test_ingest_is_idempotent_and_correction_aware(tmp_path, ground):
    folder = _folder(tmp_path)
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    ing = Ingestor(ledger, author="test-ingest")
    adapter = TranscriptFolderAdapter(folder)
    h = document_harvester(ledger, "test-ingest")

    r1 = ing.ingest(adapter.discover(), h)
    assert r1.processed == 3
    docs = ledger.active(SOURCE_DOCUMENT_KIND)
    assert len(docs) == 3
    by_title = {e.body["title"]: e for e in docs}
    assert by_title["whisper-standup"].body["machine_transcribed"] is True
    assert by_title["2026-07-10 chiefs sync"].body["provenance"]["source_refs"]

    # re-scan is a no-op
    r2 = ing.ingest(adapter.discover(), h)
    assert r2.processed == 0 and r2.skipped_duplicate == 3
    assert len(ledger.active(SOURCE_DOCUMENT_KIND)) == 3

    # an edited transcript is a CORRECTION: the stale derivation retires
    (folder / "meeting-notes.md").write_text("corrected human notes", encoding="utf-8")
    r3 = ing.ingest(adapter.discover(), h)
    assert r3.corrected == 1
    live = ledger.active(SOURCE_DOCUMENT_KIND)
    assert len(live) == 3
    assert any(e.body["content"] == "corrected human notes" for e in live)
    assert not any(e.body["content"] == "plain human notes" for e in live)


def test_bounded_content_is_honest_about_truncation():
    text, truncated = bounded_content("x" * (MAX_DOCUMENT_CHARS + 10))
    assert truncated is True and len(text) == MAX_DOCUMENT_CHARS
    text2, truncated2 = bounded_content("short")
    assert truncated2 is False and text2 == "short"


def test_missing_folder_discovers_nothing(tmp_path):
    adapter = TranscriptFolderAdapter(tmp_path / "nope")
    assert list(adapter.discover()) == []
