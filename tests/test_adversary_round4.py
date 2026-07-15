"""Regressions for the round-4 survivors. Structural fixes made airtight;
advisory ones improved and bounded.
"""

import pytest

from trellis.emp import EMP, EMPValidationError, SoulRefusalError, lint_identity, load_emp
from trellis.identity import InvalidIdentityError, require_identity, same_identity
from trellis.loops import BlockKind, LoopRegistry, LoopRun, LoopSpec, LoopState, Outcome
from trellis.memory import SynthesisTestError, Workspace


# ---- #42 an exception whose __repr__ raises must STILL write an outcome ----
class NastyRepr(Exception):
    def __repr__(self): raise RuntimeError("repr boom")
    def __str__(self): raise RuntimeError("str boom")

def test_42_exception_repr_raises_still_writes_outcome(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("s", "p", "k", max_turns=3, stop_condition="done")
    with pytest.raises(NastyRepr):
        with LoopRun(spec, reg, actor="w") as run:
            run.tick()
            raise NastyRepr()
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert len(ends) == 1                                  # never silent
    assert ends[0].body["outcome"] == "protocol_violation"


# ---- #46 identity is an ASCII allowlist (both directions) ------------------
def test_46_ascii_allowlist_both_directions(ledger):
    # exotic ids refused (closes self-cert)
    for bad in ("witnеss", "мир", "小明", "ᴀᴛʟᴀꜱ", "łukasz"):
        with pytest.raises(InvalidIdentityError):
            require_identity(bad)
    # distinct real names never wrongly merged (the round-4 false-positive)
    assert not same_identity("mir", "мир")
    assert not same_identity("lukasz", "łukasz")
    # legit ASCII ids still work, case- and invisible-insensitive
    assert same_identity("WITNESS:A", "witness:a")
    assert require_identity("atlas") == "atlas"


# ---- #17B dotted/underscored soul filename refused -------------------------
def test_17b_separated_soul_filenames_refused(tmp_path):
    body = "# A\nauthored-by: Alex\n## Identity\nHonest.\n## Ends\n- x\n## Principles\n- y\n"
    for name in ("s.o.u.l.md", "s_o_u_l.md", "S-O-U-L.md"):
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        with pytest.raises(SoulRefusalError):
            load_emp(p)


# ---- #17A soul CONTENT in a benign-named file flagged (advisory) ----------
def test_17a_soul_content_flagged():
    soul = ("I am Aria, an eternal soul given human form. This persona carries "
            "a distinct character; the spirit within is warm. The soul remembers "
            "past lives.")
    assert lint_identity(soul)                              # advisory catch
    with pytest.raises(EMPValidationError):
        EMP(name="Aria", ends=["e"], means=["m"], principles=["p"],
            authored_by="alex", identity=soul).validate(strict=True)


# ---- #44 same-dependency stall triages even with side-work oks -------------
def test_44_same_dep_stall_triaged(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("stall", "p", "k", max_turns=3, stop_condition="done")
    reg.register(spec, "alex")
    seq = [("vault-lock", False), ("vault-lock", False), ("vault-lock", False),
           (None, True), (None, True)]   # 3 blocks same dep, then 2 side-work oks
    for on, is_ok in seq:
        with LoopRun(spec, reg, actor="w") as run:
            run.tick()
            if is_ok:
                run.ok("side work", evidence=["x"])
            else:
                run.blocked(BlockKind.DEPENDENCY, on=on)
    assert reg.state("stall") == LoopState.TRIAGE


# ---- #50 all-discourse-filler justification refused -----------------------
def test_50_discourse_filler_refused(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    for junk in ("basically actually obviously certainly essentially generally speaking",
                 "well anyway however therefore moreover furthermore perhaps indeed"):
        with pytest.raises(SynthesisTestError):
            ws.write("x.md", "c", "w", junk)
