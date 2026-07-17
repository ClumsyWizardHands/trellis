"""Phase C — the contemplation loop with teeth.

Pins the anti-satisficing spine: questions are staleness-railed nodes, reworded
curiosities fold not fork, a dry seek doesn't advance understanding, and closing
a question requires evidence the map actually moved."""

from datetime import timedelta

import pytest

from trellis.curiosity import (NotResolvedError, Question, QuestionLog,
                               assumption_key)


def _q(assumption="the funder is aligned on pricing", title=None, ground=None,
       days=3):
    return Question(
        title=title or "Am I assuming the funder is aligned on pricing?",
        assumption=assumption,
        what_would_resolve="a direct statement from the funder, or Brett confirming it",
        owner="witness", revisit_at=ground.now() + timedelta(days=days))


def test_reworded_curiosity_folds_not_forks(ledger, ground):
    ql = QuestionLog(ledger, ground)
    ql.ask(_q(assumption="the funder is aligned on pricing", ground=ground), "witness")
    # same assumption, different wording of the title — must NOT be a new node
    ql.ask(_q(assumption="the funder IS aligned on pricing!!", title="different words",
              ground=ground), "witness")
    assert len(ql.open_questions()) == 1
    assert ql.open_questions()[0].body["reasked"] == 1


def test_open_question_past_revisit_is_stale(ledger, ground, clock):
    ql = QuestionLog(ledger, ground)
    ql.ask(_q(ground=ground, days=2), "witness")
    assert ql.stale() == []
    clock.advance(days=3)
    stale = ql.stale()
    assert len(stale) == 1 and "funder" in stale[0].body["assumption"]


def test_a_dry_seek_does_not_advance_understanding(ledger, ground):
    ql = QuestionLog(ledger, ground)
    ql.ask(_q(ground=ground), "witness")
    ak = assumption_key("the funder is aligned on pricing")
    ql.record_seek(ak, "searched the transcripts for 'funder pricing'",
                   map_changed=False, delta_refs=[], author="witness")
    ql.record_seek(ak, "searched Discord again", map_changed=False, delta_refs=[],
                   author="witness")
    assert ql.dry_streak(ak) == 2                 # keeps looking, nothing moves
    assert len(ql.open_questions()) == 1          # still OPEN — not satisfied


def test_cannot_close_a_question_on_nothing_new(ledger, ground):
    ql = QuestionLog(ledger, ground)
    ql.ask(_q(ground=ground), "witness")
    ak = assumption_key("the funder is aligned on pricing")
    with pytest.raises(NotResolvedError):
        ql.resolve(ak, "I looked and I feel good about it", evidence_refs=[],
                   author="witness")
    # a fabricated ref that doesn't exist is also refused
    with pytest.raises(NotResolvedError):
        ql.resolve(ak, "trust me", evidence_refs=["deadbeef"], author="witness")


def test_closing_requires_evidence_the_map_moved(ledger, ground, clock):
    ql = QuestionLog(ledger, ground)
    ql.ask(_q(ground=ground), "witness")
    ak = assumption_key("the funder is aligned on pricing")
    clock.advance(hours=1)
    # the map MOVES: a new observation is recorded after the question was asked
    moved = ledger.append("decision", "observer:witness",
                          {"decision_id": "x", "subject": "funder confirmed pricing",
                           "question_key": "obs:zzz", "verdict": "Y"})
    ql.record_seek(ak, "found the funder's confirmation in Friday's transcript",
                   map_changed=True, delta_refs=[moved.id], author="witness")
    entry = ql.resolve(ak, "the funder confirmed alignment on Friday",
                       evidence_refs=[moved.id], author="witness")
    assert entry.body["status"] == "resolved"
    assert ql.open_questions() == []              # honestly closed, with receipts


def test_stale_evidence_from_before_the_question_does_not_count(ledger, ground, clock):
    """Evidence that predates the question can't 'resolve' it — the map has to
    have moved SINCE we started wondering."""
    old = ledger.append("decision", "observer:witness",
                        {"decision_id": "old", "subject": "prior note", "verdict": "Y",
                         "question_key": "obs:old"})
    clock.advance(hours=1)
    ql = QuestionLog(ledger, ground)
    ql.ask(_q(ground=ground), "witness")
    ak = assumption_key("the funder is aligned on pricing")
    with pytest.raises(NotResolvedError):
        ql.resolve(ak, "pointing at an old note", evidence_refs=[old.id], author="witness")
