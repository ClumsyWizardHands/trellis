"""Phase B — the vault as the reconciled face of the ledger.

Pins the stress-test's vault/ledger findings: a content hash makes drift
detectable; a human edit in Obsidian is folded in (attributed), not clobbered;
a note's status is computed live from the ledger, never a stale frozen field."""

from datetime import timedelta

from trellis.decisions import Decision, DecisionLog, Verdict
from trellis.memory import Workspace
from trellis.vault import VaultReconciler, note_state, render_frontmatter

GOODJ = ("this synthesized read exists nowhere else in this form and cannot be "
         "re-derived mechanically from the transcripts")


def test_write_records_a_content_hash(tmp_path, ledger):
    ws = Workspace(tmp_path / "v", ledger)
    ws.write("reads/a.md", "# The read\nbody", "witness", GOODJ, title="The read")
    e = ledger.active("memory_write")[0]
    assert e.body["content_hash"] and len(e.body["content_hash"]) == 16


def test_detects_a_human_edit_in_obsidian(tmp_path, ledger):
    ws = Workspace(tmp_path / "v", ledger)
    ws.write("reads/a.md", "original synthesized read", "witness", GOODJ, title="Read")
    rec = VaultReconciler(ws)
    assert rec.detect_drift() == []
    # simulate the human opening Obsidian and editing the note directly
    (ws.root / "reads/a.md").write_text("original read + a human's correction",
                                        encoding="utf-8")
    drift = rec.detect_drift()
    assert len(drift) == 1 and drift[0].kind == "human_edit"


def test_reconcile_folds_the_human_edit_into_the_lineage(tmp_path, ledger):
    ws = Workspace(tmp_path / "v", ledger)
    ws.write("reads/a.md", "v1 by the agent", "witness", GOODJ, title="Read")
    (ws.root / "reads/a.md").write_text("v2 edited by Alex in Obsidian", encoding="utf-8")
    report = VaultReconciler(ws).reconcile(author="human:alex")
    assert report.healed_human_edits == ["reads/a.md"]
    # the human's edit is now ON THE RECORD, attributed to them, and joins the
    # lineage — so a later harness write folds onto it instead of clobbering it,
    # and drift is gone. (v1's TEXT was externally overwritten by the human
    # before we ever saw it — only the vault's git history holds it; the ledger
    # keeps its hash. The harness can't resurrect an out-of-band overwrite, and
    # doesn't pretend to.)
    writes = [e for e in ledger.entries() if e.kind == "memory_write"]
    assert len(writes) == 2 and writes[-1].author == "human:alex"
    assert writes[-1].body["content_hash"] != writes[0].body["content_hash"]
    assert writes[-1].supersedes == writes[0].id       # it joined the lineage
    assert VaultReconciler(ws).detect_drift() == []    # reconciled


def test_missing_file_is_surfaced_not_silently_recreated(tmp_path, ledger):
    ws = Workspace(tmp_path / "v", ledger)
    ws.write("reads/gone.md", "content", "witness", GOODJ, title="Read")
    (ws.root / "reads/gone.md").unlink()
    report = VaultReconciler(ws).reconcile()
    assert not report.healed_human_edits
    assert len(report.surfaced) == 1 and report.surfaced[0].kind == "missing_file"


def test_note_state_reflects_retirement_live_from_the_ledger(ledger):
    log = DecisionLog(ledger)
    d = log.record(Decision("Ship on Friday", Verdict.N, "not ready", "witness", "EMP:e[0]"))
    did = d.body["decision_id"]
    assert note_state(ledger, d.id)["status"] == "live"
    ledger.retire(d.id, "alex", reason="the team reversed it")
    assert note_state(ledger, d.id)["status"] == "retired"


def test_frontmatter_carries_provenance_and_status(ledger):
    log = DecisionLog(ledger)
    d = log.record(Decision(
        "Adopt the framing", Verdict.Y, "room converged", "observer:witness",
        "EMP:ends[0]", key="obs:abc123", attributed_to=["brett", "alex"],
        confidence=0.7, provenance={"machine_transcribed": True,
                                    "transcript_fallible": True, "source_refs": ["k1"]}))
    fm = render_frontmatter(ledger, d.id)
    assert "status: live" in fm and "confidence: 0.7" in fm
    assert "machine_transcribed: True" in fm and "attributed_to: [brett, alex]" in fm
