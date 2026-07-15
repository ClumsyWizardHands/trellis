"""providers/mock.py — deterministic provider for tests and dry runs.

Every trellis behavior is testable without a network or an API key. The mock
is scripted: you enqueue responses; it replays them and records everything it
was asked. Verification of the HARNESS never depends on the mood of a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .base import Provider, ProviderResponse, ToolCall


@dataclass
class MockProvider:
    id: str = "mock"
    script: list[ProviderResponse] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def enqueue_text(self, text: str) -> None:
        self.script.append(ProviderResponse(text=text, model="mock"))

    def enqueue_tool_call(self, name: str, arguments: dict) -> None:
        self.script.append(ProviderResponse(
            tool_calls=[ToolCall(name, arguments)], model="mock"))

    def complete(self, system: str, messages: list[dict],
                 tools: Optional[list[dict]] = None) -> ProviderResponse:
        self.calls.append({"system": system, "messages": list(messages),
                           "tools": list(tools or [])})
        if not self.script:
            return ProviderResponse(text="(mock exhausted)", model="mock")
        return self.script.pop(0)
