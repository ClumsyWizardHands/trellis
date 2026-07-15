"""glyph.py — the honest self-image. A deterministic SVG creature drawn from
real ledger stats.

This is the reconciliation of Alex's "the agent draws itself, and it changes as
it learns" idea with the no-soul principle (see docs/ROADMAP-UI-SPINE.md). The
creature is NOT the agent claiming a body or a self. It is a data-visualization
in the shape of a creature: every visual property is a pure function of a real
ledger number, and a `reflection` string states the mapping out loud. Same
stats → same creature, always. It changes only because the underlying record
changed — so watching it evolve is watching real growth, not theater.

The discipline (from the Tamagotchi-3.0 pattern): SEPARATE evaluation from
rendering. `GlyphStats` is the evaluation (honest numbers). `render_glyph` is
the rendering. Nothing in rendering invents state.
"""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GlyphStats:
    decisions: int = 0
    verified: int = 0
    checked: int = 0
    trust: Optional[float] = None      # verified / checked, or None if never checked
    memories: int = 0
    loop_runs: int = 0
    open_ts: int = 0                   # unresolved triangulations → alertness
    age_days: float = 0.0
    entries: int = 0

    @staticmethod
    def from_growth(d: dict) -> "GlyphStats":
        return GlyphStats(
            decisions=d.get("decisions", 0), verified=d.get("verified", 0),
            checked=d.get("checked", 0), trust=d.get("trust"),
            memories=d.get("memories", 0), loop_runs=d.get("loop_runs", 0),
            open_ts=d.get("open_ts", 0), age_days=d.get("age_days", 0.0),
            entries=d.get("entries", 0))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _hue_for_trust(trust: Optional[float]) -> tuple[str, str, str]:
    """Trust → colour. High trust = warm teal-green; low = desaturated grey;
    never-checked = pale neutral (honest: 'not yet earned')."""
    if trust is None:
        base = colorsys.hls_to_rgb(0.58, 0.72, 0.12)   # pale, cool, low-saturation
        accent = colorsys.hls_to_rgb(0.58, 0.55, 0.18)
    else:
        # hue sweeps 0.02 (wary red-grey) → 0.45 (trusted teal-green)
        hue = 0.02 + 0.43 * _clamp(trust, 0, 1)
        sat = 0.25 + 0.55 * _clamp(trust, 0, 1)
        base = colorsys.hls_to_rgb(hue, 0.62, sat)
        accent = colorsys.hls_to_rgb(hue, 0.42, min(1.0, sat + 0.1))
    darkbg = colorsys.hls_to_rgb((0.6 if trust is None else 0.02 + 0.43 * _clamp(trust or 0, 0, 1)),
                                 0.16, 0.25)
    def hx(c): return "#" + "".join(f"{int(_clamp(v,0,1)*255):02x}" for v in c)
    return hx(base), hx(accent), hx(darkbg)


def render_glyph(stats: GlyphStats, size: int = 240) -> str:
    """Return a self-contained SVG string. Deterministic in `stats`."""
    cx = cy = size / 2
    # BODY SIZE ← total activity (log so it grows fast then settles)
    activity = stats.entries
    r = 0.20 * size + 0.10 * size * _clamp(math.log10(activity + 1) / 3.0, 0, 1.6)
    r = _clamp(r, 0.18 * size, 0.36 * size)

    base, accent, darkbg = _hue_for_trust(stats.trust)

    # CREST SPIKES ← verification rigor (how much has been checked)
    spikes = int(_clamp(stats.checked, 0, 9))
    # ANTENNAE ← memories (sensing feelers), capped
    antennae = int(_clamp(1 + stats.memories // 3, 1, 4)) if stats.memories else 0
    # EYES ← alertness from open Ts; calm(2 half-lidded) → watchful(more, wide)
    eye_count = 2 if stats.open_ts == 0 else int(_clamp(2 + stats.open_ts, 2, 6))
    eye_open = 0.35 if stats.open_ts == 0 else _clamp(0.5 + 0.1 * stats.open_ts, 0.5, 1.0)
    # TAIL RINGS ← age (tree-ring style)
    rings = int(_clamp(stats.age_days // 3, 0, 6))

    parts: list[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
                 f'role="img" aria-label="trellis self-image glyph">')
    parts.append(f'<rect width="{size}" height="{size}" rx="18" fill="{darkbg}"/>')

    # tail rings behind the body (age)
    for i in range(rings):
        ry = cy + r * 0.55 + i * (r * 0.14)
        rr = r * (0.5 - i * 0.05)
        op = 0.5 - i * 0.06
        parts.append(f'<circle cx="{cx:.1f}" cy="{ry:.1f}" r="{max(rr,4):.1f}" '
                     f'fill="none" stroke="{accent}" stroke-width="2" opacity="{op:.2f}"/>')

    # crest spikes (verification rigor)
    for i in range(spikes):
        t = (i + 0.5) / max(spikes, 1)
        ang = math.pi * (0.15 + 0.7 * t)   # across the top
        sx = cx - r * math.cos(ang)
        sy = cy - r * math.sin(ang)
        tipx = cx - (r + r * 0.28) * math.cos(ang)
        tipy = cy - (r + r * 0.28) * math.sin(ang)
        parts.append(f'<path d="M {sx-6:.1f} {sy:.1f} L {tipx:.1f} {tipy:.1f} '
                     f'L {sx+6:.1f} {sy:.1f} Z" fill="{accent}" opacity="0.9"/>')

    # antennae (memories)
    for i in range(antennae):
        off = (i - (antennae - 1) / 2) * 14
        ax = cx + off
        parts.append(f'<line x1="{ax:.1f}" y1="{cy - r*0.9:.1f}" x2="{ax:.1f}" '
                     f'y2="{cy - r*1.25:.1f}" stroke="{accent}" stroke-width="2.5"/>')
        parts.append(f'<circle cx="{ax:.1f}" cy="{cy - r*1.28:.1f}" r="4" fill="{base}" '
                     f'stroke="{accent}" stroke-width="1.5"/>')

    # body
    parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{base}" '
                 f'stroke="{accent}" stroke-width="3"/>')

    # eyes (alertness)
    eye_r = _clamp(r * 0.13, 5, 16)
    spread = r * 0.44
    if eye_count <= 2:
        xs = [cx - spread, cx + spread]
    else:
        xs = [cx + (i - (eye_count - 1) / 2) * (spread * 1.4 / max(eye_count - 1, 1))
              for i in range(eye_count)]
    ey = cy - r * 0.08
    for ex in xs:
        parts.append(f'<ellipse cx="{ex:.1f}" cy="{ey:.1f}" rx="{eye_r:.1f}" '
                     f'ry="{eye_r*eye_open:.1f}" fill="#0d1117"/>')
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey - eye_r*0.15:.1f}" '
                     f'r="{eye_r*0.32:.1f}" fill="#ffffff" opacity="0.9"/>')

    # a small mouth: content curve if trusted, flat if wary/unchecked
    mood = 0.0 if stats.trust is None else (stats.trust - 0.5)
    my = cy + r * 0.42
    curve = mood * r * 0.25
    parts.append(f'<path d="M {cx - r*0.22:.1f} {my:.1f} Q {cx:.1f} {my + curve:.1f} '
                 f'{cx + r*0.22:.1f} {my:.1f}" fill="none" stroke="#0d1117" '
                 f'stroke-width="2.5" stroke-linecap="round"/>')

    parts.append('</svg>')
    return "".join(parts)


def reflection(stats: GlyphStats) -> list[str]:
    """The honesty caption: WHY it looks the way it does. Every line ties a
    visual trait to a real number, so the picture is auditable."""
    lines = []
    lines.append(f"size: grown from {stats.entries} recorded events")
    if stats.trust is None:
        lines.append("colour: pale — no work has been independently checked yet, "
                     "so trust is unearned (not low, unproven)")
    else:
        warmth = "warm/green" if stats.trust >= 0.66 else \
                 "muted" if stats.trust >= 0.4 else "wary/grey"
        lines.append(f"colour: {warmth} — verification pass-rate is "
                     f"{int(stats.trust*100)}% ({stats.verified}/{stats.checked} checked)")
    lines.append(f"crest: {int(_clamp(stats.checked,0,9))} spikes — one per body of "
                 "work put through verification")
    lines.append(f"antennae: sensing {stats.memories} memories held beside it")
    if stats.open_ts == 0:
        lines.append("eyes: calm, half-lidded — no unresolved triangulations")
    else:
        lines.append(f"eyes: {int(_clamp(2+stats.open_ts,2,6))}, wide — watching "
                     f"{stats.open_ts} unresolved 'triangulate' decision(s)")
    lines.append(f"tail rings: {int(_clamp(stats.age_days//3,0,6))} — one per ~3 days "
                 f"of accumulated life ({stats.age_days:.0f}d on the record)")
    lines.append("mouth: curves with trust; flat when unproven")
    return lines
