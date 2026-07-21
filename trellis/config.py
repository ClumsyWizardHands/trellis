"""config.py — one place to read trellis's configuration. Zero-dependency.

Loads a `.env` file if present (the real `.env` is gitignored; `.env.example` is
the committed template), then reads `os.environ`. No `python-dotenv` dependency —
a ~20-line stdlib parser keeps the core clean. Secret accessors fetch on demand
and never log the value; a required-but-missing value fails LOUD (the same
discipline as `AgentIdentity.credential()` and the D11 no-silent-degradation rule).

Nothing here depends on git, so it works identically from a `git clone` or a plain
unzipped download.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class ConfigError(Exception):
    """A required configuration value is missing or malformed."""


def load_dotenv(path: "str | Path" = ".env", *, override: bool = False) -> dict:
    """Load KEY=VALUE lines from a .env into os.environ if the file exists.

    Missing file → {} (not an error: env may be set another way). Existing
    os.environ values are NOT overwritten unless override=True. Supports
    `export KEY=val`, `#` comments, and single/double-quoted values.
    """
    p = Path(path)
    parsed: dict[str, str] = {}
    if not p.is_file():
        return parsed
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        val = val.strip().strip('"').strip("'")
        if not key:
            continue
        parsed[key] = val
        if override or key not in os.environ:
            os.environ[key] = val
    return parsed


def get(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(name, default)


def require(name: str, *, hint: str = "") -> str:
    """Return a required value or raise ConfigError naming it (and how to fix)."""
    v = os.environ.get(name, "").strip()
    if not v:
        raise ConfigError(f"required config {name} is unset"
                          + (f" — {hint}" if hint else ""))
    return v


# ---- typed accessors for known surfaces (kept in sync with .env.example) ----

def ledger_path() -> str:
    return os.environ.get("TRELLIS_LEDGER", "state/ledger.jsonl")


def vault_path() -> Optional[str]:
    v = os.environ.get("TRELLIS_VAULT_PATH", "").strip()
    return v or None


def provider_kind() -> Optional[str]:
    v = os.environ.get("TRELLIS_PROVIDER", "").strip().lower()
    return v or None
