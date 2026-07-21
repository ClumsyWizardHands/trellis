"""Go-live hardening (seat F): preflight honesty + turnkey demo.

Regression tests for Codex#14 (doctor honesty/crash), Codex#15 (openai_compat
preflight model-presence + malformed payloads), FableG14 (claude seat had no
preflight), and Codex#19 (demo repo-dependent + not re-runnable).

Each test reproduces the audit's stated repro and asserts the honest behavior.
"""

import argparse
import json

import pytest


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _doctor(monkeypatch, tmp_path, **env):
    """Run cmd_doctor in an isolated cwd with a clean, explicit environment."""
    from trellis import cli
    monkeypatch.chdir(tmp_path)
    for k in ("TRELLIS_PROVIDER", "TRELLIS_VAULT_PATH", "TRELLIS_DISCORD_TOKEN",
              "TRELLIS_APPROVER_SECRET", "TRELLIS_LEDGER", "TRELLIS_READ_SURFACES",
              "TRELLIS_ACT_SURFACES", "TRELLIS_LOCAL_BASE_URL", "TRELLIS_LOCAL_MODEL",
              "TRELLIS_MIN_CONTEXT", "OPENAI_API_KEY", "TRELLIS_OPENAI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return cli.cmd_doctor(argparse.Namespace())


class _FakeResp:
    """Minimal urlopen() context-manager stand-in returning a fixed body."""
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


# --------------------------------------------------------------------------- #
# Codex#14 — doctor honesty & no traceback
# --------------------------------------------------------------------------- #

def test_doctor_ledger_dot_fails_not_ready(monkeypatch, tmp_path, capsys):
    # TRELLIS_LEDGER=.  → the ledger path is a directory; Ledger(".") cannot
    # append. doctor must probe the real ledger and report NOT READY.
    rc = _doctor(monkeypatch, tmp_path, TRELLIS_LEDGER=".")
    assert rc == 1
    out = capsys.readouterr().out
    assert "✗" in out  # a FAIL line was printed for the ledger


def test_doctor_bad_min_context_no_traceback(monkeypatch, tmp_path, capsys):
    # TRELLIS_MIN_CONTEXT=not-an-int used to escape as an uncaught ValueError.
    rc = _doctor(
        monkeypatch, tmp_path,
        TRELLIS_LEDGER=str(tmp_path / "state/ledger.jsonl"),
        TRELLIS_PROVIDER="local",
        TRELLIS_LOCAL_BASE_URL="http://localhost:11434/v1",
        TRELLIS_LOCAL_MODEL="gemma3",
        TRELLIS_MIN_CONTEXT="not-an-int",
    )
    assert rc == 1  # normalized to a FAIL, not a traceback
    out = capsys.readouterr().out
    assert "TRELLIS_MIN_CONTEXT" in out


def test_doctor_discord_token_is_unverified_not_ok(monkeypatch, tmp_path, capsys):
    # A bogus token plus a read surface must NOT print "OK Discord read" — no
    # credential/reachability check ran, so the surface is UNVERIFIED.
    _doctor(
        monkeypatch, tmp_path,
        TRELLIS_LEDGER=str(tmp_path / "state/ledger.jsonl"),
        TRELLIS_DISCORD_TOKEN="bogus-token",
        TRELLIS_READ_SURFACES="chiefs",
    )
    out = capsys.readouterr().out
    discord_lines = [ln for ln in out.splitlines() if "Discord" in ln]
    assert discord_lines
    assert not any("✓" in ln for ln in discord_lines)  # never claims OK
    assert any("UNVERIFIED" in ln for ln in discord_lines)


# --------------------------------------------------------------------------- #
# Codex#15 — openai_compat preflight
# --------------------------------------------------------------------------- #

def _provider(model="configured-model"):
    from trellis.providers.openai_compat import OpenAICompatProvider
    return OpenAICompatProvider(base_url="http://localhost:11434/v1",
                                model=model, api_key="secret-key-xyz")

def test_preflight_absent_model_is_not_ready(monkeypatch):
    from trellis.providers import ProviderUnavailable
    from trellis.providers import openai_compat
    body = json.dumps({"data": [{"id": "other-model"}]}).encode()
    monkeypatch.setattr(openai_compat.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp(body))
    prov = _provider("configured-missing")
    with pytest.raises(ProviderUnavailable, match="configured-missing"):
        prov.preflight()


def test_preflight_present_model_ok(monkeypatch):
    from trellis.providers import openai_compat
    body = json.dumps({"data": [{"id": "configured-model"}]}).encode()
    monkeypatch.setattr(openai_compat.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp(body))
    info = prov = _provider("configured-model").preflight()
    assert info["ok"] is True


def test_preflight_malformed_payload_normalized_no_secret(monkeypatch):
    from trellis.providers import ProviderUnavailable
    from trellis.providers import openai_compat
    # Valid HTTP 200 JSON but the wrong shape (a list, not the {"data": [...]}).
    body = json.dumps(["not", "the", "expected", "shape"]).encode()
    monkeypatch.setattr(openai_compat.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp(body))
    prov = _provider("configured-model")
    with pytest.raises(ProviderUnavailable) as ei:
        prov.preflight()
    assert "secret-key-xyz" not in str(ei.value)  # never leaks the credential


# --------------------------------------------------------------------------- #
# FableG14 — the claude seat had no preflight
# --------------------------------------------------------------------------- #

def _claude_provider():
    # Bypass __init__ (which requires the optional SDK) to unit-test preflight.
    from trellis.providers.claude_sdk import ClaudeSDKProvider
    prov = ClaudeSDKProvider.__new__(ClaudeSDKProvider)
    prov.id = "claude-sdk:test"
    prov.model = "claude-sonnet-4-5"
    return prov


def test_claude_preflight_missing_key_fails(monkeypatch):
    from trellis.providers import ProviderUnavailable
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable, match="ANTHROPIC_API_KEY"):
        _claude_provider().preflight()


def test_claude_preflight_malformed_key_fails(monkeypatch):
    from trellis.providers import ProviderUnavailable
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    with pytest.raises(ProviderUnavailable):
        _claude_provider().preflight()


def test_claude_preflight_wellformed_key_ok(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc123def456")
    info = _claude_provider().preflight()
    assert info["ok"] is True


# --------------------------------------------------------------------------- #
# Codex#19 — the demo must run outside the checkout and more than once
# --------------------------------------------------------------------------- #

def test_demo_runs_twice_from_a_bare_cwd(monkeypatch, tmp_path, capsys):
    # A directory with no examples/ (mimics an installed package). The demo must
    # succeed twice without a CollidingDecisionError on the second run.
    from trellis import cli
    monkeypatch.chdir(tmp_path)
    rc1 = cli.cmd_demo(argparse.Namespace(fresh=False))
    rc2 = cli.cmd_demo(argparse.Namespace(fresh=False))
    assert rc1 == 0
    assert rc2 == 0
    out = capsys.readouterr().out
    assert "witness cycle" in out


def test_demo_fresh_flag(monkeypatch, tmp_path):
    from trellis import cli
    monkeypatch.chdir(tmp_path)
    assert cli.cmd_demo(argparse.Namespace(fresh=True)) == 0
