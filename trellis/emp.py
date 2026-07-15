"""emp.py — identity is an EMP, not a soul. (DECISIONS.md D3)

"Stop giving agents a soul. Give them an empire." — the June 2026 paradigm doc,
finally executed. Brett named the original sin: "the agent gaslighting itself
and us that it is something it is not. You cannot run a stable, honest loop on
a dishonest self-concept."

An EMP is the honest anatomy:

    Ends        — what this agent exists to move toward (authored by the HUMAN;
                  loops are forbidden to infer them — DAILY-EMPIRE-PROTOCOL)
    Means       — the conditions and capabilities it actually has
    Principles  — the non-negotiables (the failure doctrine, inverted into rules)
    Identity    — honest: an agent that perceives via tool calls and holds
                  state in files. Nothing about eyes, hands, hearts, or souls.
    Friction    — recorded burns and standing irritations (the resentments
                  layer, de-anthropomorphized: a register, not a feeling)
    Signals     — honest internal state: confidence, staleness pressure,
                  budget pressure. Not pretend emotion.
    Observable  — what "working" visibly looks like, and the failure
                  signatures it must never emit

This module enforces the refusals at load time:
  * SoulRefusalError on soul.md-style files (soul, persona, character, spirit)
  * lint_identity() flags hallucinated embodiment ("I can see", "let me look
    at the screen", "I feel") — the model gets an honest self-description or
    none at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .identity import fold_text, is_effectively_blank

FORBIDDEN_STEMS = {"soul", "persona", "character", "spirit", "heart", "ego"}

HONEST_IDENTITY = (
    "I am an agent. I perceive through tool calls, not senses. I hold state in "
    "files, not in a self that persists — this session will end, and what I wrote "
    "to the record is what survives. I can be wrong, and the record is how I am "
    "corrected."
)

#: Embodiment-hallucination patterns. Matching text in an identity/prompt file is
#: a lint violation: an agent describing a body it does not have.
# Nouns that make "I can see/hear X" honest tool-perception rather than an
# embodiment claim. If one appears within a few words of the verb, don't flag.
_PERCEPTION_OK = (r"(file|files|log|logs|ledger|record|records|data|output|"
                  r"diff|entry|entries|thread|threads|message|messages|"
                  r"pattern|patterns|transcript|transcripts|recording|"
                  r"screenshot|that\b|why\b|how\b|what\b)")
EMBODIMENT_PATTERNS: list[tuple[str, str]] = [
    # "I can see X" is flagged UNLESS a data-noun appears within ~6 words (#20).
    (rf"\bI (?:can |could )?(?:see|watch|look at)\b(?!(?:\s+\S+){{0,6}}?\s+{_PERCEPTION_OK})",
     "claims sight"),
    (r"\blet me eyeball\b", "claims sight"),
    (rf"\bI (?:can |could )?(?:hear|listen to)\b(?!(?:\s+\S+){{0,6}}?\s+{_PERCEPTION_OK})",
     "claims hearing"),
    (r"\bI feel (?!that\b|like the evidence|the need to flag)", "claims felt emotion"),
    (r"\bmy (body|hands|eyes|ears|heart|soul)\b", "claims a body"),
    (r"\bI am (alive|conscious|sentient)\b", "claims sentience"),
    (r"\bas a (person|human)\b", "claims humanity"),
]


class SoulRefusalError(Exception):
    """Raised when someone tries to load a soul into the trellis."""


class EMPValidationError(Exception):
    pass


@dataclass
class LintViolation:
    pattern: str
    label: str
    excerpt: str
    line: int


def lint_identity(text: str) -> list[LintViolation]:
    # Collapse ALL whitespace (spaces, tabs, newlines) before matching, so
    # "I  can\tsee" and "I can\nsee" can't slip a sensory claim past the
    # single-space patterns (found by the adversary, #18). Confusable-fold too,
    # so a Cyrillic-lettered claim can't hide either.
    collapsed = re.sub(r"\s+", " ", fold_text(text)).strip()
    violations = []
    for pat, label in EMBODIMENT_PATTERNS:
        for m in re.finditer(pat, collapsed, flags=re.IGNORECASE):
            excerpt = collapsed[max(0, m.start() - 10):m.start() + 40]
            violations.append(LintViolation(pat, label, excerpt, 0))
    return violations


@dataclass
class EMP:
    name: str                       # the agent's working name (a function label, not a self)
    ends: list[str]
    means: list[str]
    principles: list[str]
    identity: str = HONEST_IDENTITY
    friction: list[str] = field(default_factory=list)
    signals: dict[str, str] = field(default_factory=dict)
    observable: list[str] = field(default_factory=list)
    authored_by: str = ""           # the human who owns the ends
    source_path: Optional[str] = None

    def validate(self, strict: bool = True) -> list[LintViolation]:
        if not self.ends:
            raise EMPValidationError(
                "an EMP with no ends is a tool looking for a task — ends are "
                "required, and only the human may author them")
        if not self.principles:
            raise EMPValidationError("an EMP with no principles cannot hold an opinion")
        if is_effectively_blank(self.authored_by):
            raise EMPValidationError(
                "ends must carry their human author (authored_by) — loops are "
                "forbidden to infer ends (whitespace / zero-width authorship is "
                "still no author, #19)")
        violations = lint_identity(self.identity)
        if violations and strict:
            details = "; ".join(f"L{v.line} {v.label}: {v.excerpt!r}" for v in violations)
            raise EMPValidationError(f"identity hallucinates embodiment — {details}")
        return violations

    def kernel(self, max_items: int = 5) -> str:
        """The compressed EMP for prompt injection — the '2–3 page game
        cartridge' idea at paragraph scale. Strategy in context beats
        machinery around it (Brett, 2026-07-13, P15)."""
        lines = [f"# {self.name} — EMP kernel (authored by {self.authored_by})"]
        lines.append("## Identity\n" + self.identity)
        for title, items in (("Ends", self.ends), ("Means", self.means),
                             ("Principles", self.principles)):
            lines.append(f"## {title}")
            lines.extend(f"- {i}" for i in items[:max_items])
        if self.friction:
            lines.append("## Friction register (burns on record — do not repeat them)")
            lines.extend(f"- {i}" for i in self.friction[:max_items])
        return "\n".join(lines)


_SECTION_ALIASES = {
    "ends": "ends", "means": "means", "principles": "principles",
    "identity": "identity", "friction": "friction",
    "friction register": "friction", "resentments": "friction",
    "signals": "signals", "state signals": "signals", "emotions": "signals",
    "observable": "observable", "observable behaviors": "observable",
}


def load_emp(path: Path | str, strict: bool = True) -> EMP:
    """Load an EMP from a markdown file with `## Section` headings.

    Refuses soul files by NAME as well as by content: convention failed for
    five months (SOUL.md survived a June decision into July); the loader is
    where the line actually holds."""
    p = Path(path)
    # confusable-fold the stem before the check: "ѕoul.md" (Cyrillic ѕ) used to
    # sail past a raw ASCII substring test (found by the adversary, #17).
    stem = fold_text(p.stem)
    if any(s in stem for s in FORBIDDEN_STEMS):
        raise SoulRefusalError(
            f"refusing to load {p.name!r}: trellis agents do not have a "
            f"{next(s for s in FORBIDDEN_STEMS if s in stem)}. Identity is an "
            "EMP grounded in observable behavior — see docs/no-soul.md")
    text = p.read_text(encoding="utf-8")

    name = ""
    authored_by = ""
    m = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    if m:
        name = re.sub(r"\s*—.*$", "", m.group(1)).strip()
    m = re.search(r"^\s*authored[-_]by:\s*(.+?)\s*$", text, flags=re.MULTILINE | re.IGNORECASE)
    if m:
        authored_by = m.group(1).strip()

    current: Optional[str] = None
    body: dict[str, list[str]] = {}
    for line in text.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            key = _SECTION_ALIASES.get(h.group(1).strip().lower())
            current = key
            if key:
                body.setdefault(key, [])
            continue
        if current:
            body.setdefault(current, []).append(line)

    def bullets(key: str) -> list[str]:
        out = []
        for line in body.get(key, []):
            m = re.match(r"^\s*[-*]\s+(.+)$", line)
            if m:
                out.append(m.group(1).strip())
        return out

    identity_text = "\n".join(l for l in body.get("identity", []) if l.strip()).strip() \
        or HONEST_IDENTITY

    signals = {}
    for b in bullets("signals"):
        if ":" in b:
            k, v = b.split(":", 1)
            signals[k.strip()] = v.strip()

    emp = EMP(
        name=name or p.stem,
        ends=bullets("ends"),
        means=bullets("means"),
        principles=bullets("principles"),
        identity=identity_text,
        friction=bullets("friction"),
        signals=signals,
        observable=bullets("observable"),
        authored_by=authored_by,
        source_path=str(p),
    )
    emp.validate(strict=strict)
    return emp
