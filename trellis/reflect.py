"""reflect.py — the reflection ritual PRODUCER (DECISIONS D18; plan Phase 2.6).

The reflection portal (docs/ROADMAP-UI-SPINE.md) is the comprehension heart of
the UI. The plan's stress-test caught that it had no data producer: the
`reflection_log`, the self-change proposals, and the self-image series were data
*nobody wrote*. This module writes them — and it is gated, because an ungated
self-writing loop is exactly the "dream subagent" the harness refuses (memory
without verification).

The ritual, once per cadence (D-B = 24h):
  1. Takes the day's ledger slice and computes an honest self-image snapshot
     (a pure function of real ledger numbers — same input, same creature).
  2. Writes an append-only `reflection_log` entry that CITES clickable real
     events, passing the SYNTHESIS gate (leave only what can't be re-derived)
     and the DREAD lint (functional mortality, never performed feeling).
  3. Stages any self-change as a VERIFIED PROPOSAL wired to the verifier panel —
     it cannot take effect unless an independent verifier confirms it. The maker
     never certifies its own change (the second refusal).

Nothing here mutates the EMP or the prompt. A self-change is a *proposal on the
record*; applying it is a separate, human-in-the-loop step (stage-don't-fire).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .clock import TimeGround
from .decisions import DecisionLog
from .emp import lint_mortality
from .identity import same_identity
from .ledger import Entry, Ledger
from .loops import LoopSpec
from .memory import _fails_synthesis
from .verify import CompletionClaim, Evidence, EvidenceKind, Verifier, record_verdict


REFLECTION_KIND = "reflection_log"
DEFAULT_CADENCE = timedelta(hours=24)   # D-B: once-daily


class DreadError(Exception):
    """The reflection performed dread instead of stating mortality as fact.
    Functional mortality motivates leaving-behind; performed dread is the soul
    leaking back in (see emp.lint_mortality)."""


class ReflectionSynthesisError(Exception):
    """The reflection's `learned` field didn't pass the synthesis test — it
    could be re-derived from existing sources, so it's bloat, not memory."""


class UnverifiedSelfChangeError(Exception):
    """A staged self-change was asked to take effect without an independent
    verifier confirming it. The maker never certifies its own change."""


def self_image_stats(ledger: Ledger, ground: Optional[TimeGround] = None) -> dict:
    """The honest inputs to the self-image glyph — every number a real ledger
    fact. Core-side (no web dependency) so the ritual can snapshot it; web's
    growth_stats delegates here, so there is ONE source of truth. Counts route
    through the validity-aware resolver: retired memories/decisions don't inflate
    the picture."""
    g = ground or ledger.ground
    entries = ledger.entries()
    verifs = [e for e in entries if e.kind == "verification"]
    verified = sum(1 for e in verifs if e.body.get("status") == "verified")
    checked = sum(1 for e in verifs if e.body.get("status") in ("verified", "refuted"))
    decisions = ledger.active("decision")
    memories = ledger.active("memory_write")
    loop_ends = [e for e in entries if e.kind == "loop_run_end"]
    open_ts = len(DecisionLog(ledger, g).hidden_nos())
    first = min((e.stamp.event_time for e in entries), default=g.now())
    age_days = max(0.0, (g.now().astimezone(first.tzinfo) - first).total_seconds() / 86400)
    return {
        "decisions": len(decisions),
        "verified": verified,
        "checked": checked,
        "trust": round(verified / checked, 3) if checked else None,
        "memories": len(memories),
        "loop_runs": len(loop_ends),
        "open_ts": open_ts,
        "age_days": round(age_days, 2),
        "entries": len(entries),
    }


@dataclass(frozen=True)
class SelfChange:
    """A proposal for the agent to change itself — never applied here, only
    proposed and verified. `evidence_ids` are real ledger entries grounding it,
    so the verifier can open them."""
    target: str          # what would change, e.g. "EMP:principles (append)"
    proposal: str        # the change, plainly
    rationale: str       # why the record justifies it
    evidence_ids: list[str] = field(default_factory=list)


def reflection_loop_spec(agent_id: str, surface_key: str,
                         cadence: timedelta = DEFAULT_CADENCE) -> LoopSpec:
    """The reflection ritual as a first-class loop (bounded, with a stop
    condition and a cadence) — so it runs under the same no-silent-failure,
    no-unbounded-loop discipline as everything else."""
    return LoopSpec(
        name=f"{agent_id}.reflect",
        purpose="once per cadence, write the grounded self-reflection to the record",
        surface_key=surface_key,
        max_turns=4,
        stop_condition="today's reflection_log is written (or explicitly nothing-new)",
        cadence=cadence,
    )


class ReflectionRitual:
    """Writes the reflection_log. Verifier-gated by construction: a self-change
    must pass an INDEPENDENT verifier (maker != verifier) before it may take
    effect."""

    def __init__(self, ledger: Ledger, author: str,
                 verifier: Optional[Verifier] = None,
                 ground: Optional[TimeGround] = None,
                 cadence: timedelta = DEFAULT_CADENCE):
        self.ledger = ledger
        self.author = author
        self.verifier = verifier
        self.ground = ground or ledger.ground
        self.cadence = cadence

    # ----- cadence (the Schedule) -------------------------------------------

    def last_run(self) -> Optional[datetime]:
        runs = [e for e in self.ledger.entries() if e.kind == REFLECTION_KIND]
        if not runs:
            return None
        return max(e.stamp.event_time for e in runs)

    def due(self, now: Optional[datetime] = None) -> bool:
        now = now or self.ground.now()
        last = self.last_run()
        return last is None or (now - last) >= self.cadence

    def _slice(self, now: datetime) -> list[Entry]:
        cutoff = now - self.cadence
        return [e for e in self.ledger.entries()
                if cutoff <= e.stamp.event_time <= now and e.kind != REFLECTION_KIND]

    # ----- the ritual --------------------------------------------------------

    def run(self, session_id: str, narrative: str, learned: str,
            self_change: Optional[SelfChange] = None,
            event_time: Optional[datetime] = None) -> Entry:
        """Write today's reflection. Gates, in order: dread-lint (both texts),
        synthesis test (on `learned`), then — if a self-change is proposed —
        independent verification. All append-only; the EMP is never mutated."""
        now = event_time or self.ground.now()

        # GATE 1 — dread-lint: mortality is a fact here, never a performed feeling.
        for text in (narrative, learned):
            viol = lint_mortality(text)
            if viol:
                raise DreadError(
                    "reflection performs dread instead of stating mortality as "
                    f"fact: {[v.label for v in viol]}. Rewrite functionally.")

        # GATE 2 — synthesis test: persist only what can't be re-derived.
        problem = _fails_synthesis(learned)
        if problem:
            raise ReflectionSynthesisError(problem)

        # SNAPSHOT — the self-image series point (honest numbers).
        snapshot = self_image_stats(self.ledger, self.ground)

        # CITATIONS — real, openable events from the day's slice.
        slice_ = self._slice(now)
        citations = [{"id": e.id, "kind": e.kind, "author": e.author,
                      "when": e.stamp.event_time.isoformat()} for e in slice_]

        # SELF-CHANGE — staged as a VERIFIED PROPOSAL (never self-certified).
        change_body = None
        if self_change is not None:
            change_body = self._verify_self_change(self_change, now)

        return self.ledger.append(
            kind=REFLECTION_KIND, author=self.author,
            body={
                "session_id": session_id,
                "narrative": narrative,
                "learned": learned,
                "self_image": snapshot,
                "cites": citations,
                "cited_count": len(citations),
                "self_change": change_body,
            },
            event_time=now,
            tags=("reflection",),
        )

    def _verify_self_change(self, change: SelfChange, now: datetime) -> dict:
        """Build a completion claim for the proposed change and run it past the
        independent verifier. The proposal is recorded either way; `verified` is
        the gate on whether it may take effect.

        A self-change MUST be grounded in openable LEDGER evidence. Earlier this
        fell back to maker-authored OUTPUT evidence (the rationale text) when
        `evidence_ids` was empty — but OUTPUT evidence only checks non-emptiness,
        so an ungrounded change would 'verify' on its own words (the Phase-2.6
        adversary's HIGH). No openable evidence → the proposal is recorded but
        stays unverified and cannot take effect."""
        record = {"target": change.target, "proposal": change.proposal,
                  "rationale": change.rationale,
                  "evidence_ids": list(change.evidence_ids),
                  "verified": False, "verdict": None, "claim_id": None}
        if not change.evidence_ids:
            record["verdict"] = "insufficient"
            record["note"] = ("no openable evidence — a self-change must cite real "
                              "ledger entries an independent verifier can inspect")
            return record
        claim = CompletionClaim(
            maker=self.author,
            task=f"self-change proposal: {change.target}",
            summary=f"{change.proposal} — {change.rationale}",
            evidence=[Evidence(EvidenceKind.LEDGER, eid) for eid in change.evidence_ids])
        record["claim_id"] = claim.id
        if self.verifier is not None:
            verdict = self.verifier.verify(claim)          # raises if maker==verifier
            record_verdict(self.ledger, claim, verdict)
            record["verdict"] = verdict.status.value
            record["verified"] = verdict.status.value == "verified"
        return record

    def apply_self_change(self, reflection_entry_id: str) -> dict:
        """A self-change may take effect ONLY if the LEDGER carries an independent
        verified verdict for its claim. Otherwise refuse — an unverified self-
        change taking effect is the harness self-certifying, which it must never
        do.

        We RE-DERIVE trust from the append-only record rather than trusting the
        reflection body's self-reported `verified` flag (the Phase-2.6 adversary's
        MED): a hand-crafted reflection_log claiming verified=True must still
        produce a real `verification` entry, by a party who is not the maker, to
        take effect. The record is the authority, not the claim about it."""
        e = self.ledger.get(reflection_entry_id)
        if e is None or e.kind != REFLECTION_KIND:
            raise KeyError(f"no reflection_log entry {reflection_entry_id}")
        change = e.body.get("self_change")
        if not change:
            raise KeyError("this reflection proposed no self-change")
        maker = e.author
        claim_id = change.get("claim_id")
        # find an INDEPENDENT verified verdict for this exact claim in the ledger
        independent_ok = False
        if claim_id:
            for v in self.ledger.entries():
                if (v.kind == "verification"
                        and v.body.get("claim_id") == claim_id
                        and v.body.get("status") == "verified"
                        and not same_identity(v.author, maker)):
                    independent_ok = True
                    break
        if not independent_ok:
            raise UnverifiedSelfChangeError(
                f"self-change {change.get('target')!r} has no independent verified "
                f"verdict on the record (claim={claim_id}, verdict="
                f"{change.get('verdict')}) — it cannot take effect. The ledger, not "
                "the reflection's own flag, is the authority.")
        return change
