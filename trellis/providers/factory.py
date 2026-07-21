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

from .base import Provider, ProviderUnavailable
from .mock import MockProvider

VALID = ("mock", "local", "openai", "claude")


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

    raise ProviderUnavailable(
        f"unknown TRELLIS_PROVIDER={kind!r}. Valid: {', '.join(VALID)}.")
