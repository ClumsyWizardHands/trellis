"""verify.py — the maker never grades its own work. (DECISIONS.md D4)

"A self audit is not an audit… two agents on a line very fragile; very fragile
triangles very strong." — Brett, 2026-03-13
"You're asking Claude to watchdog itself and that's the problem." — Brett,
2026-06-17
"…the [DNA] sequencers haiku verifiers and actually verifying that the agents
are doing memory-is-navigation… takes precedent over sanitization." — Brett,
2026-07-12 (the current #1 priority)

Mechanisms:
  * CompletionClaim — a maker's structured claim: what it did, with EVIDENCE
    (refs a checker can independently open). "It works it works it works" with
    no evidence is unrepresentable.
  * SelfCertificationError — maker id == verifier id raises. Structurally.
  * RuleVerifier — the deterministic layer (cheap, no model): evidence exists,
    files really exist, times are sane, the claim's loop actually ran. This is
    the floor every claim passes before any model-judged verification.
  * ModelVerifier — the "haiku verifier" seat: a SEPARATE, cheaper model reads
    the claim + evidence and judges with fresh context ("the bigger the task…
    the fresher the context window we want" — Brett, 2026-03-13). Provider-
    agnostic; refuses to run against the maker's own session.
  * Verdicts land in the ledger — verification is memory, so trust can
    compound ("compounding interests in skills performance verification").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol

from .clock import TimeGround
from .identity import same_identity
from .ledger import Ledger


class SelfCertificationError(Exception):
    """The maker tried to verify its own work. A self-audit is not an audit."""


class EvidenceKind(str, Enum):
    FILE = "file"            # a path that must exist
    LEDGER = "ledger"        # a ledger entry id that must exist
    OUTPUT = "output"        # captured output text (attached inline)
    EXTERNAL = "external"    # a URL/ref the verifier may not be able to open — weakest


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    ref: str                 # path / entry id / text / url
    note: str = ""


@dataclass
class CompletionClaim:
    maker: str               # agent id making the claim
    task: str                # what was supposedly done, plainly
    summary: str             # what the maker says happened
    evidence: list[Evidence]
    loop_run_id: Optional[str] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        if not self.evidence:
            raise ValueError(
                "a completion claim requires evidence — 'it works it works it "
                "works' with nothing a checker can open is not a claim, it's a vibe")


class VerdictStatus(str, Enum):
    VERIFIED = "verified"
    REFUTED = "refuted"
    INSUFFICIENT = "insufficient"   # honest "cannot verify" — never silently passed


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Verdict:
    claim_id: str
    verifier: str
    status: VerdictStatus
    checks: list[Check]
    note: str = ""


class Verifier(Protocol):
    id: str
    def verify(self, claim: CompletionClaim) -> Verdict: ...


def _guard_independence(claim: CompletionClaim, verifier_id: str) -> None:
    if same_identity(claim.maker, verifier_id):
        raise SelfCertificationError(
            f"{claim.maker!r} cannot verify its own claim {claim.id} — "
            "a self-audit is not an audit. Use a different agent id (and "
            "ideally a different, cheaper model with fresh context).")


class RuleVerifier:
    """Deterministic checks — the floor. No model, no cost, no mood."""

    def __init__(self, verifier_id: str, ledger: Optional[Ledger] = None,
                 ground: Optional[TimeGround] = None,
                 max_claim_age: timedelta = timedelta(days=2)):
        self.id = verifier_id
        self.ledger = ledger
        self.ground = ground or TimeGround()
        self.max_claim_age = max_claim_age

    def verify(self, claim: CompletionClaim) -> Verdict:
        _guard_independence(claim, self.id)
        checks: list[Check] = []

        for ev in claim.evidence:
            if ev.kind == EvidenceKind.FILE:
                p = Path(ev.ref)
                checks.append(Check(
                    name=f"file exists: {ev.ref}",
                    passed=p.exists(),
                    detail="" if p.exists() else "claimed file does not exist",
                ))
            elif ev.kind == EvidenceKind.LEDGER:
                if self.ledger is None:
                    checks.append(Check(f"ledger ref {ev.ref}", False,
                                        "no ledger available to this verifier"))
                else:
                    found = self.ledger.get(ev.ref) is not None
                    checks.append(Check(f"ledger entry exists: {ev.ref}", found,
                                        "" if found else "no such ledger entry"))
            elif ev.kind == EvidenceKind.OUTPUT:
                ok = bool(ev.ref.strip())
                checks.append(Check("output evidence non-empty", ok))
            else:
                checks.append(Check(f"external ref noted: {ev.ref}", True,
                                    "external evidence cannot be opened here — "
                                    "weakest evidence class, flagged not failed"))

        # time sanity: a claim about work done "now" whose loop run is ancient
        if claim.loop_run_id and self.ledger is not None:
            runs = [e for e in self.ledger.entries()
                    if e.kind == "loop_run_end"
                    and e.body.get("run_id") == claim.loop_run_id]
            if not runs:
                checks.append(Check("loop run exists", False,
                                    f"no loop_run_end for {claim.loop_run_id} — "
                                    "claim references a run that never concluded"))
            else:
                age = self.ground.now() - runs[-1].stamp.event_time
                checks.append(Check("loop run recency", age <= self.max_claim_age,
                                    f"run concluded {age} ago"))
                checks.append(Check(
                    "loop outcome is ok",
                    runs[-1].body.get("outcome") == "ok",
                    f"outcome was {runs[-1].body.get('outcome')}"))

        hard = [c for c in checks if not c.passed]
        status = VerdictStatus.VERIFIED if not hard else VerdictStatus.REFUTED
        # If the only failures are unopenable externals, be honest, not harsh:
        if hard and all("external" in c.name for c in hard):
            status = VerdictStatus.INSUFFICIENT
        return Verdict(claim_id=claim.id, verifier=self.id, status=status,
                       checks=checks)


class ModelVerifier:
    """The haiku-verifier seat: a separate, cheaper model judging with fresh
    context. Takes any Provider (see providers/base.py). The prompt asks it to
    REFUTE — a verifier hunting for holes is worth more than one nodding along."""

    PROMPT = (
        "You are an independent verifier with fresh context. You did not do this "
        "work. Try to REFUTE the claim below using only the evidence given. "
        "Answer with exactly one first line: VERIFIED, REFUTED, or INSUFFICIENT, "
        "then one short paragraph of reasoning. If the evidence does not let you "
        "check the claim, say INSUFFICIENT — do not give the benefit of the doubt."
    )

    def __init__(self, verifier_id: str, provider) -> None:
        self.id = verifier_id
        self.provider = provider

    def verify(self, claim: CompletionClaim) -> Verdict:
        _guard_independence(claim, self.id)
        evidence_text = "\n".join(
            f"- [{e.kind.value}] {e.ref}" + (f" ({e.note})" if e.note else "")
            for e in claim.evidence)
        reply = self.provider.complete(
            system=self.PROMPT,
            messages=[{"role": "user", "content":
                       f"CLAIM by {claim.maker}: {claim.task}\n"
                       f"MAKER'S SUMMARY: {claim.summary}\n"
                       f"EVIDENCE:\n{evidence_text}"}],
        )
        lines = (reply.text or "").strip().splitlines()
        first = lines[0].strip().upper() if lines else ""  # blank reply → INSUFFICIENT, never a crash
        status = {
            "VERIFIED": VerdictStatus.VERIFIED,
            "REFUTED": VerdictStatus.REFUTED,
        }.get(first, VerdictStatus.INSUFFICIENT)  # unparseable = insufficient, never verified
        return Verdict(claim_id=claim.id, verifier=self.id, status=status,
                       checks=[Check("model judgment", status == VerdictStatus.VERIFIED,
                                     (reply.text or "")[:500])],
                       note="model verifier; refute-oriented prompt")


def record_verdict(ledger: Ledger, claim: CompletionClaim, verdict: Verdict) -> None:
    """Verification is memory. Verdicts compound in the ledger, keyed to the
    claim and both parties — the 'compounding interest' Brett asked for."""
    ledger.append(
        kind="verification", author=verdict.verifier,
        body={
            "claim_id": claim.id, "maker": claim.maker, "task": claim.task,
            "status": verdict.status.value,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                       for c in verdict.checks],
            "note": verdict.note,
        },
        tags=("verify", verdict.status.value, claim.maker),
    )


def trust_record(ledger: Ledger, maker: str) -> dict:
    """A maker's verification history — the basis for moving work between the
    three trust buckets (human-decides / agent-helps / agent-does)."""
    entries = [e for e in ledger.entries()
               if e.kind == "verification" and e.body.get("maker") == maker]
    counts = {"verified": 0, "refuted": 0, "insufficient": 0}
    for e in entries:
        counts[e.body["status"]] = counts.get(e.body["status"], 0) + 1
    total = sum(counts.values())
    return {"maker": maker, "total": total, **counts,
            "verified_ratio": (counts["verified"] / total) if total else None}
