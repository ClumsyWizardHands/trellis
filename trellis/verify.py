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

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol

from .clock import TimeGround
from .identity import same_identity, require_identity
from .ledger import Entry, Ledger


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
    # --- outcome predicates (Codex Critical 4): a claim can assert a CHECKABLE
    # outcome, not just that an artifact exists. When any of these is set, the
    # verifier performs a real content check — which is what earns VERIFIED rather
    # than PRECONDITIONS_PASSED. ---
    expect_hash: Optional[str] = None      # FILE: sha256 of the content must match
    expect_contains: Optional[str] = None  # FILE/LEDGER: body must contain this substring
    expect_kind: Optional[str] = None      # LEDGER: the entry must be of this kind

    def __post_init__(self):
        # A TRIVIAL predicate is not an outcome check. An empty/whitespace-only
        # `expect_contains` ('' is a substring of everything) or a blank
        # `expect_hash`/`expect_kind` would launder existence into VERIFIED, so
        # they are refused at construction — a predicate must actually assert
        # something checkable.
        if self.expect_contains is not None and not self.expect_contains.strip():
            raise ValueError("expect_contains must be a non-empty substring — an "
                             "empty predicate matches everything and is not an outcome check")
        if self.expect_hash is not None and not self.expect_hash.strip():
            raise ValueError("expect_hash must be a real sha256, not blank")
        if self.expect_kind is not None and not self.expect_kind.strip():
            raise ValueError("expect_kind must name a real ledger kind, not blank")

    def has_predicate(self) -> bool:
        return bool(self.expect_hash or self.expect_contains or self.expect_kind)


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
    VERIFIED = "verified"           # an OUTCOME predicate was checked and held
    PRECONDITIONS_PASSED = "preconditions_passed"   # evidence well-formed & openable,
                                    # but no claimed outcome was independently confirmed —
                                    # NOT "the claim is true" (Codex Critical 4)
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
    # both parties must be VALID identities. An id of exotic glyphs folds to
    # empty, which made same_identity non-reflexive — a small-caps-named agent
    # could verify itself because 'ᴀᴛʟᴀꜱ' != 'ᴀᴛʟᴀꜱ' after both fold to ""
    # (#46 round 3). Reject unusable ids rather than reason about them.
    require_identity(claim.maker, "maker")
    require_identity(verifier_id, "verifier")
    if same_identity(claim.maker, verifier_id):
        raise SelfCertificationError(
            f"{claim.maker!r} cannot verify its own claim {claim.id} — "
            "a self-audit is not an audit. Use a different agent id (and "
            "ideally a different, cheaper model with fresh context).")


# The maker's own run bookkeeping — a predicate against these confirms only that
# the maker labelled its own run, never an outcome (D25 / Codex#7 / FableG5b V3).
_LOOP_BOOKKEEPING_KINDS = frozenset({"loop_run_start", "loop_run_end"})


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
        outcome_checks = 0        # predicates that checked a real OUTCOME (not existence)
        external_only_unopenable = 0

        for ev in claim.evidence:
            if ev.kind == EvidenceKind.FILE:
                p = Path(ev.ref)
                # is_file(), not exists(): a directory is not the file the claim
                # says it produced (#48). Existence is a PRECONDITION, not the outcome.
                is_file = p.is_file()
                checks.append(Check(f"file exists: {ev.ref}", is_file,
                    "" if is_file else ("path is a directory, not a file" if p.is_dir()
                                        else "claimed file does not exist")))
                if is_file and (ev.expect_hash or ev.expect_contains):
                    content = p.read_text(encoding="utf-8", errors="replace")
                    if ev.expect_hash is not None:
                        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
                        ok = h == ev.expect_hash
                        checks.append(Check(f"file content hash matches: {ev.ref}", ok,
                                            "" if ok else f"sha256 {h[:12]}… != expected {ev.expect_hash[:12]}…"))
                        outcome_checks += 1
                    if ev.expect_contains is not None:
                        ok = ev.expect_contains in content
                        checks.append(Check(f"file contains expected content: {ev.ref}", ok,
                                            "" if ok else f"'{ev.expect_contains[:40]}' not found in the file"))
                        outcome_checks += 1
            elif ev.kind == EvidenceKind.LEDGER:
                if self.ledger is None:
                    checks.append(Check(f"ledger ref {ev.ref}", False,
                                        "no ledger available to this verifier"))
                else:
                    entry = self.ledger.get(ev.ref)
                    found = entry is not None
                    checks.append(Check(f"ledger entry exists: {ev.ref}", found,
                                        "" if found else "no such ledger entry"))
                    # A predicate that resolves against the MAKER's OWN loop
                    # bookkeeping (loop_run_start/end) is not an OUTCOME — it is
                    # the maker vouching for its own run label, the same laundering
                    # D25/Codex#7 close on the recency path (FableG5b V3). Such a
                    # predicate stays a PRECONDITION: it can still refute, but it
                    # never earns VERIFIED. A predicate against any other entry
                    # (a work-product the maker or another party appended) counts.
                    is_bookkeeping = found and entry.kind in _LOOP_BOOKKEEPING_KINDS
                    if found and ev.expect_kind is not None:
                        ok = entry.kind == ev.expect_kind
                        checks.append(Check(f"ledger entry is a {ev.expect_kind}: {ev.ref}", ok,
                                            "" if ok else f"entry is a {entry.kind}, not a {ev.expect_kind}"))
                        if not is_bookkeeping:
                            outcome_checks += 1
                    if found and ev.expect_contains is not None:
                        import json as _json
                        blob = _json.dumps(entry.body, ensure_ascii=False, default=str)
                        ok = ev.expect_contains in blob
                        checks.append(Check(f"ledger entry contains expected content: {ev.ref}", ok,
                                            "" if ok else f"'{ev.expect_contains[:40]}' not in the entry body"))
                        if not is_bookkeeping:
                            outcome_checks += 1
            elif ev.kind == EvidenceKind.OUTPUT:
                ok = bool(ev.ref.strip())
                checks.append(Check("output evidence non-empty", ok))
            else:
                # external evidence CANNOT be opened here → NOTED, not a failure
                # (a real file alongside it should not be refuted by it) and NOT a
                # pass (marking it passed was the Codex bug: an external-ONLY claim
                # then reached VERIFIED). It is unconfirmable; the real_evidence
                # count below turns an external-only claim into INSUFFICIENT.
                checks.append(Check(f"external ref (noted; cannot open here): {ev.ref}", True,
                                    "external evidence cannot be opened by this verifier — "
                                    "weakest class; unconfirmable, not counted as an outcome"))
                external_only_unopenable += 1

        # time sanity: a claim about work done "now" whose loop run is ancient.
        # These are PROVENANCE / PRECONDITION checks, NOT outcome checks (D25):
        # the recency and the "outcome is ok" label are authored by the MAKER's
        # own run.ok() (loops.py record_end author=run.actor), so counting them
        # as outcome checks let a maker launder existence-only evidence into
        # VERIFIED (Codex#7 / FableG5b). They can still REFUTE (a missing or
        # stale run is a hard failure), but they never EARN VERIFIED — only a
        # predicate tied to the claimed artifact/result does.
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
                recency_ok = age <= self.max_claim_age
                outcome_ok = runs[-1].body.get("outcome") == "ok"
                checks.append(Check("loop run recency", recency_ok, f"run concluded {age} ago"))
                checks.append(Check("loop outcome is ok", outcome_ok,
                                    f"outcome was {runs[-1].body.get('outcome')}"))
                # NOTE: deliberately NOT `outcome_checks += 2` — the maker's own
                # loop label is provenance, not an independently checked outcome.

        hard = [c for c in checks if not c.passed]   # real failures (external is noted, not failed)
        real_evidence = len(claim.evidence) - external_only_unopenable
        if hard:
            status = VerdictStatus.REFUTED               # a real (openable) check failed
        elif real_evidence == 0:
            status = VerdictStatus.INSUFFICIENT          # only unopenable externals — cannot confirm
        elif outcome_checks > 0:
            status = VerdictStatus.VERIFIED              # an OUTCOME was checked and held
        else:
            # evidence well-formed and openable, but no OUTCOME was checked —
            # preconditions passed, NOT "the claim is true" (Codex Critical 4).
            status = VerdictStatus.PRECONDITIONS_PASSED
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

    #: Distinct lenses for a panel. Diversity beats redundancy: three verifiers
    #: asking the same question catch less than three asking different ones
    #: ("very fragile triangles very strong" — Brett, 2026-03-13).
    LENSES = {
        "correctness": "Focus: does the evidence actually establish the claimed OUTCOME, "
                       "not just activity? Reject 'it ran' as proof 'it worked'.",
        "freshness": "Focus: TIME. Is the evidence current, or does it rest on stale "
                     "state? A correct-but-outdated result is REFUTED.",
        "attribution": "Focus: does every attributed statement/authorship in the evidence "
                       "actually check out? Misattribution alone is REFUTED.",
        "reproduce": "Focus: could an independent party re-run the evidence and get the "
                     "same result? If it is not reproducible from what is given, INSUFFICIENT.",
    }

    def __init__(self, verifier_id: str, provider, lens: Optional[str] = None) -> None:
        self.id = verifier_id
        self.provider = provider
        self.lens = lens
        self._lens_note = self.LENSES.get(lens or "", "") if lens else ""

    def verify(self, claim: CompletionClaim) -> Verdict:
        _guard_independence(claim, self.id)
        evidence_text = "\n".join(
            f"- [{e.kind.value}] {e.ref}" + (f" ({e.note})" if e.note else "")
            for e in claim.evidence)
        system = self.PROMPT + (f"\n\nYOUR LENS ({self.lens}): {self._lens_note}"
                                if self._lens_note else "")
        reply = self.provider.complete(
            system=system,
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
                       checks=[Check(f"model judgment ({self.lens or 'general'})",
                                     status == VerdictStatus.VERIFIED,
                                     (reply.text or "")[:500])],
                       note=f"model verifier; lens={self.lens or 'general'}; refute-oriented")


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
    three trust buckets (human-decides / agent-helps / agent-does).

    THE one canonical trust formula (D35): every surface delegates here, nothing
    recomputes trust. The broad-verification verdicts convene_verification records
    feed straight in (they are `verification` entries tagged with the maker), so a
    REFUTED lowers the ratio and an INSUFFICIENT never inflates it."""
    entries = [e for e in ledger.entries()
               if e.kind == "verification" and e.body.get("maker") == maker]
    counts = {"verified": 0, "preconditions_passed": 0, "refuted": 0, "insufficient": 0}
    for e in entries:
        counts[e.body["status"]] = counts.get(e.body["status"], 0) + 1
    total = sum(counts.values())
    # informational, NOT part of the ratio: open contested items this maker owns,
    # so a portal can show "trust AND what's under dispute" from the one function.
    contested = sum(1 for i in contested_items(ledger) if i.get("maker") == maker)
    # verified_ratio counts ONLY true outcome-verifications — preconditions_passed
    # is honest ("evidence openable") but is NOT a semantic pass and must not inflate
    # trust (Codex Critical 4: don't compound trust on artifact existence).
    return {"maker": maker, "total": total, **counts, "contested_open": contested,
            "verified_ratio": (counts["verified"] / total) if total else None}


# ---------------------------------------------------------------------------
# convene: broad, cheap, independent verification of a memory write (D34/D35)
# ---------------------------------------------------------------------------

CONTESTED_KIND = "contested"
CONTESTED_RESOLUTION_KIND = "contested_resolution"
CAPABILITY_GAP_KIND = "capability_gap"

# most-skeptical-wins ordering: a refutation always beats a confirmation, and a
# model that cannot confirm (INSUFFICIENT) can never be upgraded to VERIFIED by a
# merely-well-formed floor. VERIFIED is earned only when NOTHING more skeptical
# was returned — so the model verifier refutes/confirms but never mints VERIFIED
# past a floor with no outcome predicate (D25/D34).
_SEVERITY = {
    VerdictStatus.VERIFIED: 0,
    VerdictStatus.PRECONDITIONS_PASSED: 1,
    VerdictStatus.INSUFFICIENT: 2,
    VerdictStatus.REFUTED: 3,
}


def _subject_from_claim(claim: CompletionClaim) -> Optional[str]:
    """When no subject_id is given, the subject is the first openable ledger
    entry the claim is about — the decision/reflection/read being verified."""
    for e in claim.evidence:
        if e.kind == EvidenceKind.LEDGER:
            return e.ref
    return None


def convene_verification(ledger: Ledger, claim: CompletionClaim, verifier,
                         *, floor: Optional["RuleVerifier"] = None,
                         subject_id: Optional[str] = None,
                         subject_kind: Optional[str] = None,
                         record: bool = True) -> Verdict:
    """Convene independent verification of a memory write and record the outcome
    so trust accrues (D34: verify BROADLY — decision-tree writes, reflection
    writes, and load-bearing claims — because an unverified memory error compounds).

    `verifier` is the independent seat: a single ModelVerifier (the Haiku seat)
    or a VerifierPanel. `floor` is a deterministic RuleVerifier run FIRST; when
    omitted, one is built for a bare model verifier so the free floor always runs
    before any model spend. A refuted floor short-circuits (no model consulted).

    Combined refute-by-default (most-skeptical wins). On the combined verdict:
      * REFUTED  → append a `contested` event naming the subject and flag it for
        human escalation (D35); the subject is NEVER deleted (D2), only contested.
      * INSUFFICIENT → record a `capability_gap` (a persistent one is flagged),
        never counted as a pass.
    Returns the combined Verdict. Independence is structural: a maker verifying
    itself raises SelfCertificationError before anything is recorded past the floor.
    """
    subject_id = subject_id or _subject_from_claim(claim)
    verdicts: list[Verdict] = []

    active_floor = floor
    # auto-floor for a bare model verifier (has a provider, not a panel of lenses)
    if active_floor is None and hasattr(verifier, "provider") and not hasattr(verifier, "lenses"):
        active_floor = RuleVerifier(f"{verifier.id}:floor", ledger, ledger.ground)

    if active_floor is not None:
        fv = active_floor.verify(claim)          # raises if the floor id == maker
        verdicts.append(fv)
        if record:
            record_verdict(ledger, claim, fv)
        if fv.status == VerdictStatus.REFUTED:
            _mark_contested(ledger, claim, fv, subject_id, subject_kind)
            return fv                            # don't pay the model for a dead claim

    mv = verifier.verify(claim)                  # raises if the verifier id == maker
    verdicts.append(mv)
    # a panel self-records its lens verdicts (+ a panel_verdict) but not an overall
    # `verification` under its own id; a bare model verifier records nothing itself.
    # Record the returned verdict unless one already carries this claim+verifier.
    already = any(e.kind == "verification" and e.body.get("claim_id") == claim.id
                  and e.author == mv.verifier for e in ledger.entries())
    if record and not already:
        record_verdict(ledger, claim, mv)

    worst = max(verdicts, key=lambda v: _SEVERITY[v.status])
    combined = Verdict(
        claim_id=claim.id, verifier=worst.verifier, status=worst.status,
        checks=[c for v in verdicts for c in v.checks],
        note="; ".join(f"{v.verifier}={v.status.value}" for v in verdicts))

    if combined.status == VerdictStatus.REFUTED:
        _mark_contested(ledger, claim, combined, subject_id, subject_kind)
    elif combined.status == VerdictStatus.INSUFFICIENT:
        _record_capability_gap(ledger, claim, combined, subject_id, subject_kind)
    return combined


def _mark_contested(ledger: Ledger, claim: CompletionClaim, verdict: Verdict,
                    subject_id: Optional[str], subject_kind: Optional[str]) -> Entry:
    """A REFUTED verdict marks its subject contested and escalates to the human
    (D35). Append-only — the subject decision/read is NOT deleted; it is removed
    from the trusted read the next cycle compiles by querying contested_items."""
    return ledger.append(
        kind=CONTESTED_KIND, author=verdict.verifier,
        body={"claim_id": claim.id, "maker": claim.maker, "subject_id": subject_id,
              "subject_kind": subject_kind, "task": claim.task, "status": "refuted",
              "note": verdict.note or "refuted by independent verification",
              "escalated": True},
        tags=("contested", "escalation", claim.maker))


def _record_capability_gap(ledger: Ledger, claim: CompletionClaim, verdict: Verdict,
                           subject_id: Optional[str], subject_kind: Optional[str]) -> Entry:
    """A persistent INSUFFICIENT is a capability gap, not a pass (D35): the
    harness cannot check this class of claim yet. Occurrences accumulate so a
    recurring blind spot is flagged for the confusion-harvest, never swallowed."""
    prior = sum(1 for e in ledger.entries()
                if e.kind == CAPABILITY_GAP_KIND and e.body.get("subject_id") == subject_id)
    return ledger.append(
        kind=CAPABILITY_GAP_KIND, author=verdict.verifier,
        body={"claim_id": claim.id, "maker": claim.maker, "subject_id": subject_id,
              "subject_kind": subject_kind, "task": claim.task,
              "note": "independent verification INSUFFICIENT — recorded as a "
                      "capability gap, not a pass",
              "occurrence": prior + 1, "persistent": (prior + 1) >= 2},
        tags=("capability_gap", "insufficient", claim.maker))


def contested_items(ledger: Ledger, include_resolved: bool = False) -> list[dict]:
    """The portal/witness query: subjects an independent verifier REFUTED and
    flagged for escalation, most recent first. Append-only — a human clears one
    with resolve_contested(), which appends a resolution rather than deleting the
    contest. The context compiler reads this to drop contested subjects from the
    trusted read (D35)."""
    resolved: set[str] = set()
    if not include_resolved:
        for e in ledger.entries():
            if e.kind == CONTESTED_RESOLUTION_KIND:
                cid = e.body.get("contested_id")
                if cid:
                    resolved.add(cid)
    out: list[dict] = []
    for e in ledger.entries():
        if e.kind != CONTESTED_KIND:
            continue
        if not include_resolved and e.id in resolved:
            continue
        out.append({
            "contested_id": e.id, "subject_id": e.body.get("subject_id"),
            "subject_kind": e.body.get("subject_kind"), "maker": e.body.get("maker"),
            "claim_id": e.body.get("claim_id"), "task": e.body.get("task"),
            "note": e.body.get("note"), "escalated": e.body.get("escalated", True),
            "resolved": e.id in resolved, "when": e.stamp.event_time.isoformat()})
    out.reverse()
    return out


def resolve_contested(ledger: Ledger, contested_id: str, human: str,
                      note: str = "") -> Entry:
    """The human seat on the escalation queue: append a resolution clearing a
    contested item (never a deletion). The resolver runs through require_identity
    so a blank or homoglyph yes is refused at the gate, same as every human seat."""
    human = require_identity(human, "resolver")
    c = ledger.get(contested_id)
    if c is None or c.kind != CONTESTED_KIND:
        raise KeyError(f"no contested entry {contested_id}")
    return ledger.append(
        kind=CONTESTED_RESOLUTION_KIND, author=human,
        body={"contested_id": contested_id, "subject_id": c.body.get("subject_id"),
              "resolved_by": human, "note": note},
        tags=("contested", "resolved"))
