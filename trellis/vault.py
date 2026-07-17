"""vault.py — the Obsidian vault as the navigable face of the ledger, reconciled.

Phase B. The vault IS the memory-as-navigation `Workspace`, rooted at your
Obsidian vault directory. The markdown files hold the content; the ledger holds
the events (with a content hash per write). They are ONE store with two faces —
and, crucially, their divergence is DETECTABLE and HEALABLE, because v1 wrongly
claimed the vault was reconstructable from the ledger alone (it stored only a
byte-count) and left retirement/supersession to silently disagree with the files.

This module supplies the reconciliation the plan's stress-test demanded:

  * note_state() computes a note's status (live / retired / superseded) and its
    provenance FROM THE LEDGER at read time — so frontmatter is never a frozen,
    stale id; a decision retired in the ledger shows `retired` in its note.
  * detect_drift() finds where the files and the ledger disagree — most
    importantly, a note a HUMAN edited in Obsidian (its content hash no longer
    matches the recorded one).
  * reconcile() heals: a human edit is folded in as an ATTRIBUTED write (it joins
    the lineage instead of being clobbered or lost); anything it cannot heal is
    SURFACED, not papered over.

Frontmatter carries the stable question identity (not a frozen entry id) plus the
current head; wikilinks express lineage (obs <-> op, up to the EMP node).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from .clock import TimeGround
from .ledger import Ledger
from .memory import Workspace


def hash_content(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def note_state(ledger: Ledger, decision_id: str) -> dict:
    """A decision's live status, computed FROM THE LEDGER (never a frozen note
    field): live / superseded / retired, plus the current head id, confidence,
    and provenance. This is what keeps frontmatter honest after a fold or a
    retirement — the note reflects the record, not a stale snapshot."""
    entry = ledger.get(decision_id)
    if entry is None:
        return {"status": "unknown", "head_id": None}
    qk = entry.body.get("question_key")
    # is it the active head for its question, or superseded / retired?
    active = {e.id: e for e in ledger.active("decision")}
    head = next((e for e in active.values() if e.body.get("question_key") == qk), None)
    if head is None:
        status = "retired"          # not in the active set and nothing replaced it as head
        head_id = None
    elif head.id == entry.id:
        status = "live"
        head_id = entry.id
    else:
        status = "superseded"
        head_id = head.id
    return {"status": status, "head_id": head_id,
            "confidence": entry.body.get("confidence"),
            "provenance": entry.body.get("provenance"),
            "attributed_to": entry.body.get("attributed_to"),
            "question_key": qk}


def render_frontmatter(ledger: Ledger, decision_id: str) -> str:
    """Obsidian YAML frontmatter for a decision note — status/head computed live."""
    st = note_state(ledger, decision_id)
    lines = ["---", f"question_key: {st.get('question_key')}",
             f"status: {st.get('status')}", f"head: {st.get('head_id')}"]
    if st.get("confidence") is not None:
        lines.append(f"confidence: {st['confidence']}")
    prov = st.get("provenance") or {}
    if prov:
        lines.append(f"machine_transcribed: {prov.get('machine_transcribed', False)}")
        lines.append(f"transcript_fallible: {prov.get('transcript_fallible', True)}")
        if prov.get("source_refs"):
            lines.append("source_refs: [" + ", ".join(prov["source_refs"]) + "]")
    if st.get("attributed_to"):
        lines.append("attributed_to: [" + ", ".join(st["attributed_to"]) + "]")
    lines.append("---")
    return "\n".join(lines)


@dataclass
class Drift:
    path: str
    kind: str            # "human_edit" | "missing_file"
    detail: str = ""


@dataclass
class ReconcileReport:
    healed_human_edits: list = field(default_factory=list)   # paths folded back in
    surfaced: list = field(default_factory=list)             # Drifts we could not heal

    @property
    def clean(self) -> bool:
        return not self.healed_human_edits and not self.surfaced


class VaultReconciler:
    """Keeps the vault (markdown) and the ledger (events) honest with each other."""

    def __init__(self, workspace: Workspace, ledger: Optional[Ledger] = None):
        self.ws = workspace
        self.ledger = ledger or workspace.ledger

    def detect_drift(self) -> list:
        """Every way the files and the ledger currently disagree."""
        drifts = []
        for e in self.ledger.active(self.ws.MEMORY_KIND):
            rel = e.body.get("path")
            recorded = e.body.get("content_hash")
            path = self.ws.root / rel
            if not path.exists():
                drifts.append(Drift(rel, "missing_file",
                                    "the ledger has this note but the file is gone"))
                continue
            if recorded is not None:
                actual = hash_content(path.read_text(encoding="utf-8"))
                if actual != recorded:
                    drifts.append(Drift(rel, "human_edit",
                                        "the file was edited outside the harness "
                                        "(hash no longer matches the record)"))
        return drifts

    def reconcile(self, author: str = "human:obsidian") -> ReconcileReport:
        """Heal what can be healed; surface what can't. A human edit in Obsidian
        is FOLDED IN as an attributed write — the edit joins the lineage (the old
        body goes to .history, a new memory_write supersedes) instead of being
        clobbered on the next harness write or lost. A missing file is surfaced,
        never silently re-created."""
        report = ReconcileReport()
        for d in self.detect_drift():
            if d.kind == "human_edit":
                current = self.ws.read(d.path)
                # find the title so the fold keeps it findable
                prior = next((e for e in self.ledger.active(self.ws.MEMORY_KIND)
                              if e.body.get("path") == d.path), None)
                title = prior.body.get("title") if prior else None
                self.ws.write(
                    d.path, current, author,
                    synthesis_justification=(
                        "a human edited this note directly in Obsidian; folding "
                        "their change onto the record so it joins the lineage "
                        "rather than being clobbered or lost"),
                    title=title)
                report.healed_human_edits.append(d.path)
            else:
                report.surfaced.append(d)   # missing_file etc. — for the Curiosities board
        return report
