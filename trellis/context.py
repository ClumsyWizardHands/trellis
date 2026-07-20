"""context.py — the context compiler: reload the read before forming an opinion.

The Codex context-engineering audit's central finding (2026-07-20): the Witness
forms opinions on the CURRENT BATCH without reconstructing its prior read, the
relevant prior decisions, corrections, open obligations, or verification history —
it writes `current-read.md` and never reads it back. So the doctrine describes a
longitudinal contextual witness while the implemented loop is closer to a grounded
stateless cycle. This module builds the missing piece: a **deterministic,
inspectable context compiler**.

The compiler is normal software, not a model — the model interprets a prepared
packet; it does not decide from scratch which history it should have remembered.
For each cycle it:

  * RELOADS the prior read (the missing input),
  * pulls the ACTIVE decisions whose question touches the current subjects (with
    verdict, rationale, lineage),
  * surfaces the FULL open obligations (hidden nos, reopened heads, stale
    curiosities) touching those subjects — never a bare count,
  * includes recent CORRECTIONS (supersessions) and VERIFICATION outcomes so the
    read is time-correct and confidence is grounded,
  * enforces privacy at selection (a DM-scoped item is EXCLUDED from a public
    surface, its content never leaked — only the exclusion is recorded),
  * emits a **ContextManifest**: exactly what was included and why, and what was
    excluded and why — so an eloquent model answer can't hide a bad retrieval, and
    the compilation itself is auditable and testable.

Honest scope (first version): this reloads and manifests real ledger state
deterministically. It does NOT yet implement the audit's full epistemic type
lattice, the separate read-delta output schema, or the 12 gold-scenario eval
program — those are the next steps (docs/audits/CONTEXT-ENGINEERING-AUDIT-2026-07-20.md).
What it does close is the load-bearing gap: the opinion is now formed over the
prior read + relevant history, not the current batch alone, and the packet is
inspectable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .clock import TimeGround
from .curiosity import QUESTION_KIND, QuestionLog
from .decisions import DecisionLog
from .ledger import Entry, Ledger


def _kw(text: str) -> set:
    """Keyword set for deterministic relevance — length>=3 words, folded."""
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 3}


def _overlap(a: set, b: set) -> int:
    return len(a & b)


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


ItemType = str   # "prior_read" | "decision" | "obligation" | "correction" | "verification"


@dataclass(frozen=True)
class ContextItem:
    type: ItemType
    source_id: str          # a ledger entry id / path — openable
    summary: str            # the compiled, human-legible content
    selection_reason: str   # WHY it was included (auditable)
    token_cost: int
    mandatory: bool = False  # obligations/corrections are never dropped for budget


@dataclass
class ContextManifest:
    """The auditable record of what the model saw and did not see this cycle."""
    surface_key: str
    subjects: list[str]
    included: list[ContextItem] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)   # {source_id, type, reason}
    tokens_used: int = 0
    tokens_budget: int = 0

    def to_dict(self) -> dict:
        return {
            "surface_key": self.surface_key,
            "subjects": list(self.subjects),
            "budgets": {"tokens_budget": self.tokens_budget, "tokens_used": self.tokens_used},
            "included": [{"type": i.type, "source_id": i.source_id,
                          "selection_reason": i.selection_reason,
                          "token_cost": i.token_cost, "mandatory": i.mandatory}
                         for i in self.included],
            "excluded": list(self.excluded),
        }


@dataclass
class CompiledContext:
    manifest: ContextManifest
    items: list[ContextItem]

    def to_prompt_block(self) -> str:
        """The compiled context as a bounded prompt section — grouped by type, so
        the model reads its prior read and relevant history, not raw spans."""
        if not self.items:
            return ""
        groups: dict[str, list[ContextItem]] = {}
        for it in self.items:
            groups.setdefault(it.type, []).append(it)
        titles = {"prior_read": "Your prior read (reloaded — this is what you last understood)",
                  "obligation": "Open obligations touching these subjects (surface before anything else)",
                  "correction": "Recent corrections (newer supersedes older — say so out loud)",
                  "decision": "Relevant prior decisions (what was already decided, and why)",
                  "verification": "Recent verification outcomes (ground your confidence)"}
        order = ["prior_read", "obligation", "correction", "decision", "verification"]
        out = ["## Compiled context (deterministic; see the manifest for what was excluded)"]
        for t in order:
            if t not in groups:
                continue
            out.append(f"### {titles.get(t, t)}")
            out.extend(f"- {it.summary}" for it in groups[t])
        return "\n".join(out)


class ContextCompiler:
    """Reload the read and the relevant history before an opinion is formed."""

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None,
                 decisions: Optional[DecisionLog] = None,
                 questions: Optional[QuestionLog] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground
        self.decisions = decisions or DecisionLog(ledger, self.ground)
        self.questions = questions or QuestionLog(ledger, self.ground)

    def compile(self, subjects: list[str], surface_key: str = "",
                budget_tokens: int = 3000, read_prefix: str = "read",
                surface_scope: Optional[str] = None) -> CompiledContext:
        """Compile the context packet for a cycle about `subjects`. Mandatory
        items (obligations, corrections) are included first and never dropped;
        relevant decisions are relevance-scored and included until the budget is
        spent; every exclusion is recorded with a reason."""
        want = set()
        for s in subjects:
            want |= _kw(s)

        man = ContextManifest(surface_key=surface_key, subjects=list(subjects),
                              tokens_budget=budget_tokens)
        chosen: list[ContextItem] = []
        used = 0

        def add(item: ContextItem) -> bool:
            nonlocal used
            if not item.mandatory and used + item.token_cost > budget_tokens:
                man.excluded.append({"source_id": item.source_id, "type": item.type,
                                     "reason": "over token budget"})
                return False
            chosen.append(item)
            man.included.append(item)
            used += item.token_cost
            return True

        # (1) PRIOR READ — the missing input. Reloaded from the active read notes.
        for e in self.ledger.active("memory_write"):
            path = e.body.get("path", "")
            if not path.startswith(read_prefix):
                continue
            title = e.body.get("title", path)
            # privacy: a read scoped to a different DM/surface is excluded, not leaked
            if surface_scope is not None and e.body.get("scope") not in (None, "", surface_scope):
                man.excluded.append({"source_id": e.id, "type": "prior_read",
                                     "reason": "scoped to another surface (privacy)"})
                continue
            summary = f"[{title}] (open {path} to walk the full read)"
            add(ContextItem("prior_read", e.id, summary,
                            "the read you last wrote — reloaded so you don't relearn cold",
                            _est_tokens(summary), mandatory=True))

        # (2) OPEN OBLIGATIONS touching the subjects — full objects, never a count.
        for e in self.decisions.open_questions():
            subj = e.body.get("subject", "")
            rel = _overlap(want, _kw(subj)) if want else 1
            if rel == 0:
                continue
            verdict = e.body.get("verdict", "")
            summary = (f"OPEN [{verdict}] {subj} — owner {e.body.get('owner') or '—'}, "
                       f"missing {e.body.get('missing') or '—'} (decision {e.body.get('decision_id')})")
            add(ContextItem("obligation", e.id, summary,
                            "an unresolved T/reopened head on a current subject", _est_tokens(summary),
                            mandatory=True))
        for q in self.questions.stale():
            assumption = q.body.get("assumption", "")
            rel = _overlap(want, _kw(assumption)) if want else 1
            if rel == 0:
                continue
            summary = (f"STALE QUESTION: {q.body.get('title')} — assuming '{assumption}'; "
                       f"would resolve: {q.body.get('what_would_resolve')}")
            add(ContextItem("obligation", q.id, summary,
                            "an overdue curiosity on a current subject", _est_tokens(summary),
                            mandatory=True))

        # (3) CORRECTIONS touching the subjects — supersessions, newest-wins made visible.
        for e in self.ledger.entries():
            if not e.supersedes or e.kind != "decision":
                continue
            if e.id not in {x.id for x in self.ledger.active("decision")}:
                continue   # only live heads that are corrections
            subj = e.body.get("subject", "")
            if want and _overlap(want, _kw(subj)) == 0:
                continue
            old = self.ledger.get(e.supersedes)
            oldsubj = old.body.get("subject", "?") if old else "?"
            summary = (f"CORRECTED: '{oldsubj}' → now '{subj}' [{e.body.get('verdict')}] "
                       f"(the earlier version is superseded, kept in lineage)")
            add(ContextItem("correction", e.id, summary,
                            "a decision on a current subject was corrected", _est_tokens(summary),
                            mandatory=True))

        # (4) RELEVANT DECISIONS — relevance-scored, budget-bounded.
        scored = []
        for e in self.ledger.active("decision"):
            if e.id in {i.source_id for i in chosen}:
                continue
            subj = e.body.get("subject", "")
            score = _overlap(want, _kw(subj)) if want else 0
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda p: (-p[0], p[1].stamp.event_time.isoformat()))
        for score, e in scored:
            summary = (f"[{e.body.get('verdict')}] {e.body.get('subject')} — "
                       f"{e.body.get('rationale', '')[:120]}")
            add(ContextItem("decision", e.id, summary,
                            f"relevant to the subjects (keyword overlap {score})",
                            _est_tokens(summary)))

        # (5) VERIFICATION outcomes — recent, so confidence is grounded not assumed.
        verifs = [e for e in self.ledger.entries() if e.kind == "verification"]
        for e in verifs[-3:]:
            summary = (f"verification: {e.body.get('task', '?')} → {e.body.get('status')} "
                       f"(maker {e.body.get('maker')}, checked by {e.author})")
            add(ContextItem("verification", e.id, summary,
                            "a recent independent check — ground your confidence on it",
                            _est_tokens(summary)))

        man.tokens_used = used
        return CompiledContext(manifest=man, items=chosen)
