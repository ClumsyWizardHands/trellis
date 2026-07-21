"""cli.py — init/doctor turnkey, zip-safe, offline."""

import argparse
import os

from trellis import cli


def _run(cmd, monkeypatch, tmp_path, **env):
    monkeypatch.chdir(tmp_path)
    for k in ("TRELLIS_PROVIDER", "TRELLIS_VAULT_PATH", "TRELLIS_DISCORD_TOKEN",
              "TRELLIS_APPROVER_SECRET", "TRELLIS_LEDGER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return cmd(argparse.Namespace())


def test_init_scaffolds_env_and_state(monkeypatch, tmp_path):
    (tmp_path / ".env.example").write_text(
        "TRELLIS_HUMAN=operator\nTRELLIS_APPROVER_SECRET=\nTRELLIS_PROVIDER=mock\n",
        encoding="utf-8")
    rc = _run(cli.cmd_init, monkeypatch, tmp_path)
    assert rc == 0
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TRELLIS_APPROVER_SECRET=" in env
    # a real secret was generated (the line is no longer blank)
    secret_line = [l for l in env.splitlines() if l.startswith("TRELLIS_APPROVER_SECRET=")][0]
    assert len(secret_line.split("=", 1)[1]) > 20
    assert (tmp_path / "state").is_dir()


def test_init_never_overwrites_existing_env(monkeypatch, tmp_path):
    (tmp_path / ".env.example").write_text("TRELLIS_APPROVER_SECRET=\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TRELLIS_APPROVER_SECRET=mine-keep-it\n", encoding="utf-8")
    rc = _run(cli.cmd_init, monkeypatch, tmp_path)
    assert rc == 0
    assert "mine-keep-it" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_doctor_all_unconfigured_is_ready_not_failed(monkeypatch, tmp_path):
    # no .env, nothing configured → everything SKIPs, core checks pass → exit 0
    rc = _run(cli.cmd_doctor, monkeypatch, tmp_path, TRELLIS_LEDGER=str(tmp_path / "state/ledger.jsonl"))
    assert rc == 0


def test_doctor_mock_provider_ok(monkeypatch, tmp_path):
    rc = _run(cli.cmd_doctor, monkeypatch, tmp_path,
              TRELLIS_PROVIDER="mock",
              TRELLIS_LEDGER=str(tmp_path / "state/ledger.jsonl"))
    assert rc == 0


def test_doctor_flags_bad_vault(monkeypatch, tmp_path):
    rc = _run(cli.cmd_doctor, monkeypatch, tmp_path,
              TRELLIS_VAULT_PATH="/no/such/parent/xyz/vault",
              TRELLIS_LEDGER=str(tmp_path / "state/ledger.jsonl"))
    assert rc == 1   # a configured-but-broken surface fails loudly
