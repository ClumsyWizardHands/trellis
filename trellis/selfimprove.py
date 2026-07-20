"""selfimprove.py — the agent proposes its own repair; it never applies it.

Phase 1 of the self-improvement engine (docs/PLAN-self-improvement-engine.md).
Alex, 2026-07-20: "infrastructure … for the agent to constantly think about ways
to improve itself … recursively improve itself all the time."

The one line that keeps this honest:

    The agent improves itself continuously; it never CHANGES itself without an
    independent verified verdict AND a human's yes.

So this module adds NO new authority for the agent over itself. It composes two
things onto the existing spine:

  * SkillEstate — the agent's capabilities as first-class NAVIGABLE nodes (00-grade
    titles, a stable capability_key, a trust tier). Answers "is there already a
    skill for this?" by title search BEFORE a duplicate is proposed — the curiosity
    anti-fork (D16), reused for capabilities.
  * ImprovementProposal — a typed proposal (friction/principle/process/skill/…)
    that reuses reflect.apply_self_change's EXACT gate: staged, independently
    verified (maker != verifier), and unable to take effect without an independent
    `verification` entry on the record. A skill:add from an untrusted source carries
    W1's default-N and must state its supply-chain reasoning (the T-grammar's forced
    "why"). The record, not the proposal's own flag, is the authority.

Nothing here mutates the EMP, the prompt, the skill set, or any config. Applying a
ratified proposal is a separate, human-in-the-loop step (stage-don't-fire, D18/W3).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .clock import TimeGround
from .decisions import question_key
from .identity import is_effectively_blank, same_identity
from .ledger import Entry, Ledger
from .verify import (CompletionClaim, Evidence, EvidenceKind, Verifier,
                     record_verdict)


# ----- the capability estate (memory-as-navigation, for skills) --------------

SKILL_KIND = "skill_node"

#: A skill's trust tier. Only a HUMAN may move a node up a tier (W1) — the agent
#: proposes, a human reviews and installs. External code is never auto-trusted.
class SkillTrust(str, Enum):
    EXTERNAL_UNVERIFIED = "external-unverified"   # someone posted it; not reviewed
    PROPOSED = "proposed"                         # the agent proposed adding it
    LOCAL_REVIEWED = "local-reviewed"             # a human read and installed it


def capability_key(name: str) -> str:
    """The stable identity of a CAPABILITY — homoglyph/case-folded like
    question_key, so 'summarise a doc' and 'Summarize a Doc' fold onto one node.
    Dedup ('is there already a skill?') is the curiosity anti-fork, reused."""
    return "cap:" + question_key(name)


@dataclass
class SkillNode:
    title: str            # 00-grade, keyword-findable ("summarize a Google Doc")
    does: str             # what it does, plainly
    source: str           # where it came from ("local", "youtube:<url>", "team:sarah", …)
    trust: SkillTrust = SkillTrust.PROPOSED

    def __post_init__(self):
        if is_effectively_blank(self.title):
            raise ValueError("a skill needs a findable title — the estate is navigated by title")
        if is_effectively_blank(self.does):
            raise ValueError("a skill needs a plain description of what it does")
        if not isinstance(self.trust, SkillTrust):
            self.trust = SkillTrust(str(self.trust))

    def key(self) -> str:
        return capability_key(self.title)


class SkillEstate:
    """The agent's map of what it can do. Append-only, validity-aware, anti-forked
    on the capability_key — a reworded skill folds onto the same node."""

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground

    def _active_by_key(self, ckey: str) -> Optional[Entry]:
        for e in self.ledger.active(SKILL_KIND):
            if e.body.get("capability_key") == ckey:
                return e
        return None

    def register(self, skill: SkillNode, author: str) -> Entry:
        """Record a skill — or, if this capability already exists, FOLD onto it
        (refresh, keeping the trust tier) rather than mint a duplicate. This is
        the dedup that answers 'is there already a skill for this?'."""
        ckey = skill.key()
        existing = self._active_by_key(ckey)
        body = {"skill_id": (existing.body.get("skill_id") if existing
                             else uuid.uuid4().hex[:12]),
                "title": skill.title, "does": skill.does, "source": skill.source,
                "capability_key": ckey,
                # a fold never silently upgrades trust; keep the prior tier unless
                # this registration is explicitly higher via promote()
                "trust": (existing.body.get("trust") if existing else skill.trust.value)}
        return self.ledger.append(
            kind=SKILL_KIND, author=author, body=body,
            tags=("skill", ckey, body["trust"]),
            supersedes=existing.id if existing else None)

    def find(self, keywords: str) -> list[tuple[str, str]]:
        """(title, skill_id) for active skills whose TITLE matches — 'is there
        already a skill?' Search titles, open the body on a match (navigation)."""
        # length>=2 filters stop-letters like 'a' that substring-match any title
        # (the memory.search_titles convention) — a one-letter query word is noise.
        want = [w for w in re.findall(r"\w+", keywords.lower()) if len(w) >= 2]
        if not want:
            return []
        scored = []
        for e in self.ledger.active(SKILL_KIND):
            title = e.body.get("title", "")
            hits = sum(1 for w in want if w in title.lower())
            if hits:
                scored.append((hits, title, e.body.get("skill_id", e.id)))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [(t, sid) for _, t, sid in scored]

    def active_skills(self) -> list[Entry]:
        return self.ledger.active(SKILL_KIND)

    def promote(self, skill_id: str, human: str, to: SkillTrust) -> Entry:
        """Move a skill up a trust tier. HUMAN-ONLY (W1): the agent may propose a
        skill, but only a human review moves it to local-reviewed/installed. A
        blank human, or an agent trying to self-promote, is refused."""
        if is_effectively_blank(human):
            raise ValueError("a skill promotion names the human who reviewed it (W1)")
        head = next((e for e in self.ledger.active(SKILL_KIND)
                     if e.body.get("skill_id") == skill_id), None)
        if head is None:
            raise KeyError(f"no active skill {skill_id!r}")
        body = {**head.body, "trust": to.value, "reviewed_by": human}
        return self.ledger.append(
            kind=SKILL_KIND, author=human, body=body,
            tags=("skill", head.body.get("capability_key", ""), to.value),
            supersedes=head.id)


# ----- the improvement proposal (reuses reflect's verified/staged gate) -------

PROPOSAL_KIND = "improvement_proposal"

#: Trusted sources whose material the agent may propose to adopt directly. Anything
#: else (a YouTube short, a random gist) is external-untrusted: W1 default-N.
_TRUSTED_SOURCES = {"self", "local", "team"}


class ProposalTarget(str, Enum):
    EMP_FRICTION = "emp:friction"       # record a burn so a future session avoids it
    EMP_PRINCIPLE = "emp:principle"     # a non-negotiable to add (heavy — needs a human)
    PROCESS = "process"                 # a change to how the agent works
    SKILL_ADD = "skill:add"             # adopt a capability (W1 gate)
    SKILL_RETIRE = "skill:retire"       # drop a capability
    PROMPT = "prompt"                   # a standing-prompt change
    LOOP_CONFIG = "loop_config"         # a loop cadence / bound change


class W1RefusalError(Exception):
    """An external, untrusted skill:add proposal that does not state its supply-
    chain reasoning. W1 (824 malicious skills; 'don't trust AI to write skills')
    refuses auto-installed skills — an external add must carry the WHY a human will
    weigh, exactly like a T names its missing piece."""


class UnverifiedProposalError(Exception):
    """A proposal was asked to take effect without an independent verified verdict
    on the record. The maker never certifies its own change."""


@dataclass
class ImprovementProposal:
    target: ProposalTarget
    proposal: str                 # the change, plainly
    rationale: str                # why the record justifies it
    source: str = "self"          # self / local / team:<who> / youtube:<url> / …
    evidence_ids: list[str] = field(default_factory=list)  # openable ledger entries
    supply_chain_note: str = ""   # REQUIRED for an external skill:add (the W1 "why")

    def __post_init__(self):
        if not isinstance(self.target, ProposalTarget):
            self.target = ProposalTarget(str(self.target))
        if is_effectively_blank(self.proposal) or is_effectively_blank(self.rationale):
            raise ValueError("a proposal needs a plain proposal and a rationale")
        # W1: an external, untrusted skill:add must state its supply-chain reasoning.
        if self.target == ProposalTarget.SKILL_ADD and not self._source_trusted():
            if is_effectively_blank(self.supply_chain_note):
                raise W1RefusalError(
                    f"skill:add from untrusted source {self.source!r} must state its "
                    "supply-chain reasoning (is it verified? does it duplicate an "
                    "existing skill? what is the risk?) — W1 refuses auto-installed "
                    "skills; a human installs, and needs the WHY to weigh.")

    def _source_trusted(self) -> bool:
        head = self.source.split(":", 1)[0].strip().lower()
        return head in _TRUSTED_SOURCES

    def default_disposition(self) -> str:
        """The proposal's starting Y/N/T lean. An external skill:add defaults to N
        (W1) — the human must turn it to a yes explicitly."""
        if self.target == ProposalTarget.SKILL_ADD and not self._source_trusted():
            return "N"
        return "T"   # everything else starts as an open call for the human's judgment


class ImprovementEngine:
    """Stages improvement proposals and gates their application, reusing the
    reflect.py safety core exactly — this adds NO new verify or apply authority."""

    def __init__(self, ledger: Ledger, author: str,
                 verifier: Optional[Verifier] = None,
                 ground: Optional[TimeGround] = None):
        self.ledger = ledger
        self.author = author
        self.verifier = verifier
        self.ground = ground or ledger.ground

    def propose(self, p: ImprovementProposal) -> Entry:
        """Record a proposal, staged and (if a verifier is present) independently
        verified. Recorded either way; `verified` gates whether it MAY take effect.
        A proposal with no openable evidence stays unverified — an ungrounded
        change cannot 'verify' on its own words (the reflect Phase-2.6 lesson)."""
        record = {"proposal_id": uuid.uuid4().hex[:12],
                  "target": p.target.value, "proposal": p.proposal,
                  "rationale": p.rationale, "source": p.source,
                  "evidence_ids": list(p.evidence_ids),
                  "supply_chain_note": p.supply_chain_note,
                  "disposition": p.default_disposition(),
                  "verified": False, "verdict": None, "claim_id": None}
        if not p.evidence_ids:
            record["verdict"] = "insufficient"
            record["note"] = ("no openable evidence — a proposal must cite real ledger "
                              "entries an independent verifier can inspect")
            return self.ledger.append(PROPOSAL_KIND, self.author, record,
                                      tags=("improve", p.target.value, "unverified"))
        claim = CompletionClaim(
            maker=self.author,
            task=f"improvement proposal: {p.target.value}",
            summary=f"{p.proposal} — {p.rationale}",
            evidence=[Evidence(EvidenceKind.LEDGER, eid) for eid in p.evidence_ids])
        record["claim_id"] = claim.id
        if self.verifier is not None:
            verdict = self.verifier.verify(claim)      # raises if maker == verifier
            record_verdict(self.ledger, claim, verdict)
            record["verdict"] = verdict.status.value
            record["verified"] = verdict.status.value == "verified"
        return self.ledger.append(
            PROPOSAL_KIND, self.author, record,
            tags=("improve", p.target.value,
                  "verified" if record["verified"] else "unverified"))

    def ratify(self, proposal_entry_id: str, human: str) -> Entry:
        """A HUMAN accepts a proposal. Independence-guarded like every human seat:
        the proposing agent cannot ratify its own proposal, and a blank human is
        not a yes. This records the human's yes; it does NOT itself mutate anything
        — installing the skill / editing the EMP is the human's separate action."""
        if is_effectively_blank(human):
            raise ValueError("ratification names a human — a blank yes is not a yes")
        e = self.ledger.get(proposal_entry_id)
        if e is None or e.kind != PROPOSAL_KIND:
            raise KeyError(f"no improvement_proposal {proposal_entry_id}")
        if same_identity(human, e.author):
            raise UnverifiedProposalError(
                "the proposing agent cannot ratify its own proposal — ratification "
                "is the human seat (stage-don't-fire).")
        return self.ledger.append(
            kind=PROPOSAL_KIND, author=human,
            body={**e.body, "disposition": "Y", "ratified_by": human},
            tags=("improve", e.body.get("target"), "ratified"),
            supersedes=e.id)

    def can_take_effect(self, proposal_entry_id: str) -> dict:
        """A proposal may take effect ONLY if the ledger carries (a) an independent
        verified verdict for its claim AND (b) a human ratification. Re-derived from
        the append-only record, never from the proposal's own flag — the record is
        the authority. Raises if it cannot; returns the proposal body if it can."""
        e = self.ledger.get(proposal_entry_id)
        if e is None or e.kind != PROPOSAL_KIND:
            raise KeyError(f"no improvement_proposal {proposal_entry_id}")
        maker = self.author
        claim_id = e.body.get("claim_id")
        # (a) an INDEPENDENT verified verdict for this exact claim
        independent_ok = False
        if claim_id:
            for v in self.ledger.entries():
                if (v.kind == "verification" and v.body.get("claim_id") == claim_id
                        and v.body.get("status") == "verified"
                        and not same_identity(v.author, maker)):
                    independent_ok = True
                    break
        if not independent_ok:
            raise UnverifiedProposalError(
                f"proposal {e.body.get('target')!r} has no independent verified verdict "
                f"on the record (claim={claim_id}) — it cannot take effect.")
        # (b) a human ratification (disposition Y by a non-maker)
        head = next((x for x in self.ledger.active(PROPOSAL_KIND)
                     if x.body.get("proposal_id") == e.body.get("proposal_id")), e)
        if head.body.get("disposition") != "Y" or same_identity(
                head.author, maker) or is_effectively_blank(head.body.get("ratified_by", "")):
            raise UnverifiedProposalError(
                "proposal is verified but not human-ratified — a human must say yes "
                "before it takes effect (stage-don't-fire, W3).")
        return head.body

    def open_proposals(self) -> list[Entry]:
        """Proposals awaiting the human — verified-or-not, not yet ratified/denied."""
        return [e for e in self.ledger.active(PROPOSAL_KIND)
                if e.body.get("disposition") != "Y"]
