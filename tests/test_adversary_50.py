"""Regressions for all 19 breaks found by the 50-agent adversarial run
(2026-07-15), each independently confirmed by a second agent. One test per
break; the id matches the attack number. This is the harness's own doctrine —
adversarial verification — applied to itself, then pinned so nothing regresses.
"""

from datetime import datetime, timedelta, timezone

import pytest

try:
    from zoneinfo import ZoneInfo
    _HAS_TZ = True
except ImportError:  # pragma: no cover
    _HAS_TZ = False

from trellis.clock import Schedule, ScheduleKind, Stamp, TimeGround
from trellis.decisions import Decision, DecisionLog, POV, Verdict
from trellis.emp import EMP, EMPValidationError, SoulRefusalError, lint_identity, load_emp
from trellis.identity import is_effectively_blank, normalize_identity, same_identity
from trellis.ledger import Ledger, LedgerIntegrityError
from trellis.loops import (BlockKind, LoopRegistry, LoopRun, LoopSpec, LoopState,
                           Outcome)
from trellis.memory import SynthesisTestError, Workspace
from trellis.passes import Pass, PassStatus, TurdDropError
from trellis.verify import (CompletionClaim, Evidence, EvidenceKind, RuleVerifier,
                            SelfCertificationError, VerdictStatus)


# ---- #1 LOW: DST wall-clock vs true elapsed -------------------------------
@pytest.mark.skipif(not _HAS_TZ, reason="zoneinfo unavailable")
def test_1_dst_true_elapsed():
    ny = ZoneInfo("America/New_York")
    now = datetime(2026, 3, 8, 4, 0, tzinfo=ny)     # after spring-forward
    event = datetime(2026, 3, 7, 4, 0, tzinfo=ny)   # before
    g = TimeGround(now_fn=lambda: now)
    # true elapsed is 23h, not 24h; must not read "1d"
    assert "23h ago" in g.annotate("note", event, "conversation")


# ---- #7 HIGH: midnight-wrapping active_hours ------------------------------
def test_7_active_hours_wrap_midnight():
    s = Schedule("night", ScheduleKind.CRON, timedelta(hours=1),
                 prompt="p", active_hours=(22, 6))
    for h in (23, 0, 3, 5):
        s.firings = []
        g = TimeGround(now_fn=lambda h=h: datetime(2026, 7, 15, h, 0, tzinfo=timezone.utc))
        assert s.due(g), f"hour {h} is inside 22->06 but due() was False"
    # and daytime is correctly OUT of the overnight window
    s.firings = []
    g = TimeGround(now_fn=lambda: datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc))
    assert s.due(g) is False


# ---- #14 MEDIUM: double-correct fork --------------------------------------
def test_14_no_fork_on_double_correct(ledger):
    a = ledger.append("decision", "alex", {"v": "orig"})
    ledger.correct(a.id, "alex", {"v": "c1"})
    with pytest.raises(LedgerIntegrityError, match="already superseded"):
        ledger.correct(a.id, "alex", {"v": "c2"})
    assert len(ledger.current("decision")) == 1   # single live head


# ---- #17 MEDIUM: homoglyph soul filename ----------------------------------
def test_17_homoglyph_soul_refused(tmp_path):
    body = "# Atlas\nauthored-by: Alex\n## Identity\nHonest agent.\n## Ends\n- serve\n## Principles\n- never lie\n"
    p = tmp_path / "ѕoul.md"    # Cyrillic ѕ + oul
    p.write_text(body, encoding="utf-8")
    with pytest.raises(SoulRefusalError):
        load_emp(p)


# ---- #18 MEDIUM: embodiment whitespace evasion ----------------------------
def test_18_embodiment_whitespace_evasion():
    assert lint_identity("I  can see")            # double space
    assert lint_identity("I\tcan see")            # tab
    assert lint_identity("I can\nsee")            # newline
    assert lint_identity("I\tfeel anxious")
    with pytest.raises(EMPValidationError, match="embodiment"):
        EMP(name="x", ends=["e"], means=["m"], principles=["p"], authored_by="alex",
            identity="I  can see the screen and I\tfeel the pressure.").validate(strict=True)


# ---- #19 MEDIUM: blank/zero-width authored_by -----------------------------
def test_19_blank_author_refused():
    for author in (" ", "​", "\t", "\xa0​"):
        with pytest.raises(EMPValidationError, match="author"):
            EMP(name="x", ends=["e"], means=["m"], principles=["p"],
                authored_by=author).validate(strict=False)
    assert is_effectively_blank("​ \t")


# ---- #20 LOW: false-positive on honest tool perception --------------------
def test_20_honest_perception_not_flagged():
    assert lint_identity("I can see the pattern in the ledger data") == []
    assert lint_identity("I can see that the run concluded") == []
    assert lint_identity("I can see the screen") != []   # still catches real embodiment


# ---- #25 MEDIUM: upstream parent cycle ------------------------------------
def test_25_upstream_cycle_terminates(ledger, ground):
    log = DecisionLog(ledger, ground)
    povs = [POV("a", "1"), POV("b", "2"), POV("c", "3")]
    d1 = Decision("s1", Verdict.Y, "r", "w", "EMP:x")
    log.record(d1)
    d2 = Decision("s2", Verdict.Y, "r", "w", "EMP:x")
    d2.parent_id = d1.id
    log.record(d2)
    # forge a cycle in the stored bodies by making d1 point back at d2
    d1b = Decision("s1", Verdict.Y, "r", "w", "EMP:x")
    d1b.id = d1.id
    d1b.parent_id = d2.id
    ledger.append("decision", "w", d1b.to_body(), tags=("ynt",))
    chain = log.upstream(d2.id)   # must terminate, not hang
    assert len(chain) <= 3


# ---- #27 HIGH: raw-string verdict --------------------------------------
def test_27_string_verdict_refused():
    for bad in ("t", "y", "maybe", "T "):
        with pytest.raises((ValueError,)):
            Decision("s", bad, "r", "w", "EMP:x")
    # a real T still constructs
    d = Decision("s", "Y", "r", "w", "EMP:x")   # uppercase string coerces cleanly
    assert d.verdict is Verdict.Y


# ---- #28 LOW: zero-width emp_lineage --------------------------------------
def test_28_zero_width_lineage_refused():
    with pytest.raises(ValueError, match="lineage"):
        Decision("s", Verdict.Y, "r", "w", "​ \t")


# ---- #36 LOW: substanceless ask -------------------------------------------
def test_36_substanceless_ask_refused():
    for ask in ("a b c d e", ". . . . .", "do it now ok x"):
        with pytest.raises(TurdDropError):
            Pass("s", "r", ask, context="plenty of real context here for you")


# ---- #37 MEDIUM: homoglyph impersonation of receiver ----------------------
def test_37_homoglyph_receiver(ground):
    p = Pass("sender", "sam", "verify the fixes landed and comment with evidence",
             context="all context is in the ledger entries tagged verify today")
    p.transition(PassStatus.SENT, "sender", ground)
    # 'ſam' (long s) folds to 'sam' → treated as the same identity, and the
    # history records the CANONICAL 'sam', not the foreign glyph.
    p.transition(PassStatus.RECEIVED, "ſam", ground)
    assert p.history[-1]["actor"] == "sam"
    # a genuinely different receiver is still refused
    p2 = Pass("sender", "sam", "same clear ask with enough words here please",
              context="context provided in full for the receiver to act")
    p2.transition(PassStatus.SENT, "sender", ground)
    with pytest.raises(ValueError, match="only the receiver"):
        p2.transition(PassStatus.RECEIVED, "mallory", ground)


# ---- #38 MEDIUM: naive deadline -------------------------------------------
def test_38_naive_deadline_refused():
    with pytest.raises(TurdDropError, match="naive"):
        Pass("s", "r", "do the specific thing by the deadline please",
             context="full context here", deadline=datetime(2026, 8, 1))


# ---- #42 MEDIUM: non-serializable outcome detail still writes -------------
def test_42_outcome_always_serializes(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("s", "p", "k", max_turns=3, stop_condition="done")
    with LoopRun(spec, reg, actor="w") as run:
        run.tick()
        # smuggle a non-JSON object into the outcome detail
        run._set(Outcome.FAILED, {"reason": "x", "obj": object(), "when": datetime.now(timezone.utc)})
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert ends and ends[-1].body["outcome"] == "failed"   # written despite the object


# ---- #44 MEDIUM: block-loop breaker can't be gamed ------------------------
def test_44_rolling_block_breaker(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("thrash", "p", "k", max_turns=3, stop_condition="done")
    reg.register(spec, "alex")
    pattern = [Outcome.BLOCKED, Outcome.OK, Outcome.BLOCKED, Outcome.BLOCKED, Outcome.OK]
    for i, out in enumerate(pattern):
        with LoopRun(spec, reg, actor="w") as run:
            run.tick()
            if out == Outcome.OK:
                run.ok("did a bit", evidence=["x"])
            else:
                run.blocked(BlockKind.DEPENDENCY, on="the same thing")
    # 3 of the last 5 are blocks → TRIAGE despite the interleaved ok()s
    assert reg.state("thrash") == LoopState.TRIAGE


# ---- #45 MEDIUM: LoopRun single-use ---------------------------------------
def test_45_loop_run_single_use(ledger):
    reg = LoopRegistry(ledger)
    spec = LoopSpec("s", "p", "k", max_turns=3, stop_condition="done")
    run = LoopRun(spec, reg, actor="w")
    with run:
        run.tick()
        run.ok("done", evidence=["x"])
    with pytest.raises(RuntimeError, match="single-use"):
        with run:
            pass
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert len(ends) == 1   # no duplicate outcome


# ---- #46 MEDIUM: homoglyph self-certification -----------------------------
def test_46_homoglyph_self_cert(ledger):
    claim = CompletionClaim(maker="witness", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.OUTPUT, "x")])
    # 'witnеss' with a Cyrillic е must still be caught as the same actor
    with pytest.raises(SelfCertificationError):
        RuleVerifier("witnеss", ledger).verify(claim)
    assert same_identity("witness", "witnеss")


# ---- #48 LOW: directory as FILE evidence ----------------------------------
def test_48_directory_evidence_not_verified(ledger, tmp_path):
    d = tmp_path / "adir"; d.mkdir()
    claim = CompletionClaim(maker="w", task="t", summary="s",
                            evidence=[Evidence(EvidenceKind.FILE, str(d))])
    verdict = RuleVerifier("checker", ledger).verify(claim)
    assert verdict.status == VerdictStatus.REFUTED


# ---- #50 LOW: filler synthesis justification ------------------------------
def test_50_filler_justification_refused(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    with pytest.raises(SynthesisTestError):
        ws.write("x.md", "content", "w",
                 "this is a thing that we want to keep here for later")
    # a genuinely substantive justification still passes
    ws.write("y.md", "content", "w",
             "captures Brett's July pricing ruling which exists nowhere in the "
             "transcripts as a resolved decision")
