"""panel.py — the haiku verifier panel. "Very fragile triangles very strong."

Answers Alex's question directly: *how do we have sub-agent harnessed verifiers
that use haiku agents attached to this harness?*

The shape (Brett's stated #1 priority, 2026-07-12 — "DNA sequencers + haiku
verifiers"):

  * A completion claim is checked by a PANEL of cheap, independent verifiers,
    not one. Each runs in FRESH context (a subagent), on a DIFFERENT lens
    (correctness / freshness / attribution / reproduce), each prompted to
    REFUTE. Diversity, not redundancy — three verifiers asking the same
    question are one verifier with a louder voice.
  * Refute-by-default QUORUM: a claim is CONFIRMED only if a quorum of lenses
    return VERIFIED and NONE returns REFUTED. Any single refutation sinks it;
    a panel that can't tell returns INSUFFICIENT, never a pass.
  * The deterministic RuleVerifier is the floor and runs first — no model
    burns a token on a claim whose files don't even exist.
  * Every lens verdict compounds in the ledger (verify.record_verdict), so
    trust accrues per-maker AND per-lens: you learn WHICH way a maker tends
    to fail.

How the "haiku subagent" attaches (two mounts, both real):

  1. In-harness (this module): a panel of ModelVerifiers, each pinned to a
     cheap provider seat (ClaudeSDKProvider(model="claude-haiku-4-5"), or a
     local Gemma via OpenAICompatProvider). trellis orchestrates; the models
     just judge. Deterministic to test with MockProvider.

  2. Under the Claude Agent SDK: `spawn` describes each lens as a SUBAGENT
     (model=haiku, no write tools, structured output) so the SDK's own
     Agent tool fans them out. `panel_as_subagent_specs()` emits those specs;
     you wire them into your SDK harness. The trellis panel and the SDK
     subagents share one contract: a lensed, refute-oriented verdict.

Cost note (this is a personal agent — Alex, 2026-07-15): a panel is N cheap
calls, not N expensive ones. The maker is Sonnet-class; the panel is Haiku-
class. Verification is where cheap models earn their keep — they are good at
checking even where they are bad at doing (Theo, cited by Brett 2026-07-11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .ledger import Ledger
from .verify import (Check, CompletionClaim, ModelVerifier, RuleVerifier,
                     Verdict, VerdictStatus, record_verdict)

DEFAULT_LENSES = ("correctness", "freshness", "attribution", "reproduce")


@dataclass
class PanelVerdict:
    claim_id: str
    status: VerdictStatus            # the panel's overall call
    lens_verdicts: list[Verdict]
    quorum: int
    verified_count: int
    refuted_count: int
    rationale: str

    @property
    def confirmed(self) -> bool:
        return self.status == VerdictStatus.VERIFIED


class VerifierPanel:
    """N independent lens-verifiers + a deterministic floor, combined by a
    refute-by-default quorum."""

    def __init__(
        self,
        panel_id: str,
        provider,
        lenses: tuple[str, ...] = DEFAULT_LENSES,
        quorum: Optional[int] = None,
        ledger: Optional[Ledger] = None,
        rule_verifier: Optional[RuleVerifier] = None,
    ):
        self.id = panel_id
        self.lenses = lenses
        # default quorum = strict majority of lenses
        self.quorum = quorum or (len(lenses) // 2 + 1)
        self.ledger = ledger
        self.rule_verifier = rule_verifier
        # each lens is its OWN identity, so none can self-certify the maker
        self._verifiers = [
            ModelVerifier(f"{panel_id}:{lens}", provider, lens=lens)
            for lens in lenses
        ]

    def verify(self, claim: CompletionClaim, record: bool = True) -> PanelVerdict:
        lens_verdicts: list[Verdict] = []

        # Floor first: deterministic checks, no model cost. A refuted floor
        # short-circuits — don't pay a panel to judge a claim whose files
        # don't exist.
        if self.rule_verifier is not None:
            floor = self.rule_verifier.verify(claim)
            lens_verdicts.append(floor)
            if floor.status == VerdictStatus.REFUTED:
                pv = PanelVerdict(
                    claim_id=claim.id, status=VerdictStatus.REFUTED,
                    lens_verdicts=lens_verdicts, quorum=self.quorum,
                    verified_count=0, refuted_count=1,
                    rationale="deterministic floor refuted the claim; panel not consulted")
                if record and self.ledger is not None:
                    self._record(claim, pv)
                return pv

        for v in self._verifiers:
            lens_verdicts.append(v.verify(claim))

        model_verdicts = [v for v in lens_verdicts if v.verifier != getattr(
            self.rule_verifier, "id", None)]
        verified = sum(1 for v in model_verdicts if v.status == VerdictStatus.VERIFIED)
        refuted = sum(1 for v in model_verdicts if v.status == VerdictStatus.REFUTED)

        # refute-by-default quorum
        if refuted > 0:
            status = VerdictStatus.REFUTED
            rationale = f"{refuted} lens(es) refuted — any refutation sinks the claim"
        elif verified >= self.quorum:
            status = VerdictStatus.VERIFIED
            rationale = f"{verified}/{len(model_verdicts)} lenses verified, quorum {self.quorum} met, zero refutations"
        else:
            status = VerdictStatus.INSUFFICIENT
            rationale = f"only {verified}/{len(model_verdicts)} verified (quorum {self.quorum}); not enough to confirm"

        pv = PanelVerdict(
            claim_id=claim.id, status=status, lens_verdicts=lens_verdicts,
            quorum=self.quorum, verified_count=verified, refuted_count=refuted,
            rationale=rationale)
        if record and self.ledger is not None:
            self._record(claim, pv)
        return pv

    def _record(self, claim: CompletionClaim, pv: PanelVerdict) -> None:
        # each lens verdict compounds individually (per-lens trust), plus a
        # panel summary entry
        for v in pv.lens_verdicts:
            record_verdict(self.ledger, claim, v)
        self.ledger.append(
            kind="panel_verdict", author=self.id,
            body={"claim_id": claim.id, "maker": claim.maker,
                  "status": pv.status.value, "verified": pv.verified_count,
                  "refuted": pv.refuted_count, "quorum": pv.quorum,
                  "rationale": pv.rationale,
                  "lenses": [{"verifier": v.verifier, "status": v.status.value}
                             for v in pv.lens_verdicts]},
            tags=("verify", "panel", pv.status.value, claim.maker))


def panel_as_subagent_specs(lenses: tuple[str, ...] = DEFAULT_LENSES,
                            model: str = "claude-haiku-4-5") -> list[dict]:
    """Emit Claude Agent SDK subagent specs — one cheap haiku verifier per
    lens — for mounting the panel as SDK subagents (Mode B in docs/claude-sdk.md).

    Each spec is read-only (no write/edit/bash), fresh-context, structured-
    output. Wire the returned list into your ClaudeAgentOptions(agents=...)
    and fan them out with the Agent tool; combine their verdicts with the same
    refute-by-default quorum VerifierPanel uses.
    """
    specs = []
    for lens in lenses:
        specs.append({
            "name": f"verify-{lens}",
            "model": model,
            "description": f"Independent {lens}-lens verifier. Refutes by default.",
            "tools": ["Read", "Grep", "Glob"],   # can open evidence, cannot change it
            "prompt": (ModelVerifier.PROMPT + f"\n\nYOUR LENS ({lens}): "
                       + ModelVerifier.LENSES.get(lens, "")
                       + "\n\nReturn structured output: {status: VERIFIED|REFUTED|"
                         "INSUFFICIENT, reason: str}."),
        })
    return specs
