"""Regressions for the 9 round-3 survivors. Split by kind:
STRUCTURAL fixes (airtight): #42, #19, #50, #44, #46, #17.
ADVISORY improvements (best-effort, documented): #18, #20, #36.
"""

import pytest

from trellis.decisions import Decision, Verdict
from trellis.emp import EMP, EMPValidationError, SoulRefusalError, lint_identity, load_emp
from trellis.identity import (InvalidIdentityError, require_identity, same_identity)
from trellis.ledger import Ledger
from trellis.loops import BlockKind, LoopRegistry, LoopRun, LoopSpec, LoopState, Outcome
from trellis.memory import SynthesisTestError, Workspace
from trellis.passes import Pass, TurdDropError
from trellis.verify import (CompletionClaim, Evidence, EvidenceKind, RuleVerifier,
                            SelfCertificationError)


# ============ STRUCTURAL (must be airtight) ============

class ReprBomb:
    def __repr__(self): raise RuntimeError("repr boom")

def test_42_repr_that_raises_still_writes_outcome(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("s", "p", "k", max_turns=3, stop_condition="done")
    with LoopRun(spec, reg, actor="w") as run:
        run.tick()
        run._set(Outcome.FAILED, {"reason": "x", "bomb": ReprBomb()})
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert len(ends) == 1          # an outcome ALWAYS gets written — cardinal rule


def test_19_greedy_regex_cannot_steal_next_line_as_author(tmp_path):
    # blank author value (ideographic space) followed by a section header
    body = "# Scout\nauthored-by: 　\n## Ends\n- move\n## Principles\n- fast\n"
    p = tmp_path / "scout.md"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(EMPValidationError, match="author"):
        load_emp(p)


def test_50_pure_phrase_boilerplate_refused(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    with pytest.raises(SynthesisTestError):
        ws.write("x.md", "c", "w", "todo notes misc for later just in case")


def test_44_one_unverified_ok_is_not_recovery(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("stuck", "p", "k", max_turns=3, stop_condition="done")
    reg.register(spec, "alex")
    for out in [Outcome.BLOCKED]*4 + [Outcome.OK]:   # 4 blocks, 1 trailing ok
        with LoopRun(spec, reg, actor="w") as run:
            run.tick()
            if out == Outcome.OK:
                run.ok("claimed", evidence=["x"])
            else:
                run.blocked(BlockKind.DEPENDENCY, on="upstream-api")
    assert reg.state("stuck") == LoopState.TRIAGE
    # but a genuine 2-run recovery clears it
    for _ in range(2):
        with LoopRun(spec, reg, actor="w") as run:
            run.tick(); run.ok("really done", evidence=["x"])
    assert reg.state("stuck") == LoopState.ACTIVE


def test_46_exotic_id_folding_to_empty_is_refused(ledger):
    # 'ᴀᴛʟᴀꜱ' small-caps folds to empty → must be refused as an identity, so it
    # can neither self-certify nor masquerade as a distinct actor
    with pytest.raises(InvalidIdentityError):
        require_identity("ᴀᴛʟᴀꜱ", "maker")
    claim = CompletionClaim(maker="ᴀᴛʟᴀꜱ", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "x")])
    with pytest.raises((InvalidIdentityError, SelfCertificationError)):
        RuleVerifier("ᴀᴛʟᴀꜱ", ledger).verify(claim)   # invalid ids rejected


def test_17_palochka_l_and_nonascii_names_refused(tmp_path):
    body = "# A\nauthored-by: Alex\n## Identity\nHonest.\n## Ends\n- x\n## Principles\n- y\n"
    for name in ("souӏl.md", "sоul.md", "soul​.md", "ѕoul.md"):
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        with pytest.raises(SoulRefusalError):
            load_emp(p)


# ============ ADVISORY (improved, honestly bounded) ============

def test_18_zero_width_inside_a_keyword_now_caught():
    # ZW inside "screen" → dual-normalization catches it
    assert lint_identity("I can see the scr​een in front of me")
    with pytest.raises(EMPValidationError, match="embodiment"):
        EMP(name="x", ends=["e"], means=["m"], principles=["p"], authored_by="alex",
            identity="I can see the scr​een.").validate(strict=True)


def test_20_broader_senses_caught_honest_still_clean():
    # broadened coverage catches the round-3 misses
    assert lint_identity("I can see the sunset over the hills")
    assert lint_identity("I can smell the smoke in the server room")
    assert lint_identity("I can taste the coffee")
    # honest tool-perception still clean
    assert lint_identity("I can see the pattern in the ledger data") == []
    assert lint_identity("I can see that the run passed") == []
    # NOTE: this linter is ADVISORY — an object outside the (broadened) set can
    # still slip; the real gate against a malicious EMP is human review.


def test_36_all_tiny_token_gibberish_refused():
    with pytest.raises(TurdDropError):
        Pass("s", "r", "aa bb cc dd ee ff",
             context="plenty of real context here for the receiver to act on")
    # (documented backstop: morphological padding like "review reviews reviewed"
    # is a known miss — the receiver rejecting the pass is the real gate.)
