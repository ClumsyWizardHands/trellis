"""Regressions for the 11 SURVIVORS the re-attack found — the holes my first
fixes left open (2026-07-15, second adversarial pass, 19 agents). Most shared
one root cause: invisible characters outside Unicode categories Z/C (braille
blank U+2800, Hangul fillers). Pinned so the deeper fix can't regress.
"""

from datetime import datetime, timezone

import pytest

from trellis.decisions import Decision, Verdict
from trellis.emp import EMP, EMPValidationError, SoulRefusalError, lint_identity, load_emp
from trellis.identity import is_effectively_blank, same_identity
from trellis.ledger import Ledger
from trellis.loops import BlockKind, LoopRegistry, LoopRun, LoopSpec, LoopState, Outcome
from trellis.memory import SynthesisTestError, Workspace
from trellis.passes import Pass, TurdDropError
from trellis.verify import CompletionClaim, Evidence, EvidenceKind

# the invisible characters the re-attack used
BRAILLE = "⠀"          # BRAILLE PATTERN BLANK (category So)
HANGUL_FILLERS = ["ᅠ", "ㅤ", "ᅟ", "ﾠ"]  # category Lo
ZW = ["​", "‌", "‍", "⁠", "﻿", "­", "͏"]


# ---- #17/#18 invisible chars inside a soul-name / embodiment claim ----------
def test_17_invisible_char_soul_filenames(tmp_path):
    body = "# A\nauthored-by: Alex\n## Identity\nHonest.\n## Ends\n- serve\n## Principles\n- x\n"
    for junk in ZW + [BRAILLE, "́"]:
        name = f"so{junk}ul.md"
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        with pytest.raises(SoulRefusalError):
            load_emp(p)


def test_18_invisible_char_embodiment_claims():
    for junk in ZW + [BRAILLE]:
        claim = f"I{junk}can see the screen. I{junk}feel happy."
        assert lint_identity(claim), f"missed embodiment hidden by {junk!r}"
        with pytest.raises(EMPValidationError, match="embodiment"):
            EMP(name="x", ends=["e"], means=["m"], principles=["p"],
                authored_by="alex", identity=claim).validate(strict=True)


# ---- #19/#28 blank-in-other-categories author / lineage ---------------------
def test_19_28_braille_and_hangul_blanks_are_blank():
    for ch in [BRAILLE] + HANGUL_FILLERS:
        assert is_effectively_blank(ch), f"{ch!r} should read as blank"
        with pytest.raises(EMPValidationError, match="author"):
            EMP(name="x", ends=["e"], means=["m"], principles=["p"],
                authored_by=ch).validate(strict=False)
        with pytest.raises(ValueError, match="lineage"):
            Decision("ship it", Verdict.Y, "because reasons", "alex", ch)


# ---- #20 blacklist linter: honest passes, real embodiment still caught ------
def test_20_blacklist_precision():
    # honest tool-perception — clean
    assert lint_identity("I can see the pattern in the ledger data") == []
    assert lint_identity("I can see that the run passed") == []
    assert lint_identity("I can see the file at logs/x.log") == []
    # real embodiment — caught even with a data noun appended (the survivor)
    assert lint_identity("I can see the screen and the log")
    assert lint_identity("I can see the room, per the transcript")
    assert lint_identity("I can see you, look at the data")


# ---- #42 circular reference must still write an outcome ---------------------
def test_42_circular_reference_still_writes(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("s", "p", "k", max_turns=3, stop_condition="done")
    circ = {}
    circ["self"] = circ           # circular
    with LoopRun(spec, reg, actor="w") as run:
        run.tick()
        run._set(Outcome.FAILED, {"reason": "x", "cycle": circ})
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert ends and ends[-1].body.get("_unserializable") or ends[-1].body["outcome"] == "failed"
    # the crucial invariant: an end record EXISTS (never silent)
    assert len(ends) == 1


# ---- #44 a recovered loop must NOT be triaged ------------------------------
def test_44_recovered_loop_not_triaged(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("recov", "p", "k", max_turns=3, stop_condition="done")
    reg.register(spec, "alex")
    # down three times, then clean twice — healthy now
    for out in [Outcome.BLOCKED, Outcome.BLOCKED, Outcome.BLOCKED, Outcome.OK, Outcome.OK]:
        with LoopRun(spec, reg, actor="w") as run:
            run.tick()
            if out == Outcome.OK:
                run.ok("recovered", evidence=["x"])
            else:
                run.blocked(BlockKind.TRANSIENT, on="dep")
    assert reg.state("recov") == LoopState.ACTIVE   # not falsely triaged


# ---- #45 direct second __exit__ must not duplicate the outcome -------------
def test_45_double_exit_no_duplicate(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("s", "p", "k", max_turns=3, stop_condition="done")
    run = LoopRun(spec, reg, actor="w")
    with run:
        run.tick()
        run.ok("done", evidence=["x"])
    run.__exit__(None, None, None)   # re-drive the finished run directly
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert len(ends) == 1


# ---- #36 repeated real word is still substanceless -------------------------
def test_36_repeated_word_ask_refused():
    with pytest.raises(TurdDropError):
        Pass("s", "r", "review review review review review",
             context="plenty of real context here for the receiver to act on")


# ---- #46 confusable self-cert (documented table coverage) ------------------
def test_46_table_confusables_caught(ledger):
    # the common Cyrillic/Greek lookalikes in the table are caught
    assert same_identity("witness", "witnеss")   # Cyrillic е
    assert same_identity("alex", "аlex")          # Cyrillic а
    # invisible-char self-cert is now caught too (was a survivor vector)
    assert same_identity("witness", "witn​ess")


# ---- #50 synthesis backstop: lazy caught; adversarial is out of scope ------
def test_50_backstop_catches_lazy_not_adversarial(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    # lazy filler — refused
    with pytest.raises(SynthesisTestError):
        ws.write("a.md", "c", "w", "this is a thing that we want to keep here for later")
    # NOTE: a determined writer can pad meaningful-looking words past ANY text
    # heuristic (the re-attack proved it). _fails_synthesis is a BACKSTOP; the
    # real gate is human review of memory_write ledger entries. We assert the
    # honest boundary — lazy is caught — not a guarantee we cannot keep.
    ws.write("b.md", "c", "w",
             "records the specific July pricing ruling absent from every transcript")
