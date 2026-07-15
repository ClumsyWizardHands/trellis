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
    # 'l' lookalikes (no NFKD decomposition) — the #17 round-3 gap
    "ӏ": "l", "Ӏ": "l", "ł": "l", "ǀ": "l", "ן": "l", "׀": "l", "Ⲓ": "l",
}
_CONF_TABLE = str.maketrans(_CONFUSABLES)

# Categories whose characters are invisible / non-graphic and must be REMOVED
# before any identity or content comparison: control, format, surrogate,
# private-use, unassigned, combining marks, and line/paragraph separators.
_REMOVE_CATS = {"Cc", "Cf", "Cs", "Co", "Cn", "Mn", "Me", "Zl", "Zp"}
# Characters that render blank but sit in OTHER categories, so the category
# test alone misses them. The 50-agent re-attack found every one of these:
# braille blank (So), Hangul fillers (Lo), Mongolian vowel separator, etc.
_EXTRA_BLANK = {
    "⠀",                        # BRAILLE PATTERN BLANK (So)
    "ᅠ", "ㅤ", "ᅟ", "ﾠ",  # Hangul fillers (Lo)
    "᠎",                        # Mongolian vowel separator
    "​", "‌", "‍", "⁠", "﻿", "­", "͏",  # ZW family
}


def _strip_invisible(s: str) -> str:
    """Remove every non-graphic / blank-rendering character, across ALL
    categories — not just Z and C (the hole the re-attack exploited)."""
    return "".join(
        ch for ch in s
        if unicodedata.category(ch) not in _REMOVE_CATS and ch not in _EXTRA_BLANK)


def _fold(s: str) -> str:
    """CONTENT fold (soul-file, embodiment linter): NFKD → confusable table →
    strip invisibles → casefold. Confusables ARE folded here because for content
    DETECTION we want 'ѕo‍ul' to become 'soul' — aggressive folding is correct
    when the goal is to catch a disguised word."""
    s = unicodedata.normalize("NFKD", s or "")
    s = s.translate(_CONF_TABLE)
    s = _strip_invisible(s)
    return s.casefold()


def _fold_identity(s: str) -> str:
    """IDENTITY fold: NFKD → strip invisibles → casefold, but NO confusable
    table. Round 4 showed the table over-merges DISTINCT real names ('мир' →
    'mir', 'łukasz' → 'lukasz'), wrongly rejecting an honest independent
    verifier. For identity, folding confusables is the wrong move — an id must
    be a real ASCII identifier, and anything else is refused, not guessed."""
    s = unicodedata.normalize("NFKD", s or "")
    s = _strip_invisible(s)
    return s.casefold()


def normalize_identity(s: str) -> str:
    """Canonical id: 'WITNESS:A', ' witness:a ', and any invisible-char variant
    collapse to one value. Non-ASCII letters are dropped (they can't be part of
    a canonical ASCII id) — use require_identity() to REJECT rather than silently
    mangle them."""
    folded = _fold_identity(s)
    return re.sub(r"[^a-z0-9:_/-]+", "", folded.strip())


def same_identity(a: str, b: str) -> bool:
    na, nb = normalize_identity(a), normalize_identity(b)
    return bool(na) and na == nb


class InvalidIdentityError(ValueError):
    """An identity string that is not a usable ASCII identifier. Rejecting these
    at the gate — rather than folding or silently mangling them — is the
    structural answer to the homoglyph arms race (round 4 #46): self-cert is
    closed (exotic ids are refused, not reasoned about) AND distinct real names
    are never wrongly merged."""


def _has_nonascii_letter(s: str) -> bool:
    return any(ch.isalpha() and not ch.isascii() for ch in _fold_identity(s))


def require_identity(s: str, role: str = "identity") -> str:
    """Return the canonical ASCII id, or raise. Agent/human ids MUST be ASCII;
    a non-ASCII name must be registered with an ASCII canonical id by the
    deployment (see IdentityRegistry in docs). This makes identity an allowlist,
    not a blocklist — the only defense that actually converges."""
    if _has_nonascii_letter(s):
        raise InvalidIdentityError(
            f"{role} {s!r} contains non-ASCII letters — agent ids must be ASCII. "
            "Register a canonical ASCII id for a non-ASCII display name rather "
            "than letting the harness guess whether two scripts mean the same actor.")
    canon = normalize_identity(s)
    if not canon:
        raise InvalidIdentityError(
            f"{role} {s!r} does not reduce to a valid identifier — ids must "
            "contain ASCII letters or digits.")
    return canon


def fold_text(s: str) -> str:
    """Confusable-fold arbitrary text for content gates (soul-file check):
    NFKC + confusables + invisibles REMOVED + casefold — so 'ѕo‍ul' folds to
    'soul' (glyphs join)."""
    return _fold(s)


def scan_normalize(s: str) -> str:
    """For content SCANNING (the embodiment linter): every invisible/blank
    character becomes a SPACE (so a hidden word-break resurfaces), confusables
    fold, whitespace collapses, casefold. Distinct from fold_text, which
    removes invisibles — a scanner wants word boundaries to surface, a
    name-matcher wants glyphs to join."""
    nf = unicodedata.normalize("NFKD", s or "")
    spaced = "".join(
        " " if (unicodedata.category(ch) in _REMOVE_CATS or ch in _EXTRA_BLANK) else ch
        for ch in nf)
    spaced = spaced.translate(_CONF_TABLE)
    return re.sub(r"\s+", " ", spaced).strip().casefold()


def is_effectively_blank(s: str | None) -> bool:
    """True if s carries no meaningful visible character once NFKC-normalized,
    all invisible/blank characters (any category, incl. braille blank and
    Hangul fillers) removed, and whitespace stripped."""
    if not s:
        return True
    cleaned = _strip_invisible(unicodedata.normalize("NFKD", s))
    # remaining spaces (category Zs — normal, NBSP, ideographic) are whitespace
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch) != "Zs")
    return cleaned.strip() == ""
