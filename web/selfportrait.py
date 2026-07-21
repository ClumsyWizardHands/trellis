"""selfportrait.py — the daily self-portrait that builds on the previous day.

Alex, 2026-07-20: "each day the agent makes an image that represents its current
state, and each image builds upon the last so it's constantly reflecting on the
previous day."

The honest version of that idea — the one that survives the no-soul / dread-lint
doctrine. The trap is an agent that free-generates "what I feel like today"; that
is performed selfhood, the soul leaking back in through the picture. So instead:

  * Every visual trait is STILL a deterministic function of that day's ledger
    snapshot (`reflect.self_image_stats`, already snapshotted into every
    reflection_log). The agent never paints itself however it feels — the record
    paints it. Same snapshot → same portrait, always.
  * "Builds on the previous day" is made literal and honest three ways: today's
    portrait is drawn with YESTERDAY's self-image as a faint ghost behind it (today
    visibly grows out of yesterday); a MORPH crossfades yesterday → today (the
    change you see IS the change in the record); and the growth STRIP shows the
    whole bitemporal chain. Continuity is real because it interpolates two REAL
    snapshots — it invents nothing.

So this is a data-visualization of the agent's own evolution, not a mood board.
It reads the snapshot chain the reflection ritual already writes; it adds no new
authority and no performed feeling.
"""

from __future__ import annotations

from typing import Optional

from .glyph import GlyphStats, reflection, render_glyph

REFLECTION_KIND = "reflection_log"


def snapshot_series(ledger, include_live: bool = True) -> list[tuple[str, GlyphStats]]:
    """The bitemporal chain of daily self-images, oldest → newest: one
    (date, GlyphStats) per reflection_log snapshot, plus today's LIVE stats last
    (so the portrait reflects the record right now, not only the last ritual)."""
    out: list[tuple[str, GlyphStats]] = []
    for e in ledger.entries():
        if e.kind != REFLECTION_KIND:
            continue
        snap = e.body.get("self_image")
        if snap:
            out.append((e.stamp.event_time.date().isoformat(),
                        GlyphStats.from_growth(snap)))
    out.sort(key=lambda p: p[0])
    if include_live:
        from trellis.reflect import self_image_stats
        live = GlyphStats.from_growth(self_image_stats(ledger))
        # only append if it actually differs from the last snapshot (else it is
        # the same day, already shown)
        if not out or out[-1][1] != live:
            out.append((ledger.ground.now().date().isoformat(), live))
    return out


def render_self_portrait(today: GlyphStats, prev: Optional[GlyphStats] = None,
                         size: int = 240) -> str:
    """Today's self-portrait, drawn with yesterday's self-image as a faint ghost
    behind it — the agent's current state, visibly grown out of the previous day.
    Deterministic in (prev, today)."""
    from .glyph import _hue_for_trust
    _, _, darkbg = _hue_for_trust(today.trust)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
             f'role="img" aria-label="trellis daily self-portrait">',
             f'<rect width="{size}" height="{size}" rx="18" fill="{darkbg}"/>']
    if prev is not None and prev != today:
        # yesterday, faint and slightly smaller, behind today — "built upon"
        ghost = render_glyph(prev, size=size, background=False)
        inner = ghost.split(">", 1)[1].rsplit("</svg>", 1)[0]
        parts.append(f'<g opacity="0.22" transform="translate({size*0.03:.1f},'
                     f'{size*0.03:.1f}) scale(0.94)" transform-origin="center">{inner}</g>')
    figure = render_glyph(today, size=size, background=False)
    parts.append(figure.split(">", 1)[1].rsplit("</svg>", 1)[0])
    parts.append("</svg>")
    return "".join(parts)


def render_morph(prev: GlyphStats, today: GlyphStats, size: int = 240,
                 seconds: float = 3.0) -> str:
    """An SVG that crossfades yesterday → today and holds — 'reflecting on the
    previous day' as motion. Declarative SMIL animation: no clock, no randomness,
    fully deterministic in (prev, today)."""
    from .glyph import _hue_for_trust
    _, _, darkbg = _hue_for_trust(today.trust)
    def inner(stats):
        s = render_glyph(stats, size=size, background=False)
        return s.split(">", 1)[1].rsplit("</svg>", 1)[0]
    half = seconds / 2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
             f'role="img" aria-label="trellis self-portrait morph, yesterday to today">',
             f'<rect width="{size}" height="{size}" rx="18" fill="{darkbg}"/>']
    # yesterday: visible, then fades out
    parts.append(f'<g opacity="1">{inner(prev)}'
                 f'<animate attributeName="opacity" values="1;1;0;0" '
                 f'keyTimes="0;0.33;0.66;1" dur="{seconds}s" repeatCount="indefinite"/></g>')
    # today: fades in and holds
    parts.append(f'<g opacity="0">{inner(today)}'
                 f'<animate attributeName="opacity" values="0;0;1;1" '
                 f'keyTimes="0;0.33;0.66;1" dur="{seconds}s" repeatCount="indefinite"/></g>')
    parts.append("</svg>")
    return "".join(parts)


def render_growth_strip(series: list[tuple[str, GlyphStats]], cell: int = 96,
                        max_cells: int = 7) -> str:
    """The bitemporal chain as a time-lapse strip — the last N daily portraits in
    order, so the whole evolution is visible at a glance. Deterministic."""
    shown = series[-max_cells:]
    n = len(shown)
    if n == 0:
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {cell} {cell}"></svg>'
    w = cell * n
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {cell + 18}" '
             f'role="img" aria-label="trellis self-image over time">']
    for i, (date, stats) in enumerate(shown):
        g = render_glyph(stats, size=cell, background=True)
        inner = g.split(">", 1)[1].rsplit("</svg>", 1)[0]
        parts.append(f'<g transform="translate({i*cell},0)">{inner}'
                     f'<text x="{cell/2:.0f}" y="{cell+13}" text-anchor="middle" '
                     f'font-size="9" fill="#8b949e">{date[5:]}</text></g>')
    parts.append("</svg>")
    return "".join(parts)


def portrait_delta(prev: Optional[GlyphStats], today: GlyphStats) -> list[str]:
    """Honest caption: today described RELATIVE to yesterday — every line a real
    number moving. This is 'reflecting on the previous day' in words, tied to the
    record so the change is auditable (never a mood)."""
    if prev is None:
        return ["first portrait on the record — nothing to compare to yet."] + reflection(today)
    lines = []
    def delta(label, a, b, fmt=lambda x: str(x)):
        if a != b:
            arrow = "↑" if (b or 0) > (a or 0) else "↓"
            lines.append(f"{label}: {fmt(a)} → {fmt(b)} {arrow}")
    delta("recorded events", prev.entries, today.entries)
    delta("decisions", prev.decisions, today.decisions)
    delta("independently checked", prev.checked, today.checked)
    if prev.trust != today.trust:
        pt = "—" if prev.trust is None else f"{int(prev.trust*100)}%"
        tt = "—" if today.trust is None else f"{int(today.trust*100)}%"
        lines.append(f"trust (verification pass-rate): {pt} → {tt}")
    delta("open triangulations (alertness)", prev.open_ts, today.open_ts)
    delta("memories held beside it", prev.memories, today.memories)
    if not lines:
        lines.append("no change since yesterday — the record held steady, so the "
                     "portrait did too (honest stillness, not a frozen image).")
    return lines
