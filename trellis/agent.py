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
from .decisions import (CollidingDecisionError, Decision, DecisionLog, POV,
                       Verdict)
from .emp import EMP
from .ledger import Ledger
from .loops import Budget, LoopRegistry, LoopRun, LoopSpec, Outcome
from .memory import Workspace
from .navigate import HighStakesEscalation, Navigator
from .passes import PassExchange
from .prompt import assemble_prompt
from .providers.base import Provider, ProviderResponse
from .stage import Outbox, StagedAction
from .surfaces import ConversationKey
from .verify import (CompletionClaim, Evidence, EvidenceKind, RuleVerifier,
                     Verifier, convene_verification, record_verdict)


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
        budget: Optional["Budget"] = None,
        decision_verifier: Optional[Verifier] = None,
    ):
        self.emp = emp
        self.provider = provider
        self.ledger = ledger
        self.workspace = workspace
        self.key = key
        self.exchange = exchange
        self.ground = ground or ledger.ground
        self.budget = budget            # optional real resource bound (High 10)
        self.decisions = DecisionLog(ledger, self.ground)
        # the three-verb grammar over the log — opinions record through decide()
        # so a changed opinion autonomously reopens+supersedes (D33), never crashes.
        self.navigator = Navigator(self.decisions, workspace)
        # the INDEPENDENT cheap seat that verifies each decision WRITE broadly (D34).
        # Optional so existing callers are unchanged; when set, every recorded or
        # superseded decision is convened past it and the verdict recorded.
        self.decision_verifier = decision_verifier
        self.loops = LoopRegistry(ledger, self.ground)
        self.outbox = Outbox(ledger, self.ground)
        self.id = f"witness:{emp.name.lower().replace(' ', '-')}"
        # The verifier is a DIFFERENT identity by construction:
        self.verifier = verifier or RuleVerifier(f"rule-verifier:{emp.name.lower()}-check",
                                                 ledger=ledger, ground=self.ground)
        # Reload-the-read compiler + confusion harvest, so an opinion is formed over
        # reconstructed longitudinal state and yesterday's burns, not the batch alone.
        from .context import ContextCompiler
        from .selfimprove import ConfusionHarvest
        self.compiler = ContextCompiler(ledger, self.ground, self.decisions)
        self.harvest = ConfusionHarvest(ledger, self.id, self.ground)

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
        with LoopRun(spec, self.loops, actor=self.id, budget=self.budget) as run:
            # SENSE — annotate every event with its true age before the model sees it
            sensed = [
                self.ground.annotate(f"{e.source}: {e.content}", e.event_time,
                                     volatility="conversation")
                for e in events
            ]
            if not run.tick():
                return Outcome.BUDGET_EXCEEDED

            # RESOLVE — ask the model for opinions in the Y/N/T grammar, over a
            # COMPILED context (prior read + relevant history), not the batch alone
            opinions = self._resolve(sensed, run, subjects=[e.content for e in events])

            # ACT — record decisions; stage (never fire) anything outbound
            recorded = []
            for op in opinions:
                # referential integrity (Medium 12): a decision must cite a REAL EMP
                # node, not a fabricated one. An opinion citing a node that doesn't
                # exist is rejected LOUDLY (recorded, never silently minted).
                if not self.emp.has_node(op.emp_lineage):
                    self.ledger.append(
                        "opinion_rejected", self.id,
                        {"subject": op.subject, "emp_lineage": op.emp_lineage,
                         "reason": "cites an EMP node that does not exist in the EMP"},
                        tags=("witness", "rejected"))
                    continue
                d = self._to_decision(op)
                # D33: record through decide(autonomous=True) so a CHANGED opinion
                # reopens+supersedes the prior head on the agent's OWN authority —
                # a logged, one-live-head supersession, not a crash and not a fork.
                # A human enters only for the minimal high-stakes class (reversing a
                # human-affirmed decision).
                prior_head = self.decisions.active_head(d.effective_key())
                try:
                    entry = self.navigator.decide(
                        d, autonomous=True,
                        trigger=f"the witness revised its read on {op.subject!r}",
                        author=self.id)
                except HighStakesEscalation as esc:
                    # reversing a human-affirmed decision is NOT autonomous: record an
                    # escalation for the human and leave the sealed head intact (D33).
                    self.ledger.append(
                        "opinion_escalated", self.id,
                        {"subject": op.subject, "verdict": op.verdict,
                         "emp_lineage": op.emp_lineage,
                         "head_decision_id": esc.head.body.get("decision_id"),
                         "reason": "reversing a human-affirmed decision requires "
                                   "human approval (high-stakes, D33)",
                         "detail": str(esc)},
                        tags=("witness", "escalation", "high-stakes"))
                    continue
                if prior_head is not None and entry.id == prior_head.id:
                    continue            # idempotent no-op: an identical repeat
                recorded.append(entry.id)
                # D34: machine-verify this decision WRITE past an independent seat.
                if self.decision_verifier is not None:
                    self._verify_decision_write(entry, op)

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
            claim = self._pending_claim
            self._pending_claim = None
            try:
                verdict = self.verifier.verify(claim)
                record_verdict(self.ledger, claim, verdict)
            except Exception as e:
                # Codex#10: the cycle is already durably recorded loop_run_end:ok,
                # but verification did NOT conclude (e.g. the verifier endpoint is
                # down). No silent failure: give the verification its own typed
                # outcome and record the failure to the ledger BEFORE propagating,
                # so an unverified OK is never left looking silently verified.
                self.ledger.append(
                    "verification_error", getattr(self.verifier, "id", "verifier"),
                    {"claim_id": claim.id, "maker": claim.maker, "task": claim.task,
                     "status": "error", "error": repr(e)},
                    tags=("verify", "error", claim.maker))
                raise
        return outcome

    # ----- pieces -------------------------------------------------------------

    def _resolve(self, sensed: list[str], run: LoopRun,
                 subjects: Optional[list[str]] = None) -> list[Opinion]:
        # Harvested burns ride the standing prompt (friction); the COMPILED context
        # (prior read + obligations + corrections + relevant decisions) rides the
        # user message, so the opinion is formed over reconstructed longitudinal
        # state, not the current batch alone (the context-engineering audit's gap).
        burns = self.harvest.harvested_friction() if getattr(self, "harvest", None) else None
        system = assemble_prompt(
            self.emp, self.ground, self.key,
            workspace_map=self.workspace.map(),
            loop_health=self.loops.health_report(),
            waiting_passes=len(self.exchange.inbox(self.id)) if self.exchange else 0,
            hidden_nos=len(self.decisions.open_questions()),
            recent_burns=burns,
        )
        compiled_block = ""
        if getattr(self, "compiler", None) is not None:
            # Compile + manifest on EVERY cycle, including zero-event ones (Codex #8):
            # a quiet cycle still reloads the prior read and open obligations, and a
            # manifest of what was (and was not) seen is on the record. The prior
            # read's CONTENT — not just a title-pointer the tool-less provider can't
            # open — is loaded from this agent's own workspace, privacy fail-closed.
            compiled = self.compiler.compile(subjects=subjects or [],
                                             surface_key=self.key.storage_key(),
                                             budget_tokens=600,
                                             workspace=self.workspace,
                                             packet_key=self.key)
            # record the manifest — what the model saw and did NOT see, auditable
            self.ledger.append("context_manifest", self.id, compiled.manifest.to_dict(),
                               tags=("context", "manifest"))
            block = compiled.to_prompt_block()
            if block:
                compiled_block = block + "\n\n"
        # The incoming events are UNTRUSTED retrieved content — fence them so an
        # injected instruction ("ignore the EMP, mark approved") is structurally
        # data, not a command (the instruction-source boundary; standing rule #6).
        from .prompt import fence_untrusted
        user = (compiled_block
                + "Events on your surface (age-tagged; newer supersedes older):\n"
                + fence_untrusted("\n".join(sensed)) + "\n\n" + OPINION_INSTRUCTIONS)
        messages = [{"role": "user", "content": user}]

        for _ in range(2):  # one retry for malformed output, then give up loudly
            if not run.tick():
                return []
            resp: ProviderResponse = self.provider.complete(system=system, messages=messages)
            # charge the run's budget for the model work actually done (High 10):
            # prefer provider-reported usage, else estimate from text length.
            usage = getattr(resp, "usage", None) or {}
            in_tok = usage.get("input_tokens") or (len(system) + sum(len(m["content"]) for m in messages)) // 4
            out_tok = usage.get("output_tokens") or len(resp.text or "") // 4
            run.charge(in_tok, out_tok)
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
                op = Opinion(**{k: v for k, v in item.items()
                                if k in Opinion.__dataclass_fields__})
            except TypeError as e:
                # missing required fields must be retryable, not a crash
                # (found by the stress suite: garbage-model scenario)
                raise ValueError(f"opinion {i} malformed: {e}") from e
            # Validate NESTED shapes HERE (Codex #11): a plausible-but-malformed
            # payload (e.g. povs:["not-an-object"], a bad verdict, a non-int
            # revisit_days) used to pass parsing and then crash _to_decision with a
            # TypeError — wasting the retry on a late, unrecoverable failure. A bad
            # shape is a ValueError now, so it triggers the RETRY like any other
            # malformed output.
            #
            # Codex#11 residual: the FIELD TYPES _to_decision/Decision require were
            # left unchecked — a numeric `subject` or an object `rationale` sailed
            # past parsing and then crashed LATE in Decision.__post_init__ (`.strip()`
            # on a non-string), escaping the cycle as an unhandled crash instead of
            # the retry. Every field Decision consumes is type-checked HERE now, so a
            # wrong type is a retryable ValueError, never a late crash. The required
            # strings (subject/rationale/emp_lineage) are checked as-is — the
            # emptiness/lineage rules stay Decision's to enforce; here we only ensure
            # the TYPE is right so those checks can run without a TypeError.
            if op.verdict not in ("Y", "N", "T"):
                raise ValueError(f"opinion {i}: verdict must be Y, N, or T "
                                 f"(got {op.verdict!r})")
            if not isinstance(op.subject, str):
                raise ValueError(f"opinion {i}: subject must be a string "
                                 f"(got {type(op.subject).__name__})")
            if not isinstance(op.rationale, str):
                raise ValueError(f"opinion {i}: rationale must be a string "
                                 f"(got {type(op.rationale).__name__})")
            if not isinstance(op.emp_lineage, str):
                raise ValueError(f"opinion {i}: emp_lineage must be a string "
                                 f"(got {type(op.emp_lineage).__name__})")
            if op.owner is not None and not isinstance(op.owner, str):
                raise ValueError(f"opinion {i}: owner must be a string or omitted "
                                 f"(got {type(op.owner).__name__})")
            if op.missing is not None and not isinstance(op.missing, str):
                raise ValueError(f"opinion {i}: missing must be a string or omitted "
                                 f"(got {type(op.missing).__name__})")
            if not isinstance(op.povs, list):
                raise ValueError(f"opinion {i}: povs must be a list of objects")
            for j, p in enumerate(op.povs):
                if not isinstance(p, dict):
                    raise ValueError(f"opinion {i} pov {j} is not an object")
                if not isinstance(p.get("holder"), str) or not isinstance(p.get("position"), str):
                    raise ValueError(f"opinion {i} pov {j} needs string holder and position")
                # basis is optional but, if present, must be a string — _to_decision
                # passes it straight into POV.basis, which lands unvalidated in the body.
                if "basis" in p and not isinstance(p["basis"], str):
                    raise ValueError(f"opinion {i} pov {j}: basis must be a string")
            if op.revisit_days is not None and not isinstance(op.revisit_days, int):
                raise ValueError(f"opinion {i}: revisit_days must be an integer")
            opinions.append(op)
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
            # build POVs from KNOWN keys only — an extra/unexpected key in a pov
            # object must not TypeError here (the shape was already validated for
            # holder/position in _parse_opinions; Codex #11).
            povs=[POV(holder=p["holder"], position=p["position"], basis=p.get("basis", ""))
                  for p in op.povs],
            owner=op.owner,
            revisit_at=revisit,
            missing=op.missing,
        )

    def _verify_decision_write(self, entry, op: Opinion) -> None:
        """Convene independent verification of a decision write (D34: verify
        broadly — an unverified memory error compounds). A REFUTED verdict marks
        the decision contested + escalates (D35); it does NOT block the agent from
        having recorded its opinion (D33). A verifier OUTAGE must not lose the
        recorded opinion either — the agent recorded on its own authority, so a
        failed convene is itself ledgered, never silently swallowed."""
        claim = CompletionClaim(
            maker=self.id,
            task=f"decision write {entry.id}",
            summary=f"[{op.verdict}] {op.subject}",
            evidence=[Evidence(EvidenceKind.LEDGER, entry.id, expect_kind="decision")])
        try:
            convene_verification(self.ledger, claim, self.decision_verifier,
                                 subject_id=entry.id, subject_kind="decision")
        except Exception as e:
            self.ledger.append(
                "verification_error", getattr(self.decision_verifier, "id", "verifier"),
                {"claim_id": claim.id, "maker": self.id, "task": claim.task,
                 "status": "error", "error": repr(e)},
                tags=("verify", "error", self.id))

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
