"""sources.py — the ingestion spine: read the team's record in, idempotently.

Phase A of the contemplative backdrop (docs/PLAN-contemplative-ingestion.md).
This layer does ONE job and does it deterministically: take raw items from the
sources the team already produces (Atlas's Discord dumps + transcripts, Whisper
output, media), give each a stable identity, and hand it to a harvester EXACTLY
once — surviving re-reads, partial runs, and corrected re-dumps without ever
double-counting or forking a decision.

The idempotency design (hardened against the plan's stress-test):

  * identity_key — what makes two raw items "the same item". Keyed off
    (source, channel, id, event_time). When an item has NO id (the round caught
    a message_id defaulting to "" collapsing every id-less message into one
    key), the content is folded IN, so distinct id-less messages stay distinct.
  * content_hash — what makes two versions of the same item "different". Stored
    separately so a corrected re-dump (same identity, new content) is a
    CORRECTION (retire + re-harvest), not a duplicate (skip).
  * two-phase markers — an item is `started` then `complete(derived_ids)`. A
    started-but-not-complete key (a crash mid-harvest) is RESUMED: its partial
    derived entries are retired and it re-harvests. Append-only markers alone
    couldn't record partial progress; this closes v1's fatal gap.

Single-writer (a personal agent, one process) is assumed — so the read-side
resolver's last-complete-wins dedup is sufficient; no lock needed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, Optional, Protocol

from .clock import TimeGround
from .ledger import Ledger

MARKER_KIND = "ingest_marker"


@dataclass(frozen=True)
class RawItem:
    """One unit of raw material from a source, before any understanding."""
    source: str                       # "discord" | "transcript" | "media" | ...
    channel: str                      # channel / meeting / file it belongs to
    content: str
    event_time: datetime              # the item's OWN timestamp (never now())
    item_id: str = ""                 # a real id if the source has one; may be absent
    kind: str = "message"             # "message" | "transcript" | "media_transcript"
    machine_transcribed: bool = False  # Whisper/ASR output — lower confidence, flagged loud
    meta: tuple = ()                  # (k, v) pairs; frozen-friendly

    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:16]

    def identity_key(self) -> str:
        """Stable identity of the ITEM (not its content, not its exact time).
        With a real id, the identity is (source, channel, id) ALONE — so a
        re-dump that corrects the text OR the timestamp still shares this key and
        is recognised as a correction (the adversary caught event_time in the
        hash making a time-corrected re-dump look brand-new). WITHOUT an id,
        time+content are folded in so two different id-less messages never
        collapse together."""
        if self.item_id:
            basis = [self.source, self.channel, self.item_id]
        else:
            basis = [self.source, self.channel, self.event_time.isoformat(), self.content]
        raw = "\x1f".join(basis)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Provenance:
    """What a harvested understanding rests on — carried into every observation
    so nothing about the world is asserted without a traceable, honest source.
    Propagates upward (a summary inherits the floor of its inputs)."""
    source_refs: tuple[str, ...]       # identity_keys the understanding rests on
    event_time: datetime               # when it (claims to have) happened
    machine_transcribed: bool = False  # any input was ASR → flagged
    event_time_reconstructed: bool = True   # the time is the transcript's claim, not truth
    transcript_fallible: bool = True   # the agent only had the words; they can be wrong

    def to_dict(self) -> dict:
        return {"source_refs": list(self.source_refs),
                "event_time": self.event_time.isoformat(),
                "machine_transcribed": self.machine_transcribed,
                "event_time_reconstructed": self.event_time_reconstructed,
                "transcript_fallible": self.transcript_fallible}

    @staticmethod
    def merge(parts: "Iterable[Provenance]", event_time: datetime) -> "Provenance":
        """Fold provenance upward WITHOUT laundering: the union of sources, and
        OR of the fallibility flags — so a confident summary can never be built
        out of shaky inputs without carrying the shakiness."""
        parts = list(parts)
        refs: list[str] = []
        for p in parts:
            for r in p.source_refs:
                if r not in refs:
                    refs.append(r)
        return Provenance(
            source_refs=tuple(refs), event_time=event_time,
            machine_transcribed=any(p.machine_transcribed for p in parts),
            event_time_reconstructed=any(p.event_time_reconstructed for p in parts),
            transcript_fallible=any(p.transcript_fallible for p in parts) or True)


class SourceAdapter(Protocol):
    """A source behind one interface. Real adapters (Atlas dumps, discord-read,
    media→audio-transcription) implement discover(); tests use a list."""
    def discover(self) -> Iterable[RawItem]: ...


# The harvester turns one raw item + its provenance into zero-or-more derived
# ledger entries, returning their ids. Phase B supplies the real one (observation
# + opinion nodes); Phase A is agnostic to what it does.
Harvester = Callable[[RawItem, Provenance], list]


@dataclass
class IngestResult:
    processed: int = 0
    skipped_duplicate: int = 0
    corrected: int = 0
    resumed: int = 0
    derived_total: int = 0


class Ingestor:
    """Feeds raw items through a harvester EXACTLY once, idempotently."""

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None,
                 author: str = "ingest"):
        self.ledger = ledger
        self.ground = ground or ledger.ground
        self.author = author

    # ----- marker resolution (last-complete-wins) ---------------------------

    def _markers(self) -> dict:
        """identity_key -> {'complete'|'started' marker body + entry id}, latest
        per key by write_time. Append-only; the resolver dedups at read time."""
        latest: dict = {}
        for e in self.ledger.entries():
            if e.kind != MARKER_KIND:
                continue
            k = e.body.get("identity_key")
            if not k:
                continue
            prev = latest.get(k)
            if prev is None or e.stamp.write_time >= prev["_wt"]:
                latest[k] = {**e.body, "_id": e.id, "_wt": e.stamp.write_time}
        return latest

    def status_of(self, item: RawItem) -> str:
        """'done' (same content), 'correction' (same id, new content),
        'resume' (started, never completed), or 'new'."""
        m = self._markers().get(item.identity_key())
        if m is None:
            return "new"
        if m.get("phase") == "started":
            return "resume"
        # phase == complete
        return "done" if m.get("content_hash") == item.content_hash() else "correction"

    # ----- the one-time feed -------------------------------------------------

    def ingest(self, items: Iterable[RawItem], harvester: Harvester,
               confidence_default: float = 0.6) -> IngestResult:
        res = IngestResult()
        for item in items:
            status = self.status_of(item)
            if status == "done":
                res.skipped_duplicate += 1
                continue

            # a correction or a resume must first retire the stale derived work
            if status in ("correction", "resume"):
                self._retire_prior_derived(item)
                if status == "correction":
                    res.corrected += 1
                else:
                    res.resumed += 1

            prov = Provenance(
                source_refs=(item.identity_key(),),
                event_time=item.event_time,
                machine_transcribed=item.machine_transcribed,
                event_time_reconstructed=(item.kind != "message"),
                transcript_fallible=True)

            # PHASE 1: started (so a crash after this is resumable)
            self.ledger.append(
                kind=MARKER_KIND, author=self.author,
                body={"identity_key": item.identity_key(), "phase": "started",
                      "content_hash": item.content_hash(), "source": item.source,
                      "channel": item.channel, "kind": item.kind},
                event_time=item.event_time, tags=("ingest", "started"))

            derived = harvester(item, prov) or []

            # PHASE 2: complete (records exactly which entries this item produced)
            self.ledger.append(
                kind=MARKER_KIND, author=self.author,
                body={"identity_key": item.identity_key(), "phase": "complete",
                      "content_hash": item.content_hash(),
                      "derived_ids": list(derived), "source": item.source,
                      "channel": item.channel, "kind": item.kind,
                      "machine_transcribed": item.machine_transcribed},
                event_time=item.event_time, tags=("ingest", "complete"))
            if status == "new":
                res.processed += 1
            res.derived_total += len(derived)
        return res

    def _retire_prior_derived(self, item: RawItem) -> None:
        """Retire (never delete) EVERY derived entry a prior harvest produced for
        this source item — so a correction or resume replaces cleanly instead of
        double-counting. Two sources of derived ids, because a crash mid-harvest
        (the adversary's HIGH) leaves entries the `started` marker never recorded:
          1. ids named by any marker's derived_ids, AND
          2. any entry whose provenance/`from` references this identity_key —
             which catches the partial, orphaned writes a crash left behind."""
        key = item.identity_key()
        targets: set = set()
        for m in self._all_markers_for(key):
            for did in m.get("derived_ids", []) or []:
                targets.add(did)
        for e in self.ledger.entries():
            prov = e.body.get("provenance") or {}
            if key in (prov.get("source_refs") or []) or e.body.get("from") == key:
                targets.add(e.id)
        already_retired = {r.body.get("retires") for r in self.ledger.entries()
                           if r.kind == self.ledger.RETIREMENT_KIND}
        for did in targets:
            if did not in already_retired and self.ledger.get(did) is not None:
                self.ledger.retire(did, self.author,
                                   reason="superseded by re-ingest/correction")

    def _all_markers_for(self, identity_key: str) -> list:
        return [e.body for e in self.ledger.entries()
                if e.kind == MARKER_KIND and e.body.get("identity_key") == identity_key]

    # ----- coverage (what we've understood — our truth, not Atlas's) ---------

    def coverage(self) -> dict:
        """A honest picture of what has been ingested: counts by source/channel,
        and how much rests on machine transcription."""
        markers = [m for m in self._markers().values() if m.get("phase") == "complete"]
        by_source: dict = {}
        machine = 0
        for m in markers:
            by_source[m.get("source", "?")] = by_source.get(m.get("source", "?"), 0) + 1
            if m.get("machine_transcribed"):
                machine += 1
        return {"items_ingested": len(markers), "by_source": by_source,
                "machine_transcribed": machine}
