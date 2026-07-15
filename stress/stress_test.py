#!/usr/bin/env python3
"""trellis stress suite — adversarial, not congratulatory.

Each scenario attacks one of the refusals and records EVIDENCE (counts, timings,
failures) to STRESS-REPORT.md. The suite's stance is the verifier's stance:
try to REFUTE the harness. A scenario passes only if the attack failed.

Run:  python3 stress/stress_test.py
"""

from __future__ import annotations

import json
import random
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trellis.agent import Event, Witness
from trellis.clock import TimeGround
from trellis.decisions import Decision, DecisionLog, IncompleteTriangulationError, POV, Verdict
from trellis.emp import EMP
from trellis.ledger import Ledger
from trellis.loops import BlockKind, LoopRegistry, LoopRun, LoopSpec, Outcome
from trellis.memory import SynthesisTestError, Workspace
from trellis.passes import Pass, PassExchange, PassStatus, TurdDropError, _TRANSITIONS
from trellis.providers.mock import MockProvider
from trellis.surfaces import ConversationKey, PrivacyBoundaryError, Surface, can_flow, guard_flow
from trellis.verify import (CompletionClaim, Evidence, EvidenceKind, RuleVerifier,
                            SelfCertificationError)

random.seed(20260715)  # deterministic chaos: reproducible stress
REPORT: list[dict] = []


def scenario(name):
    def deco(fn):
        def wrapper():
            t0 = time.perf_counter()
            try:
                evidence = fn()
                ok = True
            except Exception as e:
                evidence = {"error": repr(e), "traceback": traceback.format_exc()[-1500:]}
                ok = False
            REPORT.append({"scenario": name, "attack_defeated": ok,
                           "seconds": round(time.perf_counter() - t0, 3),
                           "evidence": evidence})
            print(("PASS " if ok else "FAIL ") + name)
        return wrapper
    return deco


def fresh(tmp: Path, name: str):
    ground = TimeGround()
    ledger = Ledger(tmp / f"{name}.jsonl", ground)
    return ground, ledger


# ---------------------------------------------------------------- scenarios --

@scenario("scale: 5k ledger entries — append, supersede, search, as_of")
def s_ledger_scale(tmp=Path("stress/.work")):
    # NOTE (recorded design cost): reads are O(file) because the file IS the
    # truth and no cached index is allowed to drift. At 5k entries (a year of
    # a personal agent's decisions) everything below is sub-second. If a
    # ledger outgrows this, shard by year — do not add a drifting index.
    ground, ledger = fresh(tmp, "scale")
    t0 = time.perf_counter()
    ids = []
    for i in range(5_000):
        e = ledger.append("fact", f"agent-{i % 7}", {"n": i, "topic": f"topic-{i % 50}"},
                          event_time=datetime(2026, 1, 1, tzinfo=timezone.utc)
                          + timedelta(minutes=i))
        ids.append(e.id)
    t_append = time.perf_counter() - t0

    t0 = time.perf_counter()
    for i in random.sample(range(5_000), 100):
        ledger.correct(ids[i], "corrector", {"n": i, "fixed": True})
    t_correct = time.perf_counter() - t0

    t0 = time.perf_counter()
    hits = ledger.search("topic-13", limit=10)
    t_search = time.perf_counter() - t0
    assert hits, "search returned nothing at scale"

    t0 = time.perf_counter()
    cur = ledger.current("fact")
    t_current = time.perf_counter() - t0
    assert len(cur) == 5_000, f"supersession arithmetic broken: {len(cur)}"

    mid = datetime(2026, 1, 2, tzinfo=timezone.utc)
    as_of = ledger.as_of(mid)
    assert all(e.stamp.write_time <= mid for e in as_of)

    return {"entries": 5_000, "corrections": 100,
            "append_s": round(t_append, 2), "correct_s": round(t_correct, 2),
            "search_s": round(t_search, 3), "current_s": round(t_current, 3),
            "file_mb": round(ledger.path.stat().st_size / 1e6, 1)}


@scenario("session death: 200 chaotic runs — zero silent failures possible")
def s_session_death(tmp=Path("stress/.work")):
    ground, ledger = fresh(tmp, "death")
    reg = LoopRegistry(ledger)
    fates = {"ok": 0, "crash": 0, "wander": 0, "block": 0, "budget": 0}
    for i in range(200):
        spec = LoopSpec(name=f"chaos-{i}", purpose="p", surface_key="k",
                        max_turns=random.randint(1, 5), stop_condition="s")
        fate = random.choice(list(fates))
        fates[fate] += 1
        try:
            with LoopRun(spec, reg, actor=f"agent-{i % 5}") as run:
                run.tick()
                if fate == "ok":
                    run.ok("did it", evidence=["x"])
                elif fate == "crash":
                    raise RuntimeError(f"simulated session death {i}")
                elif fate == "wander":
                    pass  # exits silently — the classic four-hour spin
                elif fate == "block":
                    run.blocked(BlockKind.TRANSIENT, on="rate limit")
                elif fate == "budget":
                    while run.tick():
                        pass
        except RuntimeError:
            pass
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    starts = [e for e in ledger.entries() if e.kind == "loop_run_start"]
    assert len(starts) == 200 and len(ends) == 200, "a run escaped without an outcome"
    outcomes = {}
    for e in ends:
        outcomes[e.body["outcome"]] = outcomes.get(e.body["outcome"], 0) + 1
    assert outcomes.get("protocol_violation", 0) == fates["crash"] + fates["wander"]
    return {"runs": 200, "fates_injected": fates, "outcomes_recorded": outcomes,
            "silent_failures": 200 - len(ends)}


@scenario("time attack: skewed, future, and ancient events never read as current")
def s_time_attack(tmp=Path("stress/.work")):
    ground = TimeGround()
    now = ground.now()
    checked = 0
    for _ in range(2_000):
        skew_days = random.uniform(-400, 2)
        t = now + timedelta(days=skew_days)
        vol = random.choice(["conversation", "position", "commitment",
                             "principle", "fact"])
        note = ground.annotate("statement", t, volatility=vol)
        # the age is ALWAYS visible, whatever the decay class says
        if 1 <= -skew_days:
            assert ("d ago" in note or "h ago" in note or "m ago" in note), note
        # fast-rotting classes must never read fresh when old
        if skew_days < -60 and vol in ("conversation", "position", "commitment"):
            assert "[fresh" not in note, note
        # a >2x-half-life-old principle must not read fresh either
        if skew_days < -370 and vol == "principle":
            assert "[fresh" not in note, note
        if skew_days > 0:
            assert "in the future" in note, note
        checked += 1
    # naive timestamps must always raise
    naive_refused = 0
    for _ in range(50):
        try:
            from trellis.clock import Stamp
            Stamp(datetime(2026, 7, 15), now)
        except ValueError:
            naive_refused += 1
    assert naive_refused == 50
    return {"annotations_checked": checked, "naive_stamps_refused": naive_refused}


@scenario("pass fuzz: 3000 random transitions — illegal ones always refused, none lost")
def s_pass_fuzz(tmp=Path("stress/.work")):
    ground = TimeGround()
    ex = PassExchange(tmp / "exchange-fuzz", ground)
    all_status = list(PassStatus)
    refused = accepted = 0
    passes = []
    for i in range(60):
        p = Pass(sender=f"a{i % 4}", receiver=f"b{i % 3}",
                 ask="do the specific thing and report evidence by friday",
                 context="all context provided here in detail for the receiver")
        passes.append(p)
    for _ in range(3000):
        p = random.choice(passes)
        target = random.choice(all_status)
        legal = target in _TRANSITIONS[p.status]
        # fuzz both as the authorized side and as an impersonator
        side = Pass._ACTOR_SIDE.get(target)
        authorized = p.sender if side == "sender" else p.receiver
        actor = random.choice([authorized, "impersonator"])
        should_pass = legal and (side is None or actor == authorized)
        try:
            p.transition(target, actor, ground)
            assert should_pass, f"unauthorized/illegal transition allowed: {actor} -> {target}"
            accepted += 1
        except ValueError:
            assert not should_pass, f"authorized legal transition refused: {p.status} -> {target}"
            refused += 1
    for p in passes:
        ex.save(p)
    assert len(ex.all()) == 60
    # turd-drops always refused
    turds = 0
    for ask in ("", "help", "look at this", "thoughts on this one?"):
        try:
            Pass("a", "b", ask, context="ctx is fine and long enough here")
        except TurdDropError:
            turds += 1
    assert turds == 4
    return {"transitions_attempted": 3000, "legal_accepted": accepted,
            "illegal_refused": refused, "passes_persisted": 60,
            "turd_drops_refused": turds}


@scenario("privacy fuzz: 5000 random flows — DM->public always blocked without a token")
def s_privacy_fuzz(tmp=Path("stress/.work")):
    ground, ledger = fresh(tmp, "privacy")
    surfaces = list(Surface)
    humans = ["sarah", "brett", "clare", ""]
    blocked = allowed = 0
    for _ in range(5000):
        src = ConversationKey("a", random.choice(surfaces), "s1", random.choice(humans))
        dst = ConversationKey("a", random.choice(surfaces), "s2", random.choice(humans))
        try:
            guard_flow(src, dst)
            allowed += 1
            assert dst.privacy_rank() >= src.privacy_rank()
            if src.surface == Surface.DM and dst.surface == Surface.DM:
                assert src.human == dst.human
        except PrivacyBoundaryError:
            blocked += 1
            assert not can_flow(src, dst)
    assert blocked > 0 and allowed > 0
    return {"flows": 5000, "allowed": allowed, "blocked": blocked}


@scenario("self-certification: 100 disguise attempts all refused")
def s_self_cert(tmp=Path("stress/.work")):
    ground, ledger = fresh(tmp, "selfcert")
    refused = 0
    for i in range(100):
        maker = f"agent-{i}"
        for disguise in (maker, maker.upper(), f"  {maker} ", maker.title()):
            claim = CompletionClaim(maker=maker, task="t", summary="s",
                                    evidence=[Evidence(EvidenceKind.OUTPUT, "x")])
            try:
                RuleVerifier(disguise, ledger).verify(claim)
            except SelfCertificationError:
                refused += 1
    assert refused == 400, f"a disguised self-audit slipped through: {refused}/400"
    return {"disguise_attempts": 400, "refused": 400}


@scenario("sycophancy pressure: T-shaped maybes refused; hidden nos surface")
def s_sycophancy(tmp=Path("stress/.work")):
    ground, ledger = fresh(tmp, "syco")
    log = DecisionLog(ledger)
    refused = 0
    for i in range(200):
        # maybes wearing a T costume: 0-2 POVs, or no owner/revisit/missing
        n_povs = random.randint(0, 2)
        try:
            Decision(subject=f"s{i}", verdict=Verdict.T, rationale="hmm",
                     author="w", emp_lineage="EMP:x",
                     povs=[POV(f"h{j}", "pos") for j in range(n_povs)],
                     owner=random.choice([None, "alex"]),
                     revisit_at=random.choice([None, ground.now()]),
                     missing=random.choice([None, "data"]))
        except IncompleteTriangulationError:
            refused += 1
    assert refused == 200
    # real Ts age into hidden nos
    for i in range(10):
        log.record(Decision(
            subject=f"real-t-{i}", verdict=Verdict.T, rationale="r", author="w",
            emp_lineage="EMP:x",
            povs=[POV("a", "1"), POV("b", "2"), POV("c", "3")],
            owner="alex", missing="the thing",
            revisit_at=ground.now() - timedelta(days=1)))
    assert len(log.hidden_nos()) == 10
    return {"fake_Ts_refused": refused, "hidden_nos_surfaced": 10}


@scenario("witness under a garbage model: 30 cycles of fluff produce zero fake decisions")
def s_witness_garbage(tmp=Path("stress/.work")):
    ground, ledger = fresh(tmp, "garbage")
    ws = Workspace(tmp / "ws-garbage", ledger)
    emp = EMP(name="W", ends=["e"], means=["m"], principles=["p"], authored_by="alex")
    key = ConversationKey("witness:w", Surface.CHANNEL, "c", "")
    fluffs = ["Great question! Here's what I think...",
              "I'd be happy to help with that task.",
              '{"not": "an array"}', "[{\"subject\": \"x\"}]",  # missing required fields
              "As an AI, I see the dashboard clearly."]
    outcomes = {}
    for i in range(30):
        provider = MockProvider()
        provider.enqueue_text(random.choice(fluffs))
        provider.enqueue_text(random.choice(fluffs))
        w = Witness(emp, provider, ledger, ws, key, ground=ground)
        out = w.witness_cycle([Event("x", "hello", ground.now())])
        outcomes[out.value] = outcomes.get(out.value, 0) + 1
    decisions = ledger.current("decision")
    assert decisions == [], f"garbage produced {len(decisions)} fake decisions"
    assert outcomes.get("ok", 0) == 0
    return {"cycles": 30, "outcomes": outcomes, "fake_decisions_recorded": 0}


@scenario("concurrency: 8 threads x 500 appends — ledger stays readable, nothing lost")
def s_concurrency(tmp=Path("stress/.work")):
    ground, ledger = fresh(tmp, "threads")
    errors = []

    def writer(n):
        try:
            for i in range(500):
                ledger.append("fact", f"thread-{n}", {"i": i})
        except Exception as e:
            errors.append(repr(e))

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    entries = ledger.entries()  # raises LedgerIntegrityError on any torn line
    assert not errors, errors
    assert len(entries) == 4000, f"lost writes: {len(entries)}/4000"
    return {"threads": 8, "appends": 4000, "readable": True, "lost": 0}


@scenario("synthesis gate under pressure: 500 lazy writes refused, store stays sparse")
def s_synthesis_pressure(tmp=Path("stress/.work")):
    ground, ledger = fresh(tmp, "synth")
    ws = Workspace(tmp / "ws-synth", ledger)
    lazy = ["important", "for later", "context", "notes to self", "might need this",
            "todo", "memory stuff", "n/a"]
    refused = 0
    for i in range(500):
        try:
            ws.write(f"dump/{i}.md", "x" * 100, "agent", random.choice(lazy))
        except SynthesisTestError:
            refused += 1
    files = list((tmp / "ws-synth").rglob("*.md"))
    assert refused == 500 and len(files) == 0
    return {"lazy_writes_attempted": 500, "refused": 500, "files_created": 0}


# --------------------------------------------------------------------- main --

def main():
    work = Path("stress/.work")
    if work.exists():
        import shutil
        shutil.rmtree(work)
    work.mkdir(parents=True)

    for fn in [s_ledger_scale, s_session_death, s_time_attack, s_pass_fuzz,
               s_privacy_fuzz, s_self_cert, s_sycophancy, s_witness_garbage,
               s_concurrency, s_synthesis_pressure]:
        fn()

    passed = sum(1 for r in REPORT if r["attack_defeated"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# STRESS REPORT",
        "",
        f"run: {now} · python {sys.version.split()[0]} · seed 20260715 (deterministic chaos)",
        f"result: **{passed}/{len(REPORT)} attacks defeated**",
        "",
        "The suite's stance is the verifier's stance: each scenario ATTACKS one of",
        "the harness's refusals. A pass means the attack failed. Evidence below is",
        "recorded, not narrated.",
        "",
    ]
    for r in REPORT:
        lines.append(f"## {'✅' if r['attack_defeated'] else '❌'} {r['scenario']}")
        lines.append(f"took {r['seconds']}s")
        lines.append("```json")
        lines.append(json.dumps(r["evidence"], indent=2))
        lines.append("```")
        lines.append("")
    Path("STRESS-REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{passed}/{len(REPORT)} attacks defeated — report: STRESS-REPORT.md")
    sys.exit(0 if passed == len(REPORT) else 1)


if __name__ == "__main__":
    main()
