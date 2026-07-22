"""transcripts.py — a local folder of transcripts, ridden through the spine.

trellis already models a transcript as `RawItem(kind="transcript",
machine_transcribed=…)`; what was missing is the adapter that turns a folder the
human points at (Whisper output, meeting notes, exported docs) into those items,
plus the harvester that lands a document on the ledger as ONE navigable entry.

Honesty rules baked in:

  * event_time is the transcript's OWN claim, never now(): a leading
    `YYYY-MM-DD` in the filename wins; otherwise the file's mtime (a real
    timestamp the filesystem holds). Either way `Provenance.event_time_
    reconstructed` stays True downstream — the time is a claim, not truth.
  * ASR output is FLAGGED, loudly: `.vtt`/`.srt` files (and names carrying an
    asr/whisper/auto-transcript marker) set `machine_transcribed=True`, so the
    fallibility rides every derived understanding (FLOOR + OR, never laundered).
  * idempotent by construction: `item_id` is the file's relative path, so a
    re-scan is a no-op and an edited transcript is a CORRECTION (retire +
    re-harvest), not a duplicate — sources.py's contract, unchanged.

The `document_harvester` here is shared with the Google adapter: both surfaces
land `source_document` entries with the same body shape, so every downstream
reader (term lineage, the map, position history) treats a Drive doc and a local
transcript identically.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .ledger import Ledger
from .sources import Harvester, Provenance, RawItem

SOURCE_DOCUMENT_KIND = "source_document"

#: content cap for one ledger entry — a document beyond this is truncated with an
#: honest flag, never silently clipped. (~200k chars ≈ a very long transcript.)
MAX_DOCUMENT_CHARS = 200_000

#: extensions that are machine transcription by format
_ASR_EXTS = {".vtt", ".srt"}
#: filename markers that signal MACHINE-GENERATED text — ASR output, and
#: AI-generated meeting notes. Gemini notes are flagged on Alex's direct word
#: (2026-07-22): "notes from gemini are much worse than the actual transcripts
#: they come from" — they are a lossy derivative, and their fallibility must
#: ride every understanding built on them (FLOOR + OR, never laundered).
_ASR_MARKERS = ("whisper", "autotranscript", "auto-transcript", "asr",
                "notes-by-gemini", "notes by gemini", "meeting-started")

_DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _event_time_for(path: Path) -> datetime:
    """The transcript's own time claim: a YYYY-MM-DD filename prefix wins;
    otherwise the file's mtime (tz-aware UTC). Never a naked now()."""
    m = _DATE_PREFIX.match(path.stem)
    if m:
        try:
            y, mo, d = (int(g) for g in m.groups())
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except ValueError:
            pass   # a nonsense date like 2026-99-99 falls back to mtime
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _is_machine_transcribed(path: Path) -> bool:
    if path.suffix.lower() in _ASR_EXTS:
        return True
    low = path.name.lower()
    return any(marker in low for marker in _ASR_MARKERS)


def bounded_content(text: str) -> tuple[str, bool]:
    """(content, truncated). The cap keeps one document from bloating the ledger;
    the flag keeps the truncation honest."""
    if len(text) <= MAX_DOCUMENT_CHARS:
        return text, False
    return text[:MAX_DOCUMENT_CHARS], True


class TranscriptFolderAdapter:
    """A `SourceAdapter` over one local folder. Reads only the extensions it
    understands; everything else is counted in `skipped`, never silently eaten.

    `kind` lets the same adapter serve a folder of DOCUMENTS (principles
    checks, protocols, reference docs — `kind="document"`) as honestly as a
    folder of transcripts: the item kind is what downstream provenance keys
    event_time_reconstructed on, so a mislabeled kind would be a small lie."""

    EXTENSIONS = {".txt", ".md", ".vtt", ".srt"}

    def __init__(self, folder: "Path | str", source: str = "transcript",
                 kind: str = "transcript"):
        self.folder = Path(folder).expanduser()
        self.source = source
        self.kind = kind
        self.skipped: list[str] = []     # relative paths not understood, per scan

    def discover(self) -> Iterator[RawItem]:
        self.skipped = []
        if not self.folder.is_dir():
            return
        for path in sorted(self.folder.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            rel = str(path.relative_to(self.folder))
            if path.suffix.lower() not in self.EXTENSIONS:
                self.skipped.append(rel)
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self.skipped.append(rel)
                continue
            yield RawItem(
                source=self.source,
                channel=self.folder.name,
                content=text,
                event_time=_event_time_for(path),
                item_id=rel,
                kind=self.kind,
                machine_transcribed=_is_machine_transcribed(path),
                meta=(("title", path.stem), ("path", rel)),
            )


def document_harvester(ledger: Ledger, agent: str) -> Harvester:
    """Land one document/transcript RawItem as ONE `source_document` ledger
    entry — title, bounded content, provenance — returning its id so the
    idempotent spine can retire it cleanly on a correction. Shared by the
    transcript-folder and Google Drive adapters."""
    def h(item: RawItem, prov: Provenance) -> list:
        meta = dict(item.meta)
        title = meta.get("title") or item.item_id or "(untitled)"
        content, truncated = bounded_content(item.content)
        e = ledger.append(
            kind=SOURCE_DOCUMENT_KIND, author=agent,
            body={"title": title, "content": content, "truncated": truncated,
                  "source": item.source, "channel": item.channel,
                  "item_id": item.item_id, "kind": item.kind,
                  "machine_transcribed": item.machine_transcribed,
                  "provenance": prov.to_dict()},
            event_time=item.event_time,
            tags=(item.source, "document", title[:60]))
        return [e.id]
    return h
