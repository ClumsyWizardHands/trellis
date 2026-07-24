"""auth.py — authority is an authenticated PRINCIPAL, not a caller-supplied string.

Codex infrastructure audit, Critical 1: every authority gate (approve, declassify,
verify) inferred the actor from a name the caller supplied — the web took it from a
plain form field with no authentication, so any HTTP caller could claim to be
"alex" and satisfy the human-seat gate. Spelling/homoglyph disguise was already
closed (identity.py); impersonation was not.

This module is the trusted boundary that mints a `Principal`. An `authenticated`
Principal can ONLY come from `Authenticator.authenticate()` (verifying a secret) —
never from a caller constructing one. The web derives the approver from a SIGNED
SESSION, not a form field, and passes the authenticated id into the existing gates.

Right-sized for the actual deployment (a personal agent on your machine): a single
shared secret. Set `TRELLIS_APPROVER_SECRET` (and `TRELLIS_HUMAN`) for a stable
credential, or let the server mint an EPHEMERAL one at startup and print a one-time
login token to the console you launched it from — only someone with that terminal
can log in. A multi-user deployment swaps `Authenticator` for real accounts / OIDC
behind the same `Principal` seam; nothing downstream changes. Stdlib only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from .identity import require_identity, same_identity


class AuthError(Exception):
    """A credential or session that did not authenticate."""


@dataclass(frozen=True)
class Principal:
    """An actor whose identity has been ESTABLISHED, not merely claimed. An
    `authenticated=True` Principal is only ever minted by an Authenticator that
    verified a secret; downstream code trusts `authenticated` because the type
    can't be forged into existence through a normal string path."""
    id: str                    # canonical ASCII id (require_identity)
    authenticated: bool = False

    def same_as(self, other_id: str) -> bool:
        return same_identity(self.id, other_id)


class Authenticator:
    """Verifies a credential and issues/validates signed sessions. One shared
    secret (the personal-agent case); the seam generalizes to real accounts."""

    # How long a login lasts. Default 30 DAYS: this portal binds to localhost
    # on the owner's own machine, and a 12h expiry produced daily re-login
    # ceremony with no safety gain (Alex, 2026-07-24: "driving me crazy").
    # TRELLIS_SESSION_HOURS tunes it; a hosted/multi-user deployment should
    # set it back down. Sessions stay tamper-evident and revocable — changing
    # TRELLIS_APPROVER_SECRET invalidates every outstanding session at once.
    SESSION_TTL = int(float(os.environ.get("TRELLIS_SESSION_HOURS", "720")
                            or 720) * 3600)   # int: a float Max-Age breaks cookies

    def __init__(self, human_id: str, secret: str):
        self.human_id = require_identity(human_id, "human")
        if not secret:
            raise AuthError("an authenticator needs a non-empty secret")
        self._secret = secret.encode("utf-8")

    @classmethod
    def from_env_or_ephemeral(cls) -> Tuple["Authenticator", Optional[str]]:
        """Build from `TRELLIS_HUMAN` + `TRELLIS_APPROVER_SECRET`. If no secret is
        configured, mint an EPHEMERAL one and return it as the one-time login token
        the caller should print to the console (only someone with terminal access
        sees it). Returns (authenticator, printed_token_or_None)."""
        human = os.environ.get("TRELLIS_HUMAN", "operator")
        secret = os.environ.get("TRELLIS_APPROVER_SECRET")
        if secret:
            return cls(human, secret), None
        token = secrets.token_urlsafe(24)
        return cls(human, token), token

    # ----- credential → principal -------------------------------------------

    def authenticate(self, token: str) -> Principal:
        """Verify the login secret (constant-time) and mint an AUTHENTICATED
        principal. Wrong/blank token raises — no benefit of the doubt."""
        if not token or not hmac.compare_digest(token.encode("utf-8"), self._secret):
            raise AuthError("invalid approver token")
        return Principal(self.human_id, authenticated=True)

    # ----- signed session (so the secret isn't resent each request) ----------

    def issue_session(self, principal: Principal) -> str:
        """A tamper-evident session token: base64(id.issued).hmac. Signed with the
        secret, so it can't be forged or edited without it."""
        if not principal.authenticated:
            raise AuthError("cannot issue a session for an unauthenticated principal")
        payload = f"{principal.id}.{int(time.time())}"
        sig = self._sign(payload)
        return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig

    def verify_session(self, cookie: Optional[str]) -> Optional[Principal]:
        """Return the authenticated Principal a valid, unexpired session names, or
        None. Any tamper (edited id, forged sig, expired) → None, never a pass."""
        if not cookie or "." not in cookie:
            return None
        try:
            b64, sig = cookie.rsplit(".", 1)
            payload = base64.urlsafe_b64decode(b64.encode()).decode()
            pid, issued = payload.rsplit(".", 1)
            issued_ts = int(issued)
        except Exception:
            return None
        if not hmac.compare_digest(sig, self._sign(payload)):
            return None                              # forged / edited signature
        if time.time() - issued_ts > self.SESSION_TTL:
            return None                              # expired — re-authenticate
        if not same_identity(pid, self.human_id):
            return None                              # not the configured human
        return Principal(self.human_id, authenticated=True)

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode("utf-8"),
                        hashlib.sha256).hexdigest()[:32]
