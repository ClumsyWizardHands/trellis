"""test_google_source.py — the thin Drive/Docs adapter, fully offline.

No Google library is required to run these tests: the Drive service is a fake
injected object honoring the client's chaining API, and every ungranted state
is pinned as a TYPED, honest refusal — never a silent stub.
"""

from __future__ import annotations

import pytest

from trellis.google_source import (GoogleDriveAdapter, GoogleNotGranted,
                                   google_status, run_grant_flow)
from trellis.ledger import Ledger
from trellis.sources import Ingestor
from trellis.transcripts import SOURCE_DOCUMENT_KIND, document_harvester

FOLDER = "folder-granted-123"


class _Call:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeFilesAPI:
    def __init__(self, pages, exports, media):
        self.pages = pages          # list of list-response dicts
        self.exports = exports      # file id -> bytes/str or Exception
        self.media = media          # file id -> bytes/str or Exception
        self.list_queries: list = []
        self._page = 0

    def list(self, **kw):
        self.list_queries.append(kw)
        token = kw.get("pageToken")
        idx = int(token) if token else 0
        return _Call(self.pages[idx])

    def export(self, fileId, mimeType):
        return _Call(self.exports[fileId])

    def get_media(self, fileId, **kw):
        return _Call(self.media[fileId])


class FakeDrive:
    def __init__(self, files_api):
        self._files = files_api

    def files(self):
        return self._files


def _drive():
    pages = [
        {"files": [
            {"id": "doc-1", "name": "Team Meeting Transcript",
             "mimeType": "application/vnd.google-apps.document",
             "modifiedTime": "2026-07-01T10:00:00+00:00"},
            {"id": "txt-1", "name": "principles.md", "mimeType": "text/markdown",
             "modifiedTime": "2026-06-15T09:00:00+00:00"},
        ], "nextPageToken": "1"},
        {"files": [
            {"id": "img-1", "name": "photo.png", "mimeType": "image/png",
             "modifiedTime": "2026-06-01T09:00:00+00:00"},
            {"id": "doc-2", "name": "empire notes",
             "mimeType": "application/vnd.google-apps.document",
             "modifiedTime": "2026-07-20T08:30:00+00:00"},
        ]},
    ]
    exports = {"doc-1": b"brett: the overnight soak is done",
               "doc-2": "the empire, lowercase on purpose"}
    media = {"txt-1": b"# principles\nnever fail silently"}
    return FakeDrive(FakeFilesAPI(pages, exports, media))


# --------------------------------------------------------------------------- #
# honest ungranted states                                                      #
# --------------------------------------------------------------------------- #

def test_no_folder_is_a_typed_refusal(monkeypatch):
    monkeypatch.delenv("TRELLIS_DRIVE_FOLDER", raising=False)
    monkeypatch.delenv("TRELLIS_GOOGLE_TOKEN_STORE", raising=False)
    adapter = GoogleDriveAdapter(folder_id="", service=_drive())
    with pytest.raises(GoogleNotGranted, match="TRELLIS_DRIVE_FOLDER"):
        list(adapter.discover())


def test_status_reports_awaiting_grant_not_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("TRELLIS_DRIVE_FOLDER", FOLDER)
    monkeypatch.setenv("TRELLIS_GOOGLE_TOKEN_STORE", str(tmp_path / "absent.json"))
    monkeypatch.delenv("TRELLIS_GOOGLE_CLIENT_SECRET", raising=False)
    st = google_status()
    assert st["ready"] is False
    assert st["folder_configured"] is True
    assert st["token_store_exists"] is False
    assert st["detail"]                                # says WHAT remains, plainly


def test_grant_flow_refuses_without_client_secret(tmp_path):
    with pytest.raises(GoogleNotGranted):
        run_grant_flow(str(tmp_path / "no-secret.json"), str(tmp_path / "tok.json"))


# --------------------------------------------------------------------------- #
# discovery over the fake service                                              #
# --------------------------------------------------------------------------- #

def test_discover_yields_scoped_rawitems(tmp_path):
    adapter = GoogleDriveAdapter(folder_id=FOLDER, service=_drive())
    items = {i.item_id: i for i in adapter.discover()}

    assert set(items) == {"doc-1", "txt-1", "doc-2"}
    assert adapter.skipped == ["photo.png"]            # counted, never eaten

    # the Drive QUERY itself is folder-scoped — nothing outside is even listed —
    # and shared-drive content is included (without these flags a shared-drive
    # folder lists EMPTY and reads as "nothing there", the live-wiring bug)
    for kw in adapter._service.files().list_queries:
        assert f"'{FOLDER}' in parents" in kw["q"]
        assert kw["includeItemsFromAllDrives"] is True
        assert kw["supportsAllDrives"] is True

    doc = items["doc-1"]
    assert doc.kind == "transcript"                    # Meet-style transcript name
    assert doc.machine_transcribed is True             # ASR flagged fallible
    assert doc.event_time.isoformat().startswith("2026-07-01")
    assert "overnight soak" in doc.content

    md = items["txt-1"]
    assert md.kind == "document" and md.machine_transcribed is False

    notes = items["doc-2"]
    assert notes.kind == "document"
    assert "lowercase on purpose" in notes.content


def test_drive_items_ride_the_idempotent_spine(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    ing = Ingestor(ledger, author="test-ingest")
    h = document_harvester(ledger, "test-ingest")
    adapter = GoogleDriveAdapter(folder_id=FOLDER, service=_drive())

    r1 = ing.ingest(adapter.discover(), h)
    assert r1.processed == 3
    r2 = ing.ingest(GoogleDriveAdapter(folder_id=FOLDER, service=_drive()).discover(), h)
    assert r2.processed == 0 and r2.skipped_duplicate == 3   # re-scan is a no-op

    # a re-edited doc (same id, new content) is a CORRECTION on the spine
    drive2 = _drive()
    drive2._files.exports["doc-2"] = "the empire — now with a second sentence"
    r3 = ing.ingest(GoogleDriveAdapter(folder_id=FOLDER, service=drive2).discover(), h)
    assert r3.corrected == 1
    live = [e.body["content"] for e in ledger.active(SOURCE_DOCUMENT_KIND)]
    assert "the empire — now with a second sentence" in live
    assert "the empire, lowercase on purpose" not in live


def test_unreadable_file_is_counted_not_fatal(tmp_path):
    drive = _drive()
    drive._files.exports["doc-1"] = RuntimeError("export exploded")
    adapter = GoogleDriveAdapter(folder_id=FOLDER, service=drive)
    items = {i.item_id for i in adapter.discover()}
    assert items == {"txt-1", "doc-2"}
    assert "Team Meeting Transcript" in adapter.skipped
