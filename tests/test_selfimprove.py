"""Phase 1 — the self-improvement engine's spine.

Pins the invariants from docs/PLAN-self-improvement-engine.md: the agent proposes
its own repair but never applies it (no self-application, no self-certification,
W1 default-N on untrusted skills, human-gated ratification), and the skill estate
dedups on the capability key so 'is there already a skill?' folds, never forks."""

import pytest

from trellis.selfimprove import (ImprovementEngine, ImprovementProposal,
                                 ProposalTarget, SkillEstate, SkillNode, SkillTrust,
                                 UnverifiedProposalError, W1RefusalError,
                                 capability_key)
from trellis.verify import RuleVerifier


# ----- the capability estate: dedup, don't duplicate ----------------------

def test_skill_estate_folds_not_forks_on_reworded_capability(ledger, ground):
    est = SkillEstate(ledger, ground)
    est.register(SkillNode("Summarize a Google Doc", "condenses a doc", "local"), "witness")
    # the SAME capability, re-cased / re-spaced, must fold onto one node, not fork
    # (the fold is homoglyph/case, like question_key — not a spelling-variant merge)
    est.register(SkillNode("summarize  a  google doc", "condenses a doc", "local"), "witness")
    assert len(est.active_skills()) == 1


def test_find_answers_is_there_already_a_skill(ledger, ground):
    est = SkillEstate(ledger, ground)
    est.register(SkillNode("Transcribe an audio note", "whisper → text", "local"), "witness")
    hits = est.find("transcribe audio")
    assert hits and "Transcribe" in hits[0][0]
    assert est.find("make a pdf") == []           # honestly, no such skill


def test_only_a_human_promotes_a_skill_tier(ledger, ground):
    est = SkillEstate(ledger, ground)
    e = est.register(SkillNode("Draft a release note", "writes notes", "team:sarah"), "witness")
    sid = e.body["skill_id"]
    with pytest.raises(ValueError):
        est.promote(sid, human="   ", to=SkillTrust.LOCAL_REVIEWED)   # blank human
    promoted = est.promote(sid, human="alex", to=SkillTrust.LOCAL_REVIEWED)
    assert promoted.body["trust"] == "local-reviewed"
    assert promoted.body["reviewed_by"] == "alex"


# ----- the proposal: staged, verified, human-gated ------------------------

def _evidence(ledger):
    e1 = ledger.append("decision", "witness", {"decision_id": "d1", "subject": "a real burn"})
    e2 = ledger.append("decision", "witness", {"decision_id": "d2", "subject": "another"})
    return [e1.id, e2.id]


def test_proposal_with_no_evidence_cannot_take_effect(ledger, ground):
    eng = ImprovementEngine(ledger, author="witness",
                            verifier=RuleVerifier("verifier:check", ledger=ledger, ground=ground),
                            ground=ground)
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS,
                    "check the calendar before resolving a time question",
                    "the read mis-dated a call", evidence_ids=[]))
    assert p.body["verified"] is False
    with pytest.raises(UnverifiedProposalError):
        eng.can_take_effect(p.id)


def test_verified_and_ratified_proposal_can_take_effect(ledger, ground):
    eng = ImprovementEngine(ledger, author="witness",
                            verifier=RuleVerifier("verifier:check", ledger=ledger, ground=ground),
                            ground=ground)
    ev = _evidence(ledger)
    p = eng.propose(ImprovementProposal(ProposalTarget.EMP_FRICTION,
                    "record the recurring ownership burn",
                    "it recurred and is grounded on the record", evidence_ids=ev))
    assert p.body["verified"] is True
    # verified but NOT yet ratified → still cannot take effect (stage-don't-fire)
    with pytest.raises(UnverifiedProposalError):
        eng.can_take_effect(p.id)
    ratified = eng.ratify(p.id, human="alex")
    assert eng.can_take_effect(ratified.id)["disposition"] == "Y"


def test_agent_cannot_ratify_its_own_proposal(ledger, ground):
    eng = ImprovementEngine(ledger, author="witness",
                            verifier=RuleVerifier("verifier:check", ledger=ledger, ground=ground),
                            ground=ground)
    p = eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "change X", "because Y",
                    evidence_ids=_evidence(ledger)))
    with pytest.raises(UnverifiedProposalError):
        eng.ratify(p.id, human="witness")            # the maker, disguised as the human
    with pytest.raises(UnverifiedProposalError):
        eng.ratify(p.id, human="WITNESS")            # normalized self-ratification


def test_proposal_cannot_self_certify(ledger, ground):
    from trellis.verify import SelfCertificationError
    # the verifier shares the maker's identity → self-cert must raise at propose()
    eng = ImprovementEngine(ledger, author="witness",
                            verifier=RuleVerifier("witness", ledger=ledger, ground=ground),
                            ground=ground)
    with pytest.raises(SelfCertificationError):
        eng.propose(ImprovementProposal(ProposalTarget.PROCESS, "change X", "because Y",
                    evidence_ids=_evidence(ledger)))


# ----- W1: external skills are default-N and must state the why ------------

def test_external_skill_add_must_state_supply_chain_reasoning(ledger, ground):
    with pytest.raises(W1RefusalError):
        ImprovementProposal(ProposalTarget.SKILL_ADD,
                            "add the youtube skill", "it looked cool",
                            source="youtube:https://x", evidence_ids=["e"])  # no supply-chain note


def test_external_skill_add_defaults_to_N(ledger, ground):
    p = ImprovementProposal(ProposalTarget.SKILL_ADD,
                            "add the youtube skill", "might help with pdfs",
                            source="youtube:https://x",
                            supply_chain_note="unverified author; duplicates make-pdf; risk medium")
    assert p.default_disposition() == "N"          # W1: external adds start as a no


def test_trusted_skill_add_is_not_forced_to_N(ledger, ground):
    p = ImprovementProposal(ProposalTarget.SKILL_ADD, "add the local pdf skill",
                            "we wrote it", source="local", evidence_ids=["e"])
    assert p.default_disposition() == "T"          # trusted source: an open call, not a default-no


def test_capability_key_folds_homoglyphs_and_case():
    assert capability_key("Summarize a Doc") == capability_key("summarize a doc")


# ----- Phase 2: the confusion harvest -------------------------------------

from trellis.selfimprove import (ConfusionHarvest, PerformedConfusionError,
                                 FRICTION_KIND)


def test_harvest_turns_a_protocol_violation_into_friction(ledger, ground):
    ledger.append("loop_run_end", "witness",
                  {"run_id": "r1", "loop": "witness.watch", "outcome": "protocol_violation"})
    h = ConfusionHarvest(ledger, agent_id="witness", ground=ground)
    burns = h.harvest()
    assert len(burns) == 1 and burns[0].body["stumble"] == "protocol_violation"
    assert burns[0].body["source_ref"]                    # grounded in the real entry
    assert "protocol_violation" in h.harvested_friction()[0]


def test_harvest_catches_self_refutation(ledger, ground):
    ledger.append("verification", "verifier:check",
                  {"claim_id": "c1", "maker": "witness", "status": "refuted"})
    burns = ConfusionHarvest(ledger, "witness", ground).harvest()
    assert any(b.body["stumble"] == "self_refuted" for b in burns)


def test_harvest_catches_a_human_correction_of_the_agent(ledger, ground):
    mine = ledger.append("decision", "witness", {"decision_id": "d1", "subject": "my read"})
    ledger.append("decision", "alex", {"decision_id": "d1b", "subject": "corrected read"},
                  supersedes=mine.id)
    burns = ConfusionHarvest(ledger, "witness", ground).harvest()
    assert any(b.body["stumble"] == "human_correction" for b in burns)


def test_harvest_is_idempotent(ledger, ground):
    ledger.append("loop_run_end", "witness", {"run_id": "r1", "outcome": "failed", "reason": "x"})
    h = ConfusionHarvest(ledger, "witness", ground)
    first = h.harvest()
    second = h.harvest()                                  # re-run: no double-count
    assert len(first) == 1 and len(second) == 0
    assert len([e for e in ledger.active(FRICTION_KIND)]) == 1


def test_harvest_catches_a_dry_streak_once_per_question(ledger, ground):
    from trellis.curiosity import QuestionLog, Question, assumption_key
    from datetime import timedelta
    ql = QuestionLog(ledger, ground)
    ql.ask(Question("q title", "the funder is aligned", "a statement", "witness",
                    ground.now() + timedelta(days=2)), "witness")
    ak = assumption_key("the funder is aligned")
    ql.record_seek(ak, "searched", map_changed=False, delta_refs=[], author="witness")
    ql.record_seek(ak, "searched again", map_changed=False, delta_refs=[], author="witness")
    h = ConfusionHarvest(ledger, "witness", ground)
    burns = h.harvest(dry_streak_threshold=2)
    dry = [b for b in burns if b.body["stumble"] == "dry_streak"]
    assert len(dry) == 1 and dry[0].body["assumption_key"] == ak
    assert h.harvest(dry_streak_threshold=2) == []        # once per assumption


def test_performed_confusion_is_refused(ledger, ground):
    h = ConfusionHarvest(ledger, "witness", ground)
    from trellis.selfimprove import Burn
    with pytest.raises(PerformedConfusionError):
        h._record(Burn("I feel afraid and inadequate about being forgotten", "x", "protocol_violation"),
                  "witness")


def test_recurring_burns_surface_as_proposal_candidates(ledger, ground):
    for i in range(2):
        ledger.append("loop_run_end", "witness",
                      {"run_id": f"r{i}", "outcome": "protocol_violation"})
    h = ConfusionHarvest(ledger, "witness", ground)
    h.harvest()
    rec = h.recurring_burns(min_count=2)
    assert any(r["stumble"] == "protocol_violation" and r["count"] == 2 for r in rec)


def test_harvested_friction_reaches_the_prompt_within_budget(ledger, ground):
    """The loop closes: a burn recorded today is read by tomorrow's standing
    prompt (bounded, never blowing the 1,200-token budget)."""
    from trellis.emp import EMP
    from trellis.prompt import assemble_prompt, estimate_tokens, PROMPT_TOKEN_BUDGET
    from trellis.surfaces import ConversationKey, Surface
    ledger.append("loop_run_end", "witness", {"run_id": "r1", "outcome": "protocol_violation"})
    h = ConfusionHarvest(ledger, "witness", ground)
    h.harvest()
    burns = h.harvested_friction()
    emp = EMP(name="witness", ends=["read the room"], means=["files"],
              principles=["say no when needed"], authored_by="alex")
    key = ConversationKey(agent="witness", surface=Surface.CHANNEL, scope="chiefs", human="")
    prompt = assemble_prompt(emp, ground, key, recent_burns=burns)
    assert "Recent burns" in prompt and "protocol_violation" in prompt
    assert estimate_tokens(prompt) <= PROMPT_TOKEN_BUDGET
