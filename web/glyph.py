"""glyph.py — the honest self-image. A deterministic SVG INSTRUMENT of the record.

Alex's idea: "the agent draws itself, and it changes as it learns." The earlier
cut drew a little creature — eyes, antennae, a mouth that smiled when trusted. That
was WRONG by the project's own founding principle (D3, the embodiment linter): a
face that emotes is embodiment and performed feeling, the soul leaking back in
through the picture. An honest agent has no face to smile with.

So the self-image is an ABSTRACT INSTRUMENT — a diagram of the record's shape, not
a being: concentric growth rings (age), a filled arc gauge (verification pass-rate),
tick-segments (bodies of work checked), memory nodes, outward notches (unresolved
triangulations — tension, not eyes), and a hue (trust). Every mark is a pure
function of a real ledger number; a `reflection` string states the mapping out
loud. Same stats → same instrument, always. It changes only because the record
changed — real growth, no face, no feeling.

The discipline: SEPARATE evaluation from rendering. `GlyphStats` is the evaluation
(honest numbers). `render_glyph` is the rendering. Nothing in rendering invents
state, and nothing wears a face.
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


def _arc_path(cx: float, cy: float, r: float, start_deg: float, sweep_deg: float) -> str:
    """SVG path for a circular arc — used for the trust gauge. Clamped just under a
    full turn so a 100% arc still renders (a 360° arc has coincident endpoints)."""
    sweep_deg = _clamp(sweep_deg, 0.0, 359.9)
    a0 = math.radians(start_deg)
    a1 = math.radians(start_deg + sweep_deg)
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    large = 1 if sweep_deg > 180 else 0
    return f"M {x0:.2f} {y0:.2f} A {r:.2f} {r:.2f} 0 {large} 1 {x1:.2f} {y1:.2f}"


def render_glyph(stats: GlyphStats, size: int = 240, background: bool = True) -> str:
    """Return a self-contained SVG string — an ABSTRACT INSTRUMENT of the record,
    NOT a face (D3, no-soul). Deterministic in `stats`. Pass background=False to
    omit the panel rect so the instrument can be LAYERED (the self-portrait morph
    draws yesterday's instrument faintly behind today's)."""
    cx = cy = size / 2
    base, accent, darkbg = _hue_for_trust(stats.trust)
    # OUTER RADIUS ← total activity (log: grows fast, then settles)
    R = 0.20 * size + 0.10 * size * _clamp(math.log10(stats.entries + 1) / 3.0, 0, 1.6)
    R = _clamp(R, 0.16 * size, 0.34 * size)

    parts: list[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
                 f'role="img" aria-label="trellis self-image — an abstract instrument of the '
                 f'record, not a face">')
    if background:
        parts.append(f'<rect width="{size}" height="{size}" rx="18" fill="{darkbg}"/>')

    # AGE ← concentric growth rings (tree-ring time), one per ~3 days on the record
    rings = int(_clamp(stats.age_days // 3, 0, 6))
    for i in range(rings):
        rr = R * (0.34 + 0.11 * i)
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rr:.1f}" fill="none" '
                     f'stroke="{accent}" stroke-width="1.4" opacity="{max(0.40 - i*0.05, 0.12):.2f}"/>')

    # MEMORIES ← nodes on an inner ring (held beside the agent)
    mem = int(_clamp(stats.memories, 0, 8))
    for i in range(mem):
        ang = 2 * math.pi * i / max(mem, 1) - math.pi / 2
        px, py = cx + R * 0.30 * math.cos(ang), cy + R * 0.30 * math.sin(ang)
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.6" fill="{accent}" opacity="0.85"/>')

    # VERIFICATION RIGOR ← tick-segments around a mid ring (bodies of work checked)
    checked = int(_clamp(stats.checked, 0, 12))
    for i in range(checked):
        ang = 2 * math.pi * i / max(checked, 1) - math.pi / 2
        x0, y0 = cx + R * 0.66 * math.cos(ang), cy + R * 0.66 * math.sin(ang)
        x1, y1 = cx + R * 0.78 * math.cos(ang), cy + R * 0.78 * math.sin(ang)
        parts.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
                     f'stroke="{accent}" stroke-width="2" opacity="0.9"/>')

    # TRUST ← a filled ARC GAUGE around the perimeter (verification pass-rate).
    # This is the replacement for the old smiling mouth: a gauge, not an expression.
    track_r = R * 0.92
    if stats.trust is None:
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{track_r:.1f}" fill="none" '
                     f'stroke="{accent}" stroke-width="3" stroke-dasharray="3 5" opacity="0.5"/>')
    else:
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{track_r:.1f}" fill="none" '
                     f'stroke="{accent}" stroke-width="3" opacity="0.18"/>')
        frac = _clamp(stats.trust, 0, 1)
        if frac > 0:
            parts.append(f'<path d="{_arc_path(cx, cy, track_r, -90, frac * 360)}" fill="none" '
                         f'stroke="{accent}" stroke-width="5" stroke-linecap="round"/>')

    # OPEN TRIANGULATIONS ← notches pointing OUTWARD beyond the ring — unresolved
    # tension made visible. NOT eyes: the instrument does not watch, it registers.
    open_ts = int(_clamp(stats.open_ts, 0, 8))
    for i in range(open_ts):
        ang = -math.pi / 2 + (i - (open_ts - 1) / 2) * 0.5
        x0, y0 = cx + R * 0.98 * math.cos(ang), cy + R * 0.98 * math.sin(ang)
        x1, y1 = cx + R * 1.16 * math.cos(ang), cy + R * 1.16 * math.sin(ang)
        parts.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
                     f'stroke="{accent}" stroke-width="2.5" opacity="0.9"/>')

    # the record's CORE ← a filled disc, hue = trust (pale when unproven)
    parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{R*0.20:.1f}" fill="{base}" '
                 f'stroke="{accent}" stroke-width="2"/>')
    parts.append('</svg>')
    return "".join(parts)


def reflection(stats: GlyphStats) -> list[str]:
    """The honesty caption: WHY it looks the way it does. Every line ties an
    abstract mark to a real number — no face, no feeling, auditable."""
    lines = []
    lines.append(f"size: grown from {stats.entries} recorded events")
    if stats.trust is None:
        lines.append("hue + gauge: pale, and the outer arc is an empty dashed track — "
                     "no work has been independently checked yet, so trust is unearned "
                     "(not low, unproven)")
    else:
        warmth = "warm" if stats.trust >= 0.66 else "muted" if stats.trust >= 0.4 else "cool/grey"
        lines.append(f"hue + trust gauge: {warmth}; the outer arc is filled to "
                     f"{int(stats.trust*100)}% — the verification pass-rate "
                     f"({stats.verified}/{stats.checked} checked)")
    lines.append(f"verification ticks: {int(_clamp(stats.checked,0,12))} — one segment per "
                 "body of work put through an independent check")
    lines.append(f"memory nodes: {stats.memories} memories held beside it")
    if stats.open_ts == 0:
        lines.append("outer notches: none — no unresolved 'triangulate' decisions")
    else:
        lines.append(f"outer notches: {stats.open_ts} — unresolved 'triangulate' decision(s), "
                     "tension pointing outward")
    lines.append(f"growth rings: {int(_clamp(stats.age_days//3,0,6))} — one per ~3 days "
                 f"on the record ({stats.age_days:.0f}d)")
    lines.append("It is an abstract instrument of the record — no face, no feeling; "
                 "every mark is a real number.")
    return lines
