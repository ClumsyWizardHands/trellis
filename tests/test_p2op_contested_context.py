"""D35: a contested decision (independent verifier REFUTED it) is dropped from the
trusted read the compiler builds — it stays on the record but must not silently
ground a fresh opinion while it awaits human resolution."""

from trellis.context import ContextCompiler
from trellis.decisions import DecisionLog, Decision
from trellis.verify import CONTESTED_KIND


def test_contested_decision_is_excluded_from_the_compiled_read(ledger, ground):
    log = DecisionLog(ledger, ground)
    entry = log.record(Decision(subject="the pricing framing for july",
                                verdict="Y", rationale="agreed in the room",
                                author="witness:w", emp_lineage="emp:1"))
    # baseline: a relevant active decision is compiled in
    cc = ContextCompiler(ledger, ground).compile(subjects=["pricing framing july"])
    assert any(i.source_id == entry.id for i in cc.items), "sanity: it should be included"

    # now an independent verifier contests it
    ledger.append(kind=CONTESTED_KIND, author="haiku:verifier",
                  body={"subject_id": entry.id, "escalated": True})
    cc2 = ContextCompiler(ledger, ground).compile(subjects=["pricing framing july"])
    assert not any(i.source_id == entry.id for i in cc2.items), "contested must be withheld"
    reasons = " ".join(x["reason"] for x in cc2.manifest.excluded)
    assert "contested" in reasons
