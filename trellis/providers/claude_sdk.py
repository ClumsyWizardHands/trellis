"""providers/claude_sdk.py — the Claude Agent SDK seat (first-class, optional).

Lazy import; loud failure. The SDK brings its own loop, tools, sessions and
hooks — trellis does not fight it. This adapter uses the SDK as a *model seat*
inside trellis loops (sense→resolve→act→verify→remember stays trellis's), and
exposes a hook-mount helper for running trellis's refusals INSIDE a full SDK
agent when you want the SDK to drive.

Install:  pip install claude-agent-sdk   (and set ANTHROPIC_API_KEY)
"""

from __future__ import annotations

from typing import Optional

from .base import Provider, ProviderResponse, ProviderUnavailable


class ClaudeSDKProvider:
    """Minimal adapter: one-shot completion via the Claude Agent SDK's query().

    For long-lived SDK-driven agents, see docs/claude-sdk.md — trellis mounts
    as hooks (PreToolUse → stage-don't-fire; Stop → outcome required;
    SessionEnd → epitaph) rather than wrapping the loop.
    """

    def __init__(self, model: str = "claude-sonnet-4-5", verifier_model: Optional[str] = None):
        self.id = f"claude-sdk:{model}"
        self.model = model
        self.verifier_model = verifier_model or "claude-haiku-4-5"
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError as e:
            raise ProviderUnavailable(
                "claude-agent-sdk is not installed. This seat fails loudly by "
                "design (silent auxiliary degradation is a recorded failure "
                "mode). Install with: pip install claude-agent-sdk — or use "
                "MockProvider / OpenAICompatProvider."
            ) from e

    def preflight(self) -> dict:
        """Honest readiness for the hosted claude seat.

        Verifies a credential is present and well-formed BEFORE doctor can
        report READY. Without this, doctor printed READY for a wrong or absent
        API key — contradicting its own maker≠verifier contract (FableG14). No
        network call is made here (that would spend a token on every doctor
        run); the credential shape is checked, and that is what the note says.
        """
        import os
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise ProviderUnavailable(
                "ANTHROPIC_API_KEY is unset — the claude seat has no credential. "
                "doctor refuses to report READY for a seat it cannot authenticate.")
        if not key.startswith("sk-ant-"):
            raise ProviderUnavailable(
                "ANTHROPIC_API_KEY is set but not well-formed (Anthropic keys "
                "begin 'sk-ant-'). Refusing to report READY on a malformed "
                "credential rather than fail at the first live call.")
        return {"ok": True, "context_confirmed": True,
                "note": "API key present and well-formed (not network-checked)"}

    def complete(self, system: str, messages: list[dict],
                 tools: Optional[list[dict]] = None) -> ProviderResponse:
        import anyio
        from claude_agent_sdk import query, ClaudeAgentOptions

        prompt = "\n\n".join(
            f"[{m['role']}] {m['content']}" for m in messages if m.get("content"))

        async def _run() -> str:
            chunks: list[str] = []
            options = ClaudeAgentOptions(
                system_prompt=system,
                model=self.model,
                max_turns=8,  # bounded here too; unbounded is the recorded failure
                allowed_tools=[t["name"] for t in (tools or [])] or [],
            )
            async for message in query(prompt=prompt, options=options):
                text = getattr(message, "result", None)
                if text:
                    chunks.append(text)
            return "\n".join(chunks)

        text = anyio.run(_run)
        return ProviderResponse(text=text, model=self.model)
