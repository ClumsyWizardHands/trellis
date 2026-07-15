"""providers/base.py — the model is a seat, not the core. (DECISIONS.md D11)

trellis is model-agnostic on purpose: "Create what you want and most need
today like there's no frontier AI access tomorrow" (Brett, 2026-07-12). The
core never imports a vendor SDK; adapters do, lazily, and fail LOUD — the
Hermes cautionary tale is auxiliary models degrading silently.

The protocol is deliberately tiny: complete(system, messages, tools) -> a
response that either has text or tool calls. Everything a harness needs,
nothing a vendor lock rides in on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


class ProviderUnavailable(Exception):
    """Raised loudly when an adapter's backend is not installed/configured.
    Silent degradation is a failure mode, not a convenience."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass
class ProviderResponse:
    text: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)   # tokens/cost if the backend reports them

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@runtime_checkable
class Provider(Protocol):
    """Any model behind one method."""

    id: str

    def complete(self, system: str, messages: list[dict],
                 tools: Optional[list[dict]] = None) -> ProviderResponse:
        """messages: [{"role": "user"|"assistant"|"tool", "content": str, ...}]
        tools: optional JSON-schema tool specs (name, description, parameters).
        """
        ...
