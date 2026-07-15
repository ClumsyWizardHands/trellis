"""providers/openai_compat.py — any OpenAI-compatible endpoint, stdlib only.

This is the local-model seat: Ollama, LM Studio, llama.cpp server, vLLM —
which is how Gemma / Hermes / Nemotron sit in a trellis (Clare's July 2026
prototype runs local models on exactly this shape). No dependency: urllib.

Known local footguns are checked LOUDLY at construction (the Hermes research
lesson): a context window that's silently 4k turns an agent into a goldfish.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from .base import ProviderResponse, ProviderUnavailable, ToolCall


class OpenAICompatProvider:
    def __init__(self, base_url: str, model: str, api_key: str = "not-needed",
                 timeout: float = 120.0, min_context: int = 16000):
        self.id = f"openai-compat:{model}@{base_url}"
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.min_context = min_context

    def preflight(self) -> dict:
        """Ask the endpoint what it actually is. Fails loud, returns evidence.

        Context-window honesty: most OpenAI-compatible endpoints don't report
        their context length. Where the endpoint reports one, it is compared
        against min_context and a shortfall RAISES. Where it doesn't, the
        result says context_confirmed=False — reported, never silently
        assumed. (Review found the original docstring promised a check the
        code didn't do; this is the honest version.)"""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            raise ProviderUnavailable(
                f"endpoint {self.base_url} unreachable ({e}). If this is Ollama, "
                "remember OLLAMA_CONTEXT_LENGTH — a silent 4k context is a "
                "recorded failure mode. This adapter refuses to guess.") from e

        models = data.get("data", [])
        reported = None
        for m in models:
            if m.get("id") == self.model:
                for k in ("context_length", "max_context_length", "context_window"):
                    if isinstance(m.get(k), int):
                        reported = m[k]
        if reported is not None and reported < self.min_context:
            raise ProviderUnavailable(
                f"endpoint reports context {reported} < required "
                f"{self.min_context} for {self.model} — an agent on a goldfish "
                "context fails silently everywhere else; here it fails now.")
        return {"ok": True, "models": [m.get("id") for m in models],
                "context_confirmed": reported is not None,
                "reported_context": reported,
                "note": (None if reported is not None else
                         "endpoint does not report context length — UNCONFIRMED; "
                         f"verify >= {self.min_context} yourself")}

    def complete(self, system: str, messages: list[dict],
                 tools: Optional[list[dict]] = None) -> ProviderResponse:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if tools:
            payload["tools"] = [{
                "type": "function",
                "function": {"name": t["name"], "description": t.get("description", ""),
                             "parameters": t.get("parameters", {"type": "object"})},
            } for t in tools]
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ProviderUnavailable(f"completion call failed loudly: {e}") from e

        choice = data["choices"][0]["message"]
        calls = [ToolCall(tc["function"]["name"],
                          json.loads(tc["function"].get("arguments") or "{}"))
                 for tc in choice.get("tool_calls") or []]
        return ProviderResponse(text=choice.get("content"), tool_calls=calls,
                                model=data.get("model", self.model),
                                usage=data.get("usage", {}))
