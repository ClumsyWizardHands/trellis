"""providers/claude_sdk.py — the Claude Agent SDK seat (first-class, optional).

Lazy import; loud failure. The SDK brings its own loop, tools, sessions and
hooks — trellis does not fight it. This adapter uses the SDK as a *model seat*
inside trellis loops (sense→resolve→act→verify→remember stays trellis's), and
exposes a hook-mount helper for running trellis's refusals INSIDE a full SDK
agent when you want the SDK to drive.

Install:  pip install claude-agent-sdk. Auth: it runs on your Claude Max
SUBSCRIPTION by default (via `claude login` / `claude setup-token`), or an
ANTHROPIC_API_KEY if you prefer per-token billing — see preflight().
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .base import Provider, ProviderResponse, ProviderUnavailable


def _subscription_login_present() -> bool:
    """True if a local `claude login` subscription credential looks present.

    The Agent SDK stores these in the OS keychain on macOS and in
    ~/.claude/.credentials.json elsewhere; we can only cheaply check the file
    (and the config dir as a weak macOS signal), so this is a best-effort
    detector, never a guarantee — preflight always notes it is not
    network-verified. Factored out so tests can isolate it. For a daemon, prefer
    `claude setup-token` → CLAUDE_CODE_OAUTH_TOKEN, which is unambiguously
    detectable and unattended-safe."""
    home = Path.home()
    if (home / ".claude" / ".credentials.json").exists():
        return True
    # macOS keeps the credential in the Keychain (no readable file). Check for
    # the ENTRY'S EXISTENCE only — `security find-generic-password` WITHOUT -w
    # never prints the secret; exit 0 just means "an entry is there". This is
    # still not network-verified (preflight says so), but it stops a real,
    # working `claude login` from reading as "no credential" on macOS.
    import subprocess
    import sys
    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["security", "find-generic-password", "-s",
                 "Claude Code-credentials"],
                capture_output=True, timeout=5)
            if res.returncode == 0:
                return True
        except Exception:
            pass
    return False


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
        """Honest readiness for the claude seat — subscription-first.

        The Claude Agent SDK resolves credentials in a precedence order, and
        trellis is meant to run on the owner's **Claude Max subscription**, not
        an API key (the earlier "subscription not wired" note was wrong: using
        your OWN subscription through the OFFICIAL SDK is a supported path — it is
        reverse-engineering the raw OAuth endpoints that carries ToS risk, which
        trellis does NOT do). So this checks, in the SDK's own order:

          1. ANTHROPIC_API_KEY        — explicit API key (per-token billing)
          2. CLAUDE_CODE_OAUTH_TOKEN  — a long-lived (~1yr) subscription token from
                                        `claude setup-token` — the UNATTENDED path,
                                        the right one for the always-on runner (D37)
          3. ANTHROPIC_AUTH_TOKEN     — a gateway/bearer token
          4. a local `claude login`   — subscription creds on disk / Keychain

        No network call is made (that would spend on every doctor run); this
        reports which credential WILL be used, honestly noting it is not
        network-verified. Only when NONE is detectable does it refuse READY —
        and the message points at the subscription path first (FableG14 honesty
        preserved: no READY for a seat we cannot authenticate)."""
        import os
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if key:
            if not key.startswith("sk-ant-"):
                raise ProviderUnavailable(
                    "ANTHROPIC_API_KEY is set but not well-formed (Anthropic keys "
                    "begin 'sk-ant-'). Refusing to report READY on a malformed "
                    "credential rather than fail at the first live call.")
            return {"ok": True, "context_confirmed": True, "auth": "api_key",
                    "note": "ANTHROPIC_API_KEY present and well-formed (per-token "
                            "billing; not network-checked)"}
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
            return {"ok": True, "context_confirmed": True, "auth": "subscription_token",
                    "note": "using your Claude subscription via CLAUDE_CODE_OAUTH_TOKEN "
                            "(unattended-safe; not network-checked)"}
        if os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip():
            return {"ok": True, "context_confirmed": True, "auth": "bearer",
                    "note": "using ANTHROPIC_AUTH_TOKEN (gateway/bearer; not network-checked)"}
        if _subscription_login_present():
            return {"ok": True, "context_confirmed": True, "auth": "subscription_login",
                    "note": "using your local `claude login` subscription credentials "
                            "(not network-checked)"}
        raise ProviderUnavailable(
            "the claude seat has no detectable credential. To run on your Claude Max "
            "subscription (recommended): run `claude login` (interactive) or "
            "`claude setup-token` and set CLAUDE_CODE_OAUTH_TOKEN (unattended — best "
            "for the always-on runner). Or set ANTHROPIC_API_KEY for per-token API "
            "billing. doctor refuses to report READY for a seat it cannot authenticate.")

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

        # a HARD ceiling on the whole call: the third silent-stall class found
        # on 2026-07-22 (after the Drive transport and the OAuth refresh) was a
        # model call waiting forever. A hung seat must become a loud, caught
        # per-item failure — the learning pass records it and moves on.
        import concurrent.futures
        import os as _os
        raw = _os.environ.get("TRELLIS_MODEL_TIMEOUT", "").strip()
        try:
            ceiling = float(raw) if raw else 300.0
        except ValueError:
            ceiling = 300.0
        pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="claude-seat")
        future = pool.submit(anyio.run, _run)
        try:
            text = future.result(timeout=ceiling)
        except concurrent.futures.TimeoutError:
            # do NOT wait for the wedged worker — abandon it loudly
            pool.shutdown(wait=False, cancel_futures=True)
            raise TimeoutError(
                f"claude seat call exceeded {ceiling:.0f}s "
                "(TRELLIS_MODEL_TIMEOUT) — treated as a failed call, "
                "never a silent stall") from None
        pool.shutdown(wait=False)
        return ProviderResponse(text=text, model=self.model)
