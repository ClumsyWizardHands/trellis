#!/usr/bin/env python3
"""Seed a rich demo ledger so the web UI has something living to show, and
regenerate the committed glyph assets. Deterministic (fixed clock).

    python3 web/demo_seed.py

Writes web/demo/ledger.jsonl and docs/assets/glyph-*.svg|png (PNGs need cairosvg).
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trellis.clock import TimeGround
from trellis.ledger import Ledger
from trellis.decisions import Decision, DecisionLog, POV, Verdict
from trellis.stage import Outbox, StagedAction
from trellis.loops import LoopRegistry, LoopRun, LoopSpec, Outcome, BlockKind
from trellis.memory import Workspace
from trellis.reflect import ReflectionRitual, SelfChange
from trellis.verify import (CompletionClaim, Evidence, EvidenceKind, RuleVerifier,
                            record_verdict)
from web.glyph import GlyphStats, render_glyph

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 15, 17, 0, tzinfo=timezone.utc)


def at(days=0, hours=0):
    return NOW - timedelta(days=days, hours=hours)


def seed_ledger() -> Ledger:
    demo = ROOT / "web" / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    p = demo / "ledger.jsonl"
    if p.exists():
        p.unlink()
    g = TimeGround(now_fn=lambda: NOW)
    L = Ledger(p, g)
    log = DecisionLog(L, g)
    ws = Workspace(demo / "ws", L)

    d_time = log.record(Decision("Treat time-blindness as an asset, not just a defect", Verdict.Y,
        "Brett's July framing supersedes the April 'eliminate' framing", "witness",
        "EMP:ends[0]"), event_time=at(1))
    d_digest = log.record(Decision("Auto-post the morning digest to #chiefs", Verdict.N,
        "stage-don't-fire is doctrine; nothing auto-posts", "witness",
        "EMP:principles[0]", returnable_note="reopen if team ratifies autonomous posting"),
        event_time=at(0, 3))
    povs = [POV("brett", "memory beside the agent; the agent dies"),
            POV("clare", "mount the protocol folder; server-wide memory"),
            POV("sarah", "workflow-first; route around the unreliable agent")]
    log.record(Decision("Memory: on the agent or beside it?", Verdict.T,
        "live architectural fork the team is building in opposite directions on", "witness",
        "EMP:principles[1]", povs=povs, owner="alex", missing="a cost comparison",
        revisit_at=at(-4)), event_time=at(2))
    log.record(Decision("System of record: Obsidian vs Drive vs ledger", Verdict.T,
        "deferred in favour of verification, but still unsettled", "witness",
        "EMP:means[0]", povs=povs, owner="alex", missing="whether verification changes it",
        revisit_at=at(2)), event_time=at(9))

    for pth, title, why in [
        ("read/current-read.md", "The current read on the CF account",
         "the current synthesized read exists nowhere else"),
        ("epitaphs/2026-07-14-s1.md", "Epitaph — session 2026-07-14 (open threads)",
         "session-final open threads exist nowhere else once the window closes"),
        ("skills/end-of-day-harvest.md", "Skill: the end-of-day harvest routine",
         "a learned routine the team could not re-derive mechanically")]:
        ws.write(pth, f"# {title}\n\n" + "synthesised body " * 18, "witness", why, title=title)

    # yesterday's reflection — snapshots a smaller record, so today shows deltas
    refl = ReflectionRitual(L, author="witness",
                            verifier=RuleVerifier("verifier:reflect-check", L, g), ground=g)
    refl.run("s-2026-07-14",
             "held the read and put the day's opinions on the record",
             "Peter's asks are about findability, not features — a synthesized read "
             "that lives in no single transcript",
             event_time=at(1))

    reg = LoopRegistry(L, g)
    spec = LoopSpec("witness.watch", "keep the read current; put opinions on the record",
                    "witness__channel__chiefs__-__-", max_turns=6,
                    stop_condition="read current")
    reg.register(spec, "alex")
    checker = RuleVerifier("verifier:witness-check", L, g)
    f = str(demo / "ws" / "read" / "current-read.md")
    for i in range(6):
        with LoopRun(spec, reg, actor="witness") as run:
            run.tick()
            if i == 5:
                run.nothing_new(checked=["#chiefs", "#general"])
            else:
                run.ok("recorded opinions; read updated", evidence=[f])
        if i < 5:
            c = CompletionClaim(maker="witness", task="keep the read current",
                                summary="recorded opinions; read updated",
                                evidence=[Evidence(EvidenceKind.FILE, f)])
            record_verdict(L, c, checker.verify(c))
    bad = CompletionClaim(maker="witness", task="x", summary="y",
                          evidence=[Evidence(EvidenceKind.FILE, str(demo / "ws" / "nope.md"))])
    record_verdict(L, bad, checker.verify(bad))

    spec2 = LoopSpec("digest.assembler", "assemble the morning surface", "k2",
                     max_turns=4, stop_condition="assembled")
    reg.register(spec2, "alex")
    for _ in range(2):
        with LoopRun(spec2, reg, actor="witness") as run:
            run.tick()
            run.blocked(BlockKind.NEEDS_INPUT, on="pricing canon from Brett")

    # a trigger re-surfaces the settled 'auto-post' N — it does NOT flip it; it
    # marks it as needing re-triangulation (shows on the attention rail).
    log.reopen(d_digest.body["decision_id"],
               "the team asked about autonomous posting again in standup", "alex",
               event_time=at(0, 2))

    box = Outbox(L, g)
    box.stage(StagedAction("discord_post", "#chiefs-of-staffs",
        "Read updated: July framing of time-blindness adopted; canvas question is a live T owned by Alex.",
        created_by="witness"))
    box.stage(StagedAction("email_draft", "peter@turntwo.org",
        "Draft: the CF pricing one-pager (needs your review before it goes anywhere near a CEO).",
        created_by="witness"))

    # today's reflection — the full record, with a self-change staged as a
    # VERIFIED proposal (an independent verifier confirms it before it may act).
    refl.run("s-2026-07-15",
             "kept the read current; surfaced two live triangulations and one "
             "re-opened question",
             "the team is building memory in opposite directions; that fork is the "
             "day's defining tension and belongs on the record verbatim",
             self_change=SelfChange(
                 target="EMP:friction (append)",
                 proposal="record the recurring ownership burn so a future session "
                          "does not repeat it",
                 rationale="the burn recurred and is grounded in the decisions on record",
                 evidence_ids=[d_time.id, d_digest.id]),
             event_time=NOW)
    return L


def regen_glyphs():
    stages = {
        "glyph-1-newborn": GlyphStats(entries=2),
        "glyph-2-learning": GlyphStats(entries=28, decisions=6, verified=3, checked=4,
                                       trust=0.75, memories=3, open_ts=1, age_days=6),
        "glyph-3-trusted": GlyphStats(entries=140, decisions=34, verified=30, checked=33,
                                      trust=0.91, memories=9, open_ts=0, age_days=27),
        "glyph-4-wary": GlyphStats(entries=90, decisions=22, verified=9, checked=20,
                                   trust=0.45, memories=5, open_ts=4, age_days=15),
    }
    assets = ROOT / "docs" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name, s in stages.items():
        (assets / f"{name}.svg").write_text(render_glyph(s, size=200), encoding="utf-8")
    try:
        import cairosvg
        for name in stages:
            cairosvg.svg2png(url=str(assets / f"{name}.svg"),
                             write_to=str(assets / f"{name}.png"),
                             output_width=200, output_height=200)
    except ImportError:
        print("(cairosvg not installed — SVGs written, PNGs skipped)")


if __name__ == "__main__":
    L = seed_ledger()
    print(f"seeded {len(L.entries())} entries → web/demo/ledger.jsonl")
    regen_glyphs()
    print("regenerated docs/assets/glyph-*")
