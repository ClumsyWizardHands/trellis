"""identity.py — one definition of "the same actor" / "effectively blank",
used by every gate. Confusable-aware.

The 50-agent adversary broke three gates the same way: a homoglyph.
- #17: "ѕoul.md" (Cyrillic ѕ) bypassed the soul-file refusal
- #37: "ſam" (long s) impersonated receiver "sam"
- #46: "witnеss" (Cyrillic е) self-certified against "witness"
and three more with invisible characters (#19, #28 zero-width authored_by /
emp_lineage). One normalization now closes all of them.

Honest limitation (documented, not hidden): full Unicode confusable defense is
unbounded. This folds NFKC compatibility forms plus a table of the common
Cyrillic/Greek Latin-lookalikes. A determined attacker with an exotic homoglyph
outside the table could still slip through — a real deployment should pin an
allowlist of known agent/human identities. For a personal agent this fold plus
an allowlist is enough; the table is the floor, not the ceiling.
"""

from __future__ import annotations

import re
import unicodedata

# Common Latin-lookalikes from Cyrillic and Greek → their Latin letter.
_CONFUSABLES = {
    # Cyrillic
    "а": "a", "ѕ": "s", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y",
    "х": "x", "і": "i", "ј": "j", "ԁ": "d", "н": "h", "т": "t", "г": "r",
    "в": "b", "к": "k", "м": "m", "ѐ": "e", "ё": "e", "ո": "n", "ս": "u",
    # Greek
    "ο": "o", "α": "a", "ρ": "p", "ϲ": "c", "ν": "v", "ι": "i", "κ": "k",
    "μ": "m", "τ": "t", "υ": "u", "χ": "x", "ε": "e",
}
_CONF_TABLE = str.maketrans(_CONFUSABLES)


def _fold(s: str) -> str:
    """NFKC (folds long-s, fullwidth, ligatures) → confusable table → casefold."""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.translate(_CONF_TABLE)
    return s.casefold()


def normalize_identity(s: str) -> str:
    """Canonical identity string. 'WITNESS:A', ' witness:a ', 'witnеss:a'
    (Cyrillic) all collapse to one value; invisible chars are dropped."""
    folded = _fold(s)
    return re.sub(r"[^a-z0-9:_/-]+", "", folded.strip())


def same_identity(a: str, b: str) -> bool:
    na, nb = normalize_identity(a), normalize_identity(b)
    return bool(na) and na == nb


def fold_text(s: str) -> str:
    """Confusable-fold arbitrary text (for content gates like the soul-file and
    embodiment checks) without stripping structure."""
    return _fold(s)


def is_effectively_blank(s: str | None) -> bool:
    """True if s is empty once whitespace, zero-width, control and format
    characters are removed. Catches ' ', '\\u200b', '\\t', '\\xa0', etc."""
    if not s:
        return True
    cleaned = "".join(
        ch for ch in unicodedata.normalize("NFKC", s)
        if not unicodedata.category(ch)[0] in {"Z", "C"})
    return cleaned.strip() == ""
