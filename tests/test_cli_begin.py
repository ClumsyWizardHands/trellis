"""test_cli_begin.py — `trellis begin` (the initialize command) + doctor honesty.

Pins: a 'no' at the consent prompt reads NOTHING and is on the record; a 'yes'
runs a real first pass and writes the map; `--once` does not go resident; the
doctor reports the Google surface as wired-awaiting-grant, never READY.
"""

from __future__ import annotations

from pathlib import Path

from trellis.cli import main
from trellis.ledger import Ledger
from trellis.onboard import CONSENT_KIND, PASS_KIND, consent_state


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRELLIS_LEDGER", str(tmp_path / "state" / "ledger.jsonl"))
    monkeypatch.setenv("TRELLIS_HUMAN", "alex")
    for var in ("TRELLIS_PROVIDER", "TRELLIS_VERIFIER_PROVIDER",
                "TRELLIS_DISCORD_TOKEN", "TRELLIS_READ_SURFACES",
                "TRELLIS_ACT_SURFACES", "TRELLIS_VAULT_PATH",
                "TRELLIS_TRANSCRIPTS_DIR", "TRELLIS_DRIVE_FOLDER",
                "TRELLIS_GOOGLE_TOKEN_STORE", "TRELLIS_GOOGLE_CLIENT_SECRET",
                "TRELLIS_ONBOARD_TERMS"):
        monkeypatch.delenv(var, raising=False)


def test_begin_no_records_the_decline_and_reads_nothing(monkeypatch, tmp_path,
                                                        capsys):
    _env(monkeypatch, tmp_path)
    rc = main(["begin", "--once", "--answer", "no"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "May I begin?" in out
    assert "won't read anything" in out
    ledger = Ledger(tmp_path / "state" / "ledger.jsonl")
    assert consent_state(ledger) == "declined"        # the no is a durable fact
    assert not any(e.kind == PASS_KIND for e in ledger.entries())
    assert not (tmp_path / "state" / "workspace").exists()   # nothing mapped


def test_begin_yes_runs_a_real_first_pass(monkeypatch, tmp_path, capsys):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("TRELLIS_ONBOARD_TERMS", "empire")
    rc = main(["begin", "--once", "--answer", "yes"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "learning pass: ran" in out
    assert "open unknowns" in out
    ledger = Ledger(tmp_path / "state" / "ledger.jsonl")
    assert consent_state(ledger) == "granted"
    passes = [e for e in ledger.entries() if e.kind == PASS_KIND]
    assert passes and passes[-1].body["status"] == "ran"
    # the map exists beside the ledger (no vault configured)
    ws = tmp_path / "state" / "workspace"
    assert (ws / "map" / "README.md").is_file()
    assert (ws / "map" / "unknowns.md").is_file()
    # the seeded term is an open curiosity, honestly unresolved (no evidence yet)
    assert "empire" in (ws / "map" / "unknowns.md").read_text(encoding="utf-8")


def test_begin_resumes_without_reasking(monkeypatch, tmp_path, capsys):
    _env(monkeypatch, tmp_path)
    main(["begin", "--once", "--answer", "yes"])
    capsys.readouterr()
    rc = main(["begin", "--once", "--answer", "IGNORED"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "already on the record" in out             # consent asked exactly once
    ledger = Ledger(tmp_path / "state" / "ledger.jsonl")
    consents = [e for e in ledger.entries() if e.kind == CONSENT_KIND]
    assert len(consents) == 1


def test_begin_stages_the_introduction_never_fires(monkeypatch, tmp_path, capsys):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("TRELLIS_ACT_SURFACES", "chan-armed")
    rc = main(["begin", "--once", "--answer", "yes"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "STAGED" in out and "nothing has been sent" in out
    ledger = Ledger(tmp_path / "state" / "ledger.jsonl")
    staged = [e for e in ledger.entries() if e.kind == "staged_action"]
    assert staged and "May I begin?" in staged[-1].body["content"]
    assert staged[-1].body["status"] == "staged"
    # stage-don't-fire: no approval, no firing, no send happened
    assert not any("fir" in e.kind for e in ledger.entries())


def test_multiple_source_folders_are_each_wired_and_honestly_kinded(
        monkeypatch, tmp_path, capsys):
    """Atlas's real estate has several transcript folders, docs libraries, and
    Drive folders — every one becomes its own adapter, and a docs folder's
    items are kind=document, not falsely kind=transcript."""
    _env(monkeypatch, tmp_path)
    t1 = tmp_path / "transcripts-a"; t1.mkdir()
    (t1 / "2026-07-01 sync.md").write_text("the overnight soak", encoding="utf-8")
    t2 = tmp_path / "transcripts-b"; t2.mkdir()
    (t2 / "standup.txt").write_text("empire notes", encoding="utf-8")
    docs = tmp_path / "principles"; docs.mkdir()
    (docs / "pc-00.md").write_text("the wall", encoding="utf-8")
    monkeypatch.setenv("TRELLIS_TRANSCRIPTS_DIR", f"{t1},{t2}")
    monkeypatch.setenv("TRELLIS_DOCS_DIRS", str(docs))
    monkeypatch.setenv("TRELLIS_DRIVE_FOLDER", "folder-a,folder-b")

    rc = main(["begin", "--once", "--answer", "yes"])
    assert rc == 0
    ledger = Ledger(tmp_path / "state" / "ledger.jsonl")
    passes = [e for e in ledger.entries() if e.kind == PASS_KIND]
    ingested = passes[-1].body["ingested"]
    # one summary key per adapter — folders never collapse onto one line
    local_keys = [k for k in ingested if "TranscriptFolderAdapter" in k]
    assert len(local_keys) == 3
    # the two Drive folders are wired and honestly report awaiting-grant
    awaiting = passes[-1].body["awaiting"]
    assert len([a for a in awaiting if a["source"].startswith("GoogleDrive")]) == 2
    # docs land as kind=document; transcripts as kind=transcript
    docs_entries = [e for e in ledger.entries() if e.kind == "source_document"]
    kinds = {e.body["title"]: e.body["kind"] for e in docs_entries}
    assert kinds["pc-00"] == "document"
    assert kinds["2026-07-01 sync"] == "transcript"


def test_confirm_command_closes_the_curiosity(monkeypatch, tmp_path, capsys):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("TRELLIS_ONBOARD_TERMS", "empire")
    main(["begin", "--once", "--answer", "yes"])
    capsys.readouterr()
    rc = main(["confirm", "empire",
               "the whole tended system of people and agents"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "confidence 0.95" in out
    from trellis.curiosity import QuestionLog
    ledger = Ledger(tmp_path / "state" / "ledger.jsonl")
    open_terms = [q for q in QuestionLog(ledger).open_questions()
                  if "empire" in q.body.get("assumption", "")]
    assert open_terms == []                          # the human's word closed it


def test_doctor_reports_google_awaiting_grant(monkeypatch, tmp_path, capsys):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("TRELLIS_DRIVE_FOLDER", "folder-123")
    monkeypatch.setenv("TRELLIS_GOOGLE_TOKEN_STORE", str(tmp_path / "tok.json"))
    monkeypatch.chdir(tmp_path)
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0                                    # awaiting-grant is not a FAIL
    assert "wired, awaiting the human's grant" in out


def test_doctor_reports_onboarding_state(monkeypatch, tmp_path, capsys):
    _env(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["begin", "--once", "--answer", "yes"])
    capsys.readouterr()
    main(["doctor"])
    out = capsys.readouterr().out
    assert "consent granted" in out
