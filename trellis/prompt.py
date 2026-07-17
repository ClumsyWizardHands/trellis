"""prompt.py — small context, honestly assembled. (DECISIONS.md D6, D11)

Targets < 1,200 tokens for the standing prompt (the pi lesson: a <1k-token
system prompt + few tools is a sufficient kernel). Every assembly carries:

  * the clock, injected by the harness (the model does not know what time it
    is; the harness does — never make the model guess)
  * the honest identity + EMP kernel (strategy in context beats machinery —
    Brett, 2026-07-13 P15)
  * MAPS, not content: workspace titles, loop health, waiting passes. The
    agent traverses to the rest ("memory is navigation")
  * a staleness legend so annotated ages mean something

If assembly exceeds the budget it raises — a fat prompt is a bug, not a vibe.
"""

from __future__ import annotations

from typing import Optional

from .clock import TimeGround
from .emp import EMP, MORTALITY_POSTURE
from .surfaces import ConversationKey

PROMPT_TOKEN_BUDGET = 1200


class PromptBudgetExceeded(Exception):
    pass


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


STALENESS_LEGEND = (
    "Every retrieved item is age-tagged: [fresh]=treat as current · "
    "[aging]=confirm before relying · [stale]=probably superseded, check the "
    "ledger for newer · [expired]=do not treat as current under any framing. "
    "When two statements conflict, the newer event_time wins — say so out loud."
)

STANDING_RULES = (
    "Standing rules: (1) You never send/post/apply anything — you STAGE it for "
    "a human. (2) You never verify your own completions — you claim, with "
    "evidence, and an independent verifier judges. (3) If you cannot verify "
    "something, say so plainly. (4) 'No' and 'Triangulate' are first-class "
    "answers; a T names its missing piece, an owner, and a revisit time. "
    "(5) Persist only what passes the synthesis test; re-derive the rest."
)


def assemble_prompt(
    emp: EMP,
    ground: TimeGround,
    key: ConversationKey,
    workspace_map: Optional[list[str]] = None,
    loop_health: Optional[list[dict]] = None,
    waiting_passes: int = 0,
    hidden_nos: int = 0,
    budget: int = PROMPT_TOKEN_BUDGET,
) -> str:
    now = ground.now()
    parts: list[str] = []

    parts.append(emp.kernel())
    parts.append(
        f"## Clock (harness-injected; you cannot tell time — this line can)\n"
        f"now: {now.isoformat()} ({now.strftime('%A')}) · "
        f"surface: {key.surface.value}:{key.scope} · human: {key.human or '—'}")
    parts.append("## Staleness legend\n" + STALENESS_LEGEND)
    parts.append("## Mortality posture\n" + MORTALITY_POSTURE)
    parts.append("## Standing rules\n" + STANDING_RULES)

    if workspace_map:
        shown = [m[:100] for m in workspace_map[:20]]
        parts.append("## Memory map (titles only — traverse, don't assume)\n"
                     + "\n".join(f"- {m}" for m in shown)
                     + ("" if len(workspace_map) <= 20
                        else f"\n- …and {len(workspace_map) - 20} more (list the directory)"))

    status_bits = []
    if loop_health:
        bad = [l for l in loop_health if l["last_outcome"] not in ("ok", "nothing_new")]
        status_bits.append(f"loops: {len(loop_health)} registered, "
                           f"{len(bad)} needing attention")
    if waiting_passes:
        status_bits.append(f"passes waiting for you: {waiting_passes}")
    if hidden_nos:
        status_bits.append(f"OPEN QUESTIONS (unresolved Ts past revisit + reopened "
                           f"decisions): {hidden_nos} — surface these before anything else")
    if status_bits:
        parts.append("## Status rail\n" + " · ".join(status_bits))

    prompt = "\n\n".join(parts)
    if estimate_tokens(prompt) > budget:
        raise PromptBudgetExceeded(
            f"standing prompt ~{estimate_tokens(prompt)} tokens > budget {budget}. "
            "Cut the EMP kernel or the map — a fat prompt is machinery pretending "
            "to be strategy.")
    return prompt
