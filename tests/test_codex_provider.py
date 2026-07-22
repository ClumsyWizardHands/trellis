"""The OpenAI seat via the official Codex CLI (subscription, no API key).

trellis drives `codex login status` / `codex exec` and never touches the Codex
credential. All subprocess calls are mocked here — no network, no real codex run.
"""

import subprocess
import types

import pytest

from trellis.providers import ProviderUnavailable


def _provider(monkeypatch, *, installed=True):
    import trellis.providers.codex as cx
    monkeypatch.setattr(cx.shutil, "which", lambda _b: "/usr/bin/codex" if installed else None)
    return cx


def test_missing_codex_binary_fails_loud(monkeypatch):
    cx = _provider(monkeypatch, installed=False)
    with pytest.raises(ProviderUnavailable, match="Codex CLI"):
        cx.CodexProvider()


def _fake_run(monkeypatch, cx, *, status_rc=0, status_out="Logged in using ChatGPT",
              exec_rc=0, last_message="THE OPINION", stderr=""):
    calls = {}

    def fake_run(cmd, **kw):
        if cmd[:3] == [cx_bin, "login", "status"] if (cx_bin := cmd[0]) else False:
            return types.SimpleNamespace(returncode=status_rc, stdout=status_out, stderr="")
        # codex exec — write the last-message file the provider will read
        if "exec" in cmd:
            calls["exec_cmd"] = cmd
            if "--output-last-message" in cmd:
                path = cmd[cmd.index("--output-last-message") + 1]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(last_message)
            return types.SimpleNamespace(returncode=exec_rc, stdout="", stderr=stderr)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cx.subprocess, "run", fake_run)
    return calls


def test_preflight_logged_in_chatgpt_subscription(monkeypatch):
    cx = _provider(monkeypatch)
    _fake_run(monkeypatch, cx, status_out="Logged in using ChatGPT")
    info = cx.CodexProvider().preflight()
    assert info["ok"] is True and info["auth"] == "chatgpt_subscription"


def test_preflight_logged_in_api_key(monkeypatch):
    cx = _provider(monkeypatch)
    _fake_run(monkeypatch, cx, status_out="Logged in using an API key")
    info = cx.CodexProvider().preflight()
    assert info["ok"] is True and info["auth"] == "api_key"


def test_preflight_not_logged_in_points_at_codex_login(monkeypatch):
    cx = _provider(monkeypatch)
    _fake_run(monkeypatch, cx, status_rc=1, status_out="Not logged in")
    with pytest.raises(ProviderUnavailable, match="codex login"):
        cx.CodexProvider().preflight()


def test_complete_returns_the_agents_last_message(monkeypatch):
    cx = _provider(monkeypatch)
    calls = _fake_run(monkeypatch, cx, last_message="Y — the framing holds")
    resp = cx.CodexProvider(model="gpt-5-codex").complete(
        system="you are the witness", messages=[{"role": "user", "content": "the july pricing"}])
    assert resp.text == "Y — the framing holds"
    # sandboxed + ephemeral + read-only + model passed through, prompt via stdin
    cmd = calls["exec_cmd"]
    for flag in ("--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check"):
        assert flag in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-5-codex"
    assert cmd[-1] == "-"


def test_complete_failure_with_no_message_raises(monkeypatch):
    cx = _provider(monkeypatch)
    _fake_run(monkeypatch, cx, exec_rc=1, last_message="", stderr="auth error")
    with pytest.raises(ProviderUnavailable, match="codex exec"):
        cx.CodexProvider().complete(system="", messages=[{"role": "user", "content": "hi"}])


def test_factory_builds_codex_seat(monkeypatch):
    _provider(monkeypatch)  # pretend codex installed
    monkeypatch.setenv("TRELLIS_PROVIDER", "codex")
    from trellis.providers.factory import provider_from_env, VALID
    assert "codex" in VALID
    prov = provider_from_env()
    assert prov.id.startswith("codex")
