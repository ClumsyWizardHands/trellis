"""providers/codex.py — the OpenAI seat via the OFFICIAL Codex CLI.

trellis runs OpenAI models on your **ChatGPT subscription** without an API key by
shelling out to OpenAI's own `codex` client — the same way the `local` seat shells
out to Ollama. Codex owns the login and the credential end to end; trellis NEVER
touches OAuth, tokens, or `~/.codex/auth.json`, and never recreates the sign-in
exchange. This keeps the subscription credential inside OpenAI's sanctioned client
(so it is not the raw-token reuse that carries ToS risk).

Auth (Codex manages it; trellis only detects + points you at it):
  * `codex login`                       — Sign in with ChatGPT (browser); uses your
                                          Plus/Pro/Team subscription, no API key
  * `codex login --device-auth`         — headless / remote box
  * `printenv OPENAI_API_KEY | codex login --with-api-key`  — API-key instead

A completion is one non-interactive `codex exec` run, sandboxed READ-ONLY in a
throwaway working dir (it cannot touch your files), with the agent's final message
captured via `--output-last-message`.

Caveat (stated honestly): Codex is a coding *agent*, not a bare chat model — it
follows the prompt and returns a final message, which is what the Witness reads,
but it is heavier and more tool-shaped than the `claude`/`local`/`openai` seats.
Good for "use my OpenAI subscription, no API key"; not a drop-in chat endpoint.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional

from .base import ProviderResponse, ProviderUnavailable


class CodexProvider:
    """OpenAI model seat backed by the official `codex` CLI (subscription or key).

    trellis invokes `codex`; it does not authenticate, store, refresh, read, or
    expose any Codex credential — that is entirely Codex's job (per OpenAI's
    documented CLI). preflight() only *detects* login via `codex login status`.
    """

    def __init__(self, model: Optional[str] = None, codex_bin: str = "codex",
                 timeout: float = 180.0):
        self.model = model or None            # None → Codex's configured default
        self.id = f"codex:{model}" if model else "codex"
        self.codex_bin = codex_bin
        self.timeout = timeout
        if shutil.which(codex_bin) is None:
            raise ProviderUnavailable(
                f"the OpenAI Codex CLI ({codex_bin!r}) is not installed — this seat "
                "fails loudly by design. Install it (npm i -g @openai/codex or see "
                "developers.openai.com/codex), then run `codex login`.")

    # ----- readiness: detect Codex's own login, never handle its credential ----

    def preflight(self) -> dict:
        """Honest readiness: ask `codex login status`. READY only when Codex
        reports a login; otherwise refuse and point at the sanctioned sign-in.
        No credential is read or parsed — Codex answers for itself."""
        try:
            r = subprocess.run([self.codex_bin, "login", "status"],
                               capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as e:
            raise ProviderUnavailable(f"could not run `{self.codex_bin} login status`: {e}")
        out = f"{r.stdout}\n{r.stderr}".strip()
        low = out.lower()
        if r.returncode == 0 and "logged in" in low:
            if "chatgpt" in low:
                auth = "chatgpt_subscription"
            elif "api" in low:
                auth = "api_key"
            else:
                auth = "authenticated"
            return {"ok": True, "context_confirmed": True, "auth": auth,
                    "note": out.splitlines()[0] if out else "codex reports logged in"}
        raise ProviderUnavailable(
            "codex is not logged in. Run `codex login` (Sign in with ChatGPT — uses "
            "your subscription, no API key), or `codex login --device-auth` on a "
            "headless box, or `printenv OPENAI_API_KEY | codex login --with-api-key`. "
            "trellis never handles the Codex credential — Codex manages its own login.")

    # ----- completion: one non-interactive, read-only, ephemeral codex exec ----

    def complete(self, system: str, messages: list[dict],
                 tools: Optional[list[dict]] = None) -> ProviderResponse:
        prompt = self._build_prompt(system, messages)
        # A throwaway cwd + read-only sandbox + ephemeral session: Codex cannot
        # write anything, persists no session, and never scans the trellis repo.
        with tempfile.TemporaryDirectory(prefix="trellis-codex-") as workdir:
            last_msg = os.path.join(workdir, "last_message.txt")
            cmd = [self.codex_bin, "exec",
                   "--skip-git-repo-check", "--ephemeral",
                   "--sandbox", "read-only", "--color", "never",
                   "--cd", workdir,
                   "--output-last-message", last_msg]
            if self.model:
                cmd += ["-m", self.model]
            cmd += ["-"]                        # read the prompt from stdin
            try:
                r = subprocess.run(cmd, input=prompt, capture_output=True,
                                   text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                raise ProviderUnavailable(
                    f"`codex exec` did not finish within {self.timeout:.0f}s — "
                    "refusing to report a partial/empty completion as success.")
            except OSError as e:
                raise ProviderUnavailable(f"could not run `codex exec`: {e}")
            text = ""
            try:
                with open(last_msg, encoding="utf-8") as fh:
                    text = fh.read().strip()
            except OSError:
                text = ""
        if r.returncode != 0 and not text:
            tail = (r.stderr or r.stdout or "").strip()[-400:]
            raise ProviderUnavailable(
                f"`codex exec` failed (exit {r.returncode}). If this is an auth issue, "
                f"run `codex login`. Detail: {tail}")
        return ProviderResponse(text=text, usage={"seat": "codex"})

    @staticmethod
    def _build_prompt(system: str, messages: list[dict]) -> str:
        parts = []
        if system and system.strip():
            parts.append(system.strip())
        for m in messages:
            content = m.get("content")
            if content:
                parts.append(f"[{m.get('role', 'user')}] {content}")
        return "\n\n".join(parts)
