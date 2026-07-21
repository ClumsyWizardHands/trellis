"""Decision lineage is referentially checked, not just non-blank (Codex Medium 12).

An opinion citing an EMP node that doesn't exist is a fabricated lineage — the
Witness rejects it loudly instead of minting a decision that claims to express a
principle the EMP doesn't have. (Honest boundary: authored_by and POV bases remain
CLAIMED provenance, reviewed by a human — see the acceptance doctrine.)"""

from trellis.emp import EMP


def _emp():
    return EMP(name="witness", ends=["read the room", "hold a view"],
              means=["files"], principles=["say no when needed", "stage don't fire"],
              authored_by="alex")


def test_emp_knows_its_real_nodes():
    e = _emp()
    assert e.has_node("EMP:ends[0]") and e.has_node("EMP:ends[1]")
    assert e.has_node("EMP:principles[1]")
    assert not e.has_node("EMP:ends[5]")        # out of range
    assert not e.has_node("EMP:nope[0]")        # no such section
    assert not e.has_node("")                    # blank


def test_witness_rejects_a_fabricated_lineage(ledger, ground, tmp_path):
    from trellis.agent import Witness, Event
    from trellis.memory import Workspace
    from trellis.surfaces import ConversationKey, Surface
    from trellis.providers.mock import MockProvider
    ws = Workspace(tmp_path / "ws", ledger)
    key = ConversationKey("witness", Surface.CHANNEL, "chiefs", "")
    w = Witness(_emp(), MockProvider(id="m"), ledger, ws, key, ground=ground)
    # the model returns two opinions: one with a REAL node, one FABRICATED
    w.provider.enqueue_text('[{"subject":"a real call","verdict":"Y","rationale":"grounded",'
                            '"emp_lineage":"EMP:ends[0]"},'
                            '{"subject":"a phantom call","verdict":"Y","rationale":"x",'
                            '"emp_lineage":"EMP:ends[9]"}]')
    w.witness_cycle([Event("brett", "let's decide", ground.now())])
    subjects = {e.body.get("subject") for e in ledger.active("decision")}
    assert "a real call" in subjects
    assert "a phantom call" not in subjects      # fabricated lineage → not minted
    rejected = [e for e in ledger.entries() if e.kind == "opinion_rejected"]
    assert rejected and rejected[0].body["emp_lineage"] == "EMP:ends[9]"
