"""agent.py — the Witness: contextual understanding, principled opinion.
(DECISIONS.md D12)

This is the agent shape trellis exists for — NOT a task-completer:

  "an agent that is tasked with contextually understanding something and not
   being a taskmaster… able to express an opinion through principles, and in
   fact, not necessarily completing something." — Alex, 2026-07-15
  "I want agents that tell you what they learned and are learning, not just
   what they made for you." — Brett, 2026-07-13

The Witness:
  * ingests events from a surface (messages, transcripts, files) with real
    event-times — never pretending it was there
  * maintains a READ: a current, EMP-grounded understanding, persisted beside
    it (memory dies with the session; the read does not)
  * emits OPINIONS as Y/N/T decisions with lineage — including N, including
    T-with-a-named-missing-piece
  * its stopping condition is "my read is current and my opinions are on the
    record" — never "the task list is empty"
  * everything outbound is staged; every run ends in a typed outcome; every
    completion claim is verified by someone else

The loop is the June spec's state machine, kept:
    sense → resolve → act → verify → remember
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .clock import TimeGround
from .decisions import Decision, DecisionLog, POV, Verdict
from .emp import EMP
from .ledger import Ledger
from .loops import LoopRegistry, LoopRun, LoopSpec, Outcome
from .memory import Workspace
from .passes import PassExchange
from .prompt import assemble_prompt
from .providers.base import Provider, ProviderResponse
from .stage import Outbox, StagedAction
from .surfaces import ConversationKey
from .verify import (CompletionClaim, Evidence, EvidenceKind, RuleVerifier,
                     record_verdict)


@dataclass(frozen=True)
class Event:
    """Something that happened on a surface. event_time is when it HAPPENED —
    an agent ingesting last week's transcript is reading the past and must
    know it."""
    source: str          # who/where
    content: str
    event_time: datetime


@dataclass
class Opinion:
    """A proposed decision from the model, before it becomes a Decision.
    The harness validates it into the Y/N/T grammar; malformed opinions are
    returned to the model, not silently accepted."""
    subject: str
    verdict: str         # "Y" | "N" | "T"
    rationale: str
    emp_lineage: str
    povs: list[dict] = field(default_factory=list)
    owner: Optional[str] = None
    revisit_days: Optional[int] = None
    missing: Optional[str] = None


OPINION_INSTRUCTIONS = (
    "Respond ONLY with a JSON array of opinions. Each opinion: "
    '{"subject": str, "verdict": "Y"|"N"|"T", "rationale": str (plain language), '
    '"emp_lineage": "which End or Principle this expresses, e.g. EMP:principles[2]", '
    '"povs": [{"holder": str, "position": str, "basis": str}] (>=3 for T), '
    '"owner": str (T only), "revisit_days": int (T only), "missing": str (T only)}. '
    "An empty array [] is a legitimate answer meaning: nothing here moved my read. "
    "Do not manufacture opinions to seem useful — that is the sycophancy defect."
)


class Witness:
    def __init__(
        self,
        emp: EMP,
        provider: Provider,
        ledger: Ledger,
        workspace: Workspace,
        key: ConversationKey,
        exchange: Optional[PassExchange] = None,
        ground: Optional[TimeGround] = None,
        verifier: Optional[RuleVerifier] = None,
    ):
        self.emp = emp
        self.provider = provider
        self.ledger = ledger
        self.workspace = workspace
        self.key = key
        self.exchange = exchange
        self.ground = ground or ledger.ground
        self.decisions = DecisionLog(ledger, self.ground)
        self.loops = LoopRegistry(ledger, self.ground)
        self.outbox = Outbox(ledger, self.ground)
        self.id = f"witness:{emp.name.lower().replace(' ', '-')}"
        # The verifier is a DIFFERENT identity by construction:
        self.verifier = verifier or RuleVerifier(f"rule-verifier:{emp.name.lower()}-check",
                                                 ledger=ledger, ground=self.ground)

    # ----- the working loop --------------------------------------------------

    def witness_cycle(self, events: list[Event], spec: Optional[LoopSpec] = None) -> Outcome:
        """One bounded cycle: sense → resolve → act → verify → remember."""
        spec = spec or LoopSpec(
            name=f"{self.id}.witness",
            purpose="keep the read current; put opinions on the record",
            surface_key=self.key.storage_key(),
            max_turns=6,
            stop_condition="read updated and opinions recorded (possibly zero)",
        )
        with LoopRun(spec, self.loops, actor=self.id) as run:
            # SENSE — annotate every event with its true age before the model sees it
            sensed = [
                self.ground.annotate(f"{e.source}: {e.content}", e.event_time,
                                     volatility="conversation")
                for e in events
            ]
            if not run.tick():
                return Outcome.BUDGET_EXCEEDED

            # RESOLVE — ask the model for opinions in the Y/N/T grammar
            opinions = self._resolve(sensed, run)

            # ACT — record decisions; stage (never fire) anything outbound
            recorded = []
            for op in opinions:
                d = self._to_decision(op)
                entry = self.decisions.record(d)
                recorded.append(entry.id)

            # remember — update the read beside us, then claim
            read_path = self._update_read(sensed, opinions)

            if not opinions:
                run.nothing_new(checked=[e.source for e in events] or ["(no events)"])
            else:
                claim = CompletionClaim(
                    maker=self.id,
                    task=spec.purpose,
                    summary=f"recorded {len(recorded)} opinion(s); read updated",
                    evidence=[
                        Evidence(EvidenceKind.FILE, read_path, "the updated read"),
                        *[Evidence(EvidenceKind.LEDGER, rid, "recorded decision")
                          for rid in recorded],
                    ],
                    loop_run_id=run.run_id,
                )
                run.ok(claim.summary, evidence=[e.ref for e in claim.evidence])
                # VERIFY — by someone who is not us (post-run so the run exists)
                self._pending_claim = claim
        outcome = Outcome(self.loops.recent_outcomes(spec.name, 1)[0])
        if outcome == Outcome.OK and getattr(self, "_pending_claim", None) is not None:
            verdict = self.verifier.verify(self._pending_claim)
            record_verdict(self.ledger, self._pending_claim, verdict)
            self._pending_claim = None
        return outcome

    # ----- pieces -------------------------------------------------------------

    def _resolve(self, sensed: list[str], run: LoopRun) -> list[Opinion]:
        system = assemble_prompt(
            self.emp, self.ground, self.key,
            workspace_map=self.workspace.map(),
            loop_health=self.loops.health_report(),
            waiting_passes=len(self.exchange.inbox(self.id)) if self.exchange else 0,
            hidden_nos=len(self.decisions.open_questions()),
        )
        user = ("Events on your surface (age-tagged; newer supersedes older):\n"
                + "\n".join(sensed) + "\n\n" + OPINION_INSTRUCTIONS)
        messages = [{"role": "user", "content": user}]

        for _ in range(2):  # one retry for malformed output, then give up loudly
            if not run.tick():
                return []
            resp: ProviderResponse = self.provider.complete(system=system, messages=messages)
            try:
                return self._parse_opinions(resp.text or "")
            except ValueError as e:
                messages.append({"role": "assistant", "content": resp.text or ""})
                messages.append({"role": "user", "content":
                                 f"Malformed: {e}. Reply with ONLY the JSON array."})
        run.failed("model could not produce well-formed opinions after retry")
        return []

    @staticmethod
    def _parse_opinions(text: str) -> list[Opinion]:
        text = text.strip()
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("no JSON array found")
        try:
            raw = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON: {e}") from e
        if not isinstance(raw, list):
            raise ValueError("expected a JSON array")
        opinions = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"opinion {i} is not an object")
            try:
                opinions.append(Opinion(**{k: v for k, v in item.items()
                                           if k in Opinion.__dataclass_fields__}))
            except TypeError as e:
                # missing required fields must be retryable, not a crash
                # (found by the stress suite: garbage-model scenario)
                raise ValueError(f"opinion {i} malformed: {e}") from e
        return opinions

    def _to_decision(self, op: Opinion) -> Decision:
        from datetime import timedelta
        revisit = (self.ground.now() + timedelta(days=op.revisit_days)
                   if op.revisit_days else None)
        return Decision(
            subject=op.subject,
            verdict=Verdict(op.verdict),
            rationale=op.rationale,
            author=self.id,
            emp_lineage=op.emp_lineage,
            povs=[POV(**p) for p in op.povs],
            owner=op.owner,
            revisit_at=revisit,
            missing=op.missing,
        )

    def _update_read(self, sensed: list[str], opinions: list[Opinion]) -> str:
        now = self.ground.now()
        content = "\n".join([
            f"# Read — {self.emp.name} — as of {now.isoformat()}",
            "",
            "## What the surface shows (age-tagged at ingestion)",
            *[f"- {s}" for s in sensed[-20:]],
            "",
            "## Opinions this cycle",
            *([f"- [{o.verdict}] {o.subject} — {o.rationale}" for o in opinions]
              or ["- none: nothing moved the read (that is a finding, not a gap)"]),
        ])
        receipt = self.workspace.write(
            "read/current-read.md", content, author=self.id,
            synthesis_justification=(
                "the current read is this agent's working understanding; it "
                "exists nowhere else in this synthesized, opinionated form"))
        return receipt.path

    # ----- staging outbound ----------------------------------------------------

    def propose_outbound(self, kind: str, target: str, content: str) -> str:
        """The only way a Witness touches the world: stage it and wait."""
        return self.outbox.stage(StagedAction(
            kind=kind, target=target, content=content, created_by=self.id,
            destination=self.key))
