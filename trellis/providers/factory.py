"""providers/factory.py — pick the model seat from configuration, fail LOUD.

`TRELLIS_PROVIDER` selects the backend; each branch reads its own vars and raises
`ProviderUnavailable` naming the exact missing one. There is NO silent fallback to
Mock — a misconfigured seat is a loud error, because a silently-degraded auxiliary
model is a recorded failure mode (D11). Adapters are imported lazily inside their
branch, so importing this module drags in no vendor code and needs no extra.

Backends:
  mock    — deterministic, offline, no accounts (the safe default for a fresh clone)
  local   — any OpenAI-compatible endpoint: Ollama / LM Studio / llama.cpp / vLLM
            (this is the Gemma seat) — stdlib only
  openai  — hosted OpenAI with an API key — stdlib only
  claude  — the Claude Agent SDK seat — needs `pip install 'trellis-harness[claude]'`

Not yet: `openai-oauth` (ChatGPT/OpenAI subscription login). It rides undocumented
endpoints and carries ToS risk; use `openai` (API key) or `local` for now. See
docs/SETUP.md.
"""

from __future__ import annotations

import os
from typing import Optional

from .base import Provider, ProviderUnavailable
from .mock import MockProvider

VALID = ("mock", "local", "openai", "claude", "codex")

#: same family, cheaper seat (D34): the verifier defaults to a Haiku-class model
#: on the same backend as the Opus-class maker.
_VERIFIER_DEFAULT_MODEL = {"claude": "claude-haiku-4-5"}


class VerifierSeatError(ProviderUnavailable):
    """The configured verifier seat is not independent of the maker (D4/D34).
    A self-audit is not an audit — even the model SEAT must differ, not just the
    agent id. Subclasses ProviderUnavailable so it is caught by the same loud
    boundary, but is distinguishable when a caller wants to name the collision."""


def _require(name: str, hint: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise ProviderUnavailable(f"TRELLIS_PROVIDER needs {name} — {hint}")
    return v


def provider_from_env() -> Provider:
    """Construct the configured model seat. Raises ProviderUnavailable (loud) if
    unset, misconfigured, or unknown — never silently returns Mock."""
    kind = os.environ.get("TRELLIS_PROVIDER", "").strip().lower()
    if not kind:
        raise ProviderUnavailable(
            "TRELLIS_PROVIDER is unset. Refusing to guess a model seat. Set it to "
            f"one of: {', '.join(VALID)} (see docs/SETUP.md).")

    if kind == "mock":
        return MockProvider()

    if kind == "local":
        from .openai_compat import OpenAICompatProvider
        base = _require("TRELLIS_LOCAL_BASE_URL",
                        "e.g. http://localhost:11434/v1 for Ollama")
        model = _require("TRELLIS_LOCAL_MODEL", "e.g. gemma3")
        key = os.environ.get("TRELLIS_LOCAL_API_KEY", "not-needed")
        raw_ctx = os.environ.get("TRELLIS_MIN_CONTEXT", "16000").strip()
        try:
            min_ctx = int(raw_ctx)
        except ValueError as e:
            # A malformed numeric config is a loud ProviderUnavailable, not an
            # uncaught ValueError traceback out of doctor (Codex#14).
            raise ProviderUnavailable(
                f"TRELLIS_MIN_CONTEXT must be an integer, got {raw_ctx!r}.") from e
        return OpenAICompatProvider(base_url=base, model=model,
                                    api_key=key, min_context=min_ctx)

    if kind == "openai":
        from .openai_compat import OpenAICompatProvider
        key = _require("OPENAI_API_KEY", "your OpenAI API key (sk-...)")
        model = _require("TRELLIS_OPENAI_MODEL", "e.g. gpt-5.5")
        base = os.environ.get("TRELLIS_OPENAI_BASE_URL", "https://api.openai.com/v1")
        return OpenAICompatProvider(base_url=base, model=model, api_key=key)

    if kind == "claude":
        # ClaudeSDKProvider.__init__ raises ProviderUnavailable if the SDK is absent.
        from .claude_sdk import ClaudeSDKProvider
        model = os.environ.get("TRELLIS_CLAUDE_MODEL", "claude-sonnet-4-5")
        return ClaudeSDKProvider(model=model)

    if kind == "codex":
        # OpenAI on your ChatGPT SUBSCRIPTION via the official Codex CLI (no API
        # key). CodexProvider.__init__ raises if `codex` isn't installed; its
        # preflight detects `codex login`. trellis never handles the credential.
        from .codex import CodexProvider
        model = os.environ.get("TRELLIS_CODEX_MODEL", "").strip() or None
        return CodexProvider(model=model)

    raise ProviderUnavailable(
        f"unknown TRELLIS_PROVIDER={kind!r}. Valid: {', '.join(VALID)}.")


def _build_verifier_seat(kind: str, model: str) -> Provider:
    """Construct the verifier backend. `model` is the verifier-specific (cheaper)
    model; connection vars (base url / key) are shared with the maker seat since
    D34 keeps the SAME family — only the model differs. Imports lazily like the
    maker branches, so importing this module drags in no vendor code."""
    if kind == "mock":
        # the mock seat carries the verifier model in its id, so a distinct
        # verifier model reads as a distinct SEAT (two 'mock's are the same seat).
        return MockProvider(id=f"mock:{model}" if model else "mock")

    if kind == "local":
        from .openai_compat import OpenAICompatProvider
        base = _require("TRELLIS_LOCAL_BASE_URL",
                        "e.g. http://localhost:11434/v1 for Ollama")
        m = model or _require("TRELLIS_VERIFIER_MODEL",
                              "the cheaper verifier model, e.g. gemma3:2b")
        key = os.environ.get("TRELLIS_LOCAL_API_KEY", "not-needed")
        return OpenAICompatProvider(base_url=base, model=m, api_key=key)

    if kind == "openai":
        from .openai_compat import OpenAICompatProvider
        key = _require("OPENAI_API_KEY", "your OpenAI API key (sk-...)")
        m = model or _require("TRELLIS_VERIFIER_MODEL", "e.g. gpt-5.5-mini")
        base = os.environ.get("TRELLIS_OPENAI_BASE_URL", "https://api.openai.com/v1")
        return OpenAICompatProvider(base_url=base, model=m, api_key=key)

    if kind == "claude":
        from .claude_sdk import ClaudeSDKProvider
        return ClaudeSDKProvider(model=model or _VERIFIER_DEFAULT_MODEL["claude"])

    if kind == "codex":
        from .codex import CodexProvider
        return CodexProvider(model=model or None)

    raise ProviderUnavailable(
        f"unknown TRELLIS_VERIFIER_PROVIDER={kind!r}. Valid: {', '.join(VALID)}.")


def verifier_provider_from_env(maker: Optional[Provider] = None) -> Provider:
    """The SECOND seat (D34): the independent, cheaper verifier — Opus makes,
    Haiku verifies, same family. Reads TRELLIS_VERIFIER_PROVIDER (defaulting to
    the maker's TRELLIS_PROVIDER — same family) and TRELLIS_VERIFIER_MODEL (the
    cheaper model). REFUSES LOUD if the verifier seat equals the maker seat, in
    parity with D4 (maker != verifier): even the model seat must differ, not just
    the agent id, or the verification is a self-audit one layer down.

    Pass the already-constructed `maker` so the collision can be checked; omit it
    only when you have no maker to compare against."""
    kind = os.environ.get("TRELLIS_VERIFIER_PROVIDER", "").strip().lower()
    if not kind:
        kind = os.environ.get("TRELLIS_PROVIDER", "").strip().lower()  # same family
    if not kind:
        raise ProviderUnavailable(
            "TRELLIS_VERIFIER_PROVIDER (or TRELLIS_PROVIDER) is unset. Refusing to "
            f"guess the verifier seat. Set it to one of: {', '.join(VALID)}.")
    if kind not in VALID:
        raise ProviderUnavailable(
            f"unknown TRELLIS_VERIFIER_PROVIDER={kind!r}. Valid: {', '.join(VALID)}.")

    model = os.environ.get("TRELLIS_VERIFIER_MODEL", "").strip()
    verifier = _build_verifier_seat(kind, model)

    if maker is not None and _same_seat(maker, verifier):
        raise VerifierSeatError(
            f"the verifier seat ({verifier.id!r}) equals the maker seat "
            f"({maker.id!r}) — a self-audit is not an audit (D4/D34). Set "
            "TRELLIS_VERIFIER_MODEL to a distinct, cheaper model in the same "
            "family (Opus makes, Haiku verifies).")
    return verifier


def _same_seat(a: Provider, b: Provider) -> bool:
    """Two provider seats are 'the same' when their ids match (a provider id
    encodes backend + model). Case/space-insensitive so trivial differences don't
    read as independence."""
    return getattr(a, "id", "").strip().lower() == getattr(b, "id", "").strip().lower()
