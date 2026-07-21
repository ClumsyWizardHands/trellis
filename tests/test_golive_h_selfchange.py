"""go-live hardening (lane H) — self-change gate integrity.

Two audits (Fable architecture, Codex sanity) confirmed the "change itself only
behind two gates" property leaked in four places, all in code that is live today.
Each test below reproduces one leak (fails on the pre-fix code) and pins the
root-cause fix:

  * FableG8 — selfimprove.ratify/reject/promote never ran the human through
    require_identity, so a Cyrillic-homoglyph ratifier passed as a *distinct*
    human (the round-4 self-cert seat identity.py claims closed).
  * can_take_effect bound independence to the ENGINE's configured author
    (self.author), not the proposal ENTRY's author — a portal hardcoding
    'witness' laundered a maker-forged verification by the live 'witness:<emp>'.
  * ImprovementLoop.address closed ANY improvement question with ANY ratified
    proposal — no independent-verified-verdict requirement (only one of two gates).
  * reflect.apply_self_change required NO human ratification — an unequal gate
    vs the improvement path.
"""

import pytest

from trellis.identity import InvalidIdentityError
from trellis.selfimprove import (ImprovementEngine, ImprovementLoop,
                                  ImprovementProposal, ProposalTarget, SkillEstate,
                                  SkillNode, SkillTrust, UnverifiedProposalError)
from trellis.reflect import (ReflectionRitual, SelfChange, UnverifiedSelfChangeError)
from trellis.verify import RuleVerifier

# a Cyrillic 'е' (U+0435) inside an otherwise-ASCII 'witness' — the homoglyph seat
HOMOGLYPH_WITNESS = "witnеss"


def _evidence(ledger, author="witness"):
    e1 = ledger.append("decision", author, {"decision_id": "d1", "subject": "a real burn"})
    e2 = ledger.append("decision", author, {"decision_id": "d2", "subject": "another"})
    return [e1.id, e2.id]


# ----- FableG8: the human seats reject a homoglyph, never accept it as distinct -

def test_ratify_refuses_a_homoglyph_ratifier(ledger, ground):
    eng = ImprovementEngine(ledger, author="witness",
                            verifier=RuleVerifier("verifier:check", ledger=ledger, ground=ground),
                            ground=ground)
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "change X", "because Y",
                    evidence_ids=_evidence(ledger)))
    # pre-fix: same_identity('witnеss','witness') is False (the Cyrillic е is
    # dropped, folding to 'witnss'), so the maker slips in as a "different" human.
    # Fixed: require_identity REFUSES the non-ASCII id at the gate.
    with pytest.raises(InvalidIdentityError):
        eng.ratify(p.id, HOMOGLYPH_WITNESS)


def test_reject_refuses_a_homoglyph_human(ledger, ground):
    eng = ImprovementEngine(ledger, author="witness",
                            verifier=RuleVerifier("verifier:check", ledger=ledger, ground=ground),
                            ground=ground)
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "change X", "because Y",
                    evidence_ids=_evidence(ledger)))
    with pytest.raises(InvalidIdentityError):
        eng.reject(p.id, HOMOGLYPH_WITNESS, reason="no")


def test_promote_refuses_a_homoglyph_reviewer(ledger, ground):
    est = SkillEstate(ledger, ground)
    e = est.register(SkillNode("Draft a release note", "writes notes", "team:sarah"), "witness")
    with pytest.raises(InvalidIdentityError):
        est.promote(e.body["skill_id"], human=HOMOGLYPH_WITNESS, to=SkillTrust.LOCAL_REVIEWED)


# ----- independence is derived from the proposal ENTRY's author, not self.author -

def test_can_take_effect_binds_independence_to_the_entry_author_not_engine_author(ledger, ground):
    """A maker-forged verification (authored by the live maker 'witness:emp1')
    must NOT pass a portal that hardcodes author='witness'. Independence is a
    property of who authored the proposal on the record, not a constructor field."""
    maker = "witness:emp1"
    eng = ImprovementEngine(ledger, author=maker, ground=ground)      # no verifier
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "change X", "because Y",
                    evidence_ids=_evidence(ledger, author=maker)))
    claim_id = p.body["claim_id"]
    assert claim_id and p.body["verified"] is False
    # the MAKER forges its own 'verified' verdict on the record
    ledger.append("verification", maker,
                  {"claim_id": claim_id, "status": "verified", "maker": maker})
    ratified = eng.ratify(p.id, human="alex")                         # a real human yes
    # the PORTAL, configured with a bare 'witness', tries to let it take effect.
    portal = ImprovementEngine(ledger, author="witness", ground=ground)
    # pre-fix: maker=self.author='witness' != 'witness:emp1', so the forged verdict
    # reads as independent and the change takes effect. Fixed: maker is derived from
    # the proposal entry ('witness:emp1'), so its own verdict is not independent.
    with pytest.raises(UnverifiedProposalError):
        portal.can_take_effect(ratified.id)


def test_independent_verified_and_ratified_still_takes_effect(ledger, ground):
    """The fix must not over-block: a genuinely independent verdict + a human yes
    still lets a proposal take effect (regression guard on the derived maker)."""
    maker = "witness:emp1"
    eng = ImprovementEngine(ledger, author=maker,
                            verifier=RuleVerifier("verifier:check", ledger=ledger, ground=ground),
                            ground=ground)
    p = eng.propose(ImprovementProposal(ProposalTarget.EMP_FRICTION, "record it",
                    "grounded and recurred", evidence_ids=_evidence(ledger, author=maker)))
    assert p.body["verified"] is True
    ratified = eng.ratify(p.id, human="alex")
    assert eng.can_take_effect(ratified.id)["disposition"] == "Y"


# ----- ImprovementLoop.address needs BOTH gates, not just ratification ----------

def _recurring_burns(ledger, kind="protocol_violation", n=2):
    for i in range(n):
        ledger.append("loop_run_end", "witness", {"run_id": f"r{i}", "outcome": kind})


def test_address_requires_an_independent_verified_verdict_not_just_ratified(ledger, ground):
    from trellis.curiosity import NotResolvedError
    _recurring_burns(ledger)
    loop = ImprovementLoop(ledger, "witness", ground)
    loop.run(min_count=2)
    # a proposal with evidence but NO verifier → a claim exists, never verified
    ev = [ledger.append("decision", "witness", {"decision_id": "d", "subject": "x"}).id]
    eng = ImprovementEngine(ledger, "witness", ground=ground)         # no verifier
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "fix it",
                    "protocol_violation recurred", evidence_ids=ev))
    assert p.body["verified"] is False
    ratified = eng.ratify(p.id, human="alex")                         # human says yes...
    # ...but with NO independent verified verdict the question must stay open.
    # pre-fix: address closed on disposition=='Y' alone. Fixed: two-gate rule.
    with pytest.raises(NotResolvedError):
        loop.address("protocol_violation", ratified)
    assert len(loop.open_improvements()) == 1


def test_address_closes_when_both_gates_are_met(ledger, ground, clock):
    """Regression guard: a verified AND ratified proposal still closes the question."""
    _recurring_burns(ledger)
    loop = ImprovementLoop(ledger, "witness", ground)
    loop.run(min_count=2)
    clock.advance(hours=1)
    ev = [ledger.append("decision", "witness", {"decision_id": "d", "subject": "x"}).id]
    eng = ImprovementEngine(ledger, "witness",
                            verifier=RuleVerifier("verifier:check", ledger=ledger, ground=ground),
                            ground=ground)
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "fix it",
                    "protocol_violation recurred", evidence_ids=ev))
    ratified = eng.ratify(p.id, human="alex")
    loop.address("protocol_violation", ratified)
    assert loop.open_improvements() == []


# ----- reflect.apply_self_change: the SAME two gates as the improvement path ----

def _seed(ledger, author="witness"):
    e1 = ledger.append("decision", author, {"decision_id": "d1", "subject": "x",
                                            "question_key": "x", "verdict": "Y"})
    e2 = ledger.append("memory_write", author,
                       {"path": "reads/a.md", "title": "The read on EAF", "bytes": 5})
    return e1, e2


_GOODLEARNED = ("witness learned that Peter's asks are about findability not "
                "features, a synthesized read that exists in no single transcript")


def test_apply_self_change_requires_human_ratification_not_just_verification(ledger):
    e1, e2 = _seed(ledger)
    verifier = RuleVerifier("verifier:reflect-check", ledger)
    r = ReflectionRitual(ledger, author="witness", verifier=verifier)
    change = SelfChange(target="EMP:friction (append)",
                        proposal="record the ownership burn so it isn't repeated",
                        rationale="the burn is on the record and recurred",
                        evidence_ids=[e1.id, e2.id])
    entry = r.run("s1", "reflected on a recurring burn", _GOODLEARNED, self_change=change)
    assert entry.body["self_change"]["verified"] is True
    # verified but NOT human-ratified → cannot take effect (equal gate vs improve).
    # pre-fix: apply_self_change returned the change with only gate (a).
    with pytest.raises(UnverifiedSelfChangeError):
        r.apply_self_change(entry.id)
    # a named human ratifies → now BOTH gates are met and it may take effect
    r.ratify_self_change(entry.id, human="alex")
    applied = r.apply_self_change(entry.id)
    assert applied["target"] == "EMP:friction (append)"


def test_reflect_ratify_refuses_a_homoglyph_human(ledger):
    e1, e2 = _seed(ledger)
    verifier = RuleVerifier("verifier:reflect-check", ledger)
    r = ReflectionRitual(ledger, author="witness", verifier=verifier)
    change = SelfChange("EMP:friction (append)", "record it", "grounded",
                        evidence_ids=[e1.id, e2.id])
    entry = r.run("s1", "reflected", _GOODLEARNED, self_change=change)
    with pytest.raises(InvalidIdentityError):
        r.ratify_self_change(entry.id, human=HOMOGLYPH_WITNESS)


def test_reflect_maker_cannot_ratify_its_own_self_change(ledger):
    e1, e2 = _seed(ledger)
    verifier = RuleVerifier("verifier:reflect-check", ledger)
    r = ReflectionRitual(ledger, author="witness", verifier=verifier)
    change = SelfChange("EMP:friction (append)", "record it", "grounded",
                        evidence_ids=[e1.id, e2.id])
    entry = r.run("s1", "reflected", _GOODLEARNED, self_change=change)
    with pytest.raises(UnverifiedSelfChangeError):
        r.ratify_self_change(entry.id, human="witness")       # the maker as 'human'
    # and a maker-forged ratification (author == maker) never unlocks apply
    ledger.append("self_change_ratification", "witness",
                  {"reflection_id": entry.id, "ratified_by": "witness"})
    with pytest.raises(UnverifiedSelfChangeError):
        r.apply_self_change(entry.id)
