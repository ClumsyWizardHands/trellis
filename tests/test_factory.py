"""providers/factory.py — config-driven model seat, fail LOUD, no silent mock."""

import pytest

from trellis.providers import provider_from_env, MockProvider, ProviderUnavailable


def _clear(monkeypatch):
    for k in ("TRELLIS_PROVIDER", "TRELLIS_LOCAL_BASE_URL", "TRELLIS_LOCAL_MODEL",
              "OPENAI_API_KEY", "TRELLIS_OPENAI_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_unset_provider_fails_loud(monkeypatch):
    _clear(monkeypatch)
    with pytest.raises(ProviderUnavailable, match="TRELLIS_PROVIDER is unset"):
        provider_from_env()


def test_mock_selected(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "mock")
    assert isinstance(provider_from_env(), MockProvider)


def test_local_missing_base_url_names_the_var(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "local")
    with pytest.raises(ProviderUnavailable, match="TRELLIS_LOCAL_BASE_URL"):
        provider_from_env()


def test_local_constructs_without_network(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "local")
    monkeypatch.setenv("TRELLIS_LOCAL_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("TRELLIS_LOCAL_MODEL", "gemma3")
    prov = provider_from_env()                 # construction must not hit the network
    assert "gemma3" in prov.id


def test_openai_missing_key_names_the_var(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "openai")
    with pytest.raises(ProviderUnavailable, match="OPENAI_API_KEY"):
        provider_from_env()


def test_unknown_provider_fails_loud(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "gpt9000")
    with pytest.raises(ProviderUnavailable, match="unknown TRELLIS_PROVIDER"):
        provider_from_env()
