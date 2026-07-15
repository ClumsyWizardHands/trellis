"""identity.py — one definition of "the same actor", used by every gate.

The fresh-eyes review (2026-07-15) bypassed the self-approval gate with
"WITNESS:A" and "witness:a." — case and punctuation disguises. The lesson:
every independence check must share ONE normalization, or the strictest gate
is only as strong as the sloppiest comparison.
"""

from __future__ import annotations

import re


def normalize_identity(s: str) -> str:
    """Casefold and strip everything that isn't identity-bearing. 'WITNESS:A.',
    ' witness:a ' and 'Witness:A' are all the same actor."""
    return re.sub(r"[^a-z0-9:_/-]+", "", (s or "").strip().casefold())


def same_identity(a: str, b: str) -> bool:
    na, nb = normalize_identity(a), normalize_identity(b)
    return bool(na) and na == nb
