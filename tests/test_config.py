"""config.py — the zero-dep .env loader + fail-loud accessors."""

import pytest

from trellis import config


def test_load_dotenv_parses_and_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "TRELLIS_HUMAN=alex\n"
        'export TRELLIS_OPENAI_MODEL="gpt-5.5"\n'
        "TRELLIS_LOCAL_MODEL='gemma3'\n"
        "\n"
        "MALFORMED_NO_EQUALS\n",
        encoding="utf-8")
    monkeypatch.setenv("TRELLIS_HUMAN", "already-set")   # must NOT be overwritten
    monkeypatch.delenv("TRELLIS_OPENAI_MODEL", raising=False)
    parsed = config.load_dotenv(env)
    assert parsed["TRELLIS_OPENAI_MODEL"] == "gpt-5.5"     # quotes stripped
    assert parsed["TRELLIS_LOCAL_MODEL"] == "gemma3"       # export + quotes stripped
    assert "MALFORMED_NO_EQUALS" not in parsed
    import os
    assert os.environ["TRELLIS_OPENAI_MODEL"] == "gpt-5.5"  # loaded into env
    assert os.environ["TRELLIS_HUMAN"] == "already-set"     # NOT overridden


def test_load_dotenv_missing_file_is_empty(tmp_path):
    assert config.load_dotenv(tmp_path / "nope.env") == {}


def test_load_dotenv_honors_TRELLIS_ENV_FILE_override(tmp_path, monkeypatch):
    # A caller (and the test suite) can redirect the default path so a real ./.env
    # is never picked up — the isolation that keeps a developer's local config
    # from silently changing behavior (it once turned every login test into a 422).
    real = tmp_path / "real.env"
    real.write_text("TRELLIS_FROM_REAL=yes\n", encoding="utf-8")
    monkeypatch.setenv("TRELLIS_ENV_FILE", str(tmp_path / "does-not-exist.env"))
    monkeypatch.delenv("TRELLIS_FROM_REAL", raising=False)
    assert config.load_dotenv() == {}                 # default path → the override → nothing
    assert config.load_dotenv(real) == {"TRELLIS_FROM_REAL": "yes"}   # explicit path still works


def test_require_fails_loud(monkeypatch):
    monkeypatch.delenv("TRELLIS_NOPE", raising=False)
    with pytest.raises(config.ConfigError, match="TRELLIS_NOPE"):
        config.require("TRELLIS_NOPE", hint="set it")


def test_typed_accessors(monkeypatch):
    monkeypatch.delenv("TRELLIS_VAULT_PATH", raising=False)
    monkeypatch.delenv("TRELLIS_PROVIDER", raising=False)
    assert config.ledger_path() == "state/ledger.jsonl"
    assert config.vault_path() is None
    assert config.provider_kind() is None
    monkeypatch.setenv("TRELLIS_PROVIDER", "  LOCAL  ")
    assert config.provider_kind() == "local"              # normalized
