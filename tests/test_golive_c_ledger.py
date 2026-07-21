"""Go-live hardening — ledger durability & anti-fork integrity (agent C).

Regression tests for the confirmed defects in trellis/ledger.py and
trellis/decisions.py that must be closed before wiring to live Discord:

  * Codex#5  — concurrent corrections / concurrent fresh decisions are a
               check-then-append TOCTOU that forks one lineage / one question
               into two live heads. The check-plus-append must be serialized
               across threads AND processes (fcntl on the file).
  * Codex#17 — a same-size in-place rewrite that PRESERVES mtime leaves the
               read cache stale; the POSIX signature must include ctime_ns.
  * FableG12 — durability posture: fsync on append; a torn (unterminated) tail
               is quarantined + re-terminated before append instead of fusing
               into the next entry and wedging every read; an out-of-band
               prefix rewrite emits a LOUD event instead of a silent rebuild;
               and a corrupt final line has a documented repair ritual.
"""

import os
import threading
import time

import pytest

from trellis.ledger import Ledger, LedgerIntegrityError
from trellis.decisions import (
    DecisionLog, Decision, Verdict, CollidingDecisionError,
)


# --------------------------------------------------------------------------
# Codex#5 — ledger correction anti-fork under real thread concurrency
# --------------------------------------------------------------------------

def test_concurrent_corrections_do_not_fork_one_lineage(tmp_path, ground):
    """Two threads both correct the same root. The check (`_superseder_of`) and
    the append must be one critical section: exactly one correction may win, the
    other must be refused, and `active()` must show ONE head — never two live
    heads superseding the same root (the confirmed fork)."""
    led = Ledger(tmp_path / "l.jsonl", ground)
    root = led.append("fact", "alice", {"v": "root"})

    # Force the two threads to overlap AT the check: hold inside the superseder
    # scan long enough that, without serialization, both read None before either
    # appends. With the fix this runs inside the exclusive lock, so the second
    # thread simply waits and then sees the first winner.
    orig = led._superseder_of

    def slow(entry_id, _orig=orig):
        r = _orig(entry_id)
        time.sleep(0.3)
        return r

    led._superseder_of = slow

    results: dict[str, object] = {}

    def worker(name):
        try:
            e = led.correct(root.id, name, {"v": name})
            results[name] = e.id
        except LedgerIntegrityError as exc:
            results[name] = exc

    ts = [threading.Thread(target=worker, args=(n,)) for n in ("t0", "t1")]
    [t.start() for t in ts]
    [t.join() for t in ts]

    heads = led.active("fact")
    assert len(heads) == 1, f"lineage forked into {len(heads)} live heads"
    # exactly one worker succeeded, the other was refused loudly
    ok = [v for v in results.values() if isinstance(v, str)]
    refused = [v for v in results.values() if isinstance(v, LedgerIntegrityError)]
    assert len(ok) == 1 and len(refused) == 1
    # and the single live head is the winner's correction, superseding root
    assert heads[0].supersedes == root.id


# --------------------------------------------------------------------------
# Codex#5 — decision question-key anti-fork under real thread concurrency
# --------------------------------------------------------------------------

def test_concurrent_fresh_decisions_do_not_fork_a_question(tmp_path, ground):
    """Two threads record a BRAND-NEW decision on the same question at once. The
    question-key collision check plus the append must be atomic across threads,
    so only one live head can answer the question; the loser gets a loud
    CollidingDecisionError, not a silent second head."""
    led = Ledger(tmp_path / "l.jsonl", ground)
    log = DecisionLog(led, ground)

    orig = log.active_head

    def slow(qk, _orig=orig):
        r = _orig(qk)
        time.sleep(0.3)
        return r

    log.active_head = slow

    def mk(author):
        return Decision(
            subject="ship the go-live wiring",
            verdict=Verdict.Y,
            rationale=f"{author} says go",
            author=author,
            emp_lineage="EMP:ends[1]",
        )

    results: dict[str, object] = {}

    def worker(name):
        try:
            e = log.record(mk(name))
            results[name] = e.id
        except CollidingDecisionError as exc:
            results[name] = exc

    ts = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    [t.start() for t in ts]
    [t.join() for t in ts]

    heads = led.active("decision")
    assert len(heads) == 1, f"question forked into {len(heads)} live heads"
    ok = [v for v in results.values() if isinstance(v, str)]
    collided = [v for v in results.values() if isinstance(v, CollidingDecisionError)]
    assert len(ok) == 1 and len(collided) == 1


# --------------------------------------------------------------------------
# Codex#17 — preserved-mtime same-size rewrite must still be detected
# --------------------------------------------------------------------------

def test_preserved_mtime_same_size_rewrite_is_detected(tmp_path, ground):
    """A same-size in-place rewrite that RESTORES the original mtime_ns (os.utime)
    is invisible to a size+inode+mtime signature — but ctime_ns still advances.
    The signature must include ctime_ns so the stale cache is caught."""
    path = tmp_path / "l.jsonl"
    led = Ledger(path, ground)
    led.append("fact", "w", {"v": "aaaa"})
    assert led.entries()[0].body["v"] == "aaaa"

    st0 = os.stat(path)
    line = path.read_bytes()
    replacement = line.replace(b"aaaa", b"bbbb")
    assert len(replacement) == len(line)
    with path.open("wb") as f:
        f.write(replacement)
    # restore the original mtime (and atime) — mtime is now UNCHANGED; only ctime
    # moved, which no caller can set.
    os.utime(path, ns=(st0.st_atime_ns, st0.st_mtime_ns))
    assert os.stat(path).st_mtime_ns == st0.st_mtime_ns

    assert led.entries()[0].body["v"] == "bbbb"  # detected via ctime, rebuilt


# --------------------------------------------------------------------------
# FableG12(a) — fsync on append
# --------------------------------------------------------------------------

def test_append_fsyncs_for_durability(tmp_path, ground, monkeypatch):
    """A power loss after a remote-accepted send must not resurrect an action as
    APPROVED. append() must fsync the file so a committed line is durable."""
    import trellis.ledger as ledmod

    calls = {"n": 0}
    real = os.fsync

    def spy(fd):
        calls["n"] += 1
        return real(fd)

    monkeypatch.setattr(ledmod.os, "fsync", spy)

    led = Ledger(tmp_path / "l.jsonl", ground)
    led.append("fact", "w", {"i": 0})
    assert calls["n"] >= 1, "append did not fsync — a committed line is not durable"


# --------------------------------------------------------------------------
# FableG12(b) — torn tail is quarantined + re-terminated, never fused
# --------------------------------------------------------------------------

def test_torn_tail_is_quarantined_before_append_not_fused(tmp_path, ground, capsys):
    """A prior torn (unterminated) write left a partial line at EOF. The next
    append must NOT concatenate onto it (which fuses a corrupt line that wedges
    every read and loses the new entry). The torn tail is quarantined, the file
    re-terminated, and the new entry lands as a clean, readable line."""
    path = tmp_path / "l.jsonl"
    led = Ledger(path, ground)
    led.append("fact", "w", {"i": 0})

    # simulate a torn write: a partial line with NO trailing newline
    with path.open("ab") as f:
        f.write(b'{"i": 1, "partial": "tor')

    # a fresh instance appends (the harness restarts and writes the next entry)
    led2 = Ledger(path, ground)
    e = led2.append("fact", "w", {"i": 2})

    got = led2.entries()
    bodies = [x.body.get("i") for x in got]
    assert 0 in bodies and 2 in bodies       # good history + new entry both readable
    assert e.body["i"] == 2
    # reads did not wedge
    assert all(isinstance(x.body, dict) for x in got)
    # the torn fragment was preserved out-of-band, not silently dropped
    q = path.with_name(path.name + ".quarantine")
    assert q.exists() and b"tor" in q.read_bytes()
    err = capsys.readouterr().err
    assert "quarantin" in err.lower()        # loud, not silent


def test_repair_tail_quarantines_a_corrupt_final_line(tmp_path, ground, capsys):
    """A complete-but-corrupt FINAL line wedges every read (kept as loud
    tamper-evidence). The documented repair ritual quarantines that final line so
    reads recover — while refusing to touch a corrupt INTERIOR line (silent
    deletion of history is the gaslight this ledger refuses)."""
    path = tmp_path / "l.jsonl"
    led = Ledger(path, ground)
    led.append("fact", "w", {"i": 0})
    good1 = path.read_bytes()

    # a complete corrupt line at the tail
    with path.open("ab") as f:
        f.write(b'{"corrupt"\n')

    with pytest.raises(LedgerIntegrityError):
        led.entries()

    quarantined = led.repair_tail("alice")
    assert quarantined is not None and "corrupt" in quarantined
    assert [x.body["i"] for x in led.entries()] == [0]   # reads recovered
    q = path.with_name(path.name + ".quarantine")
    assert q.exists()
    assert "repair_tail" in capsys.readouterr().err

    # now put a corrupt line in the MIDDLE — repair_tail must refuse it
    with path.open("ab") as f:
        f.write(b'{"corrupt2"\n')
        f.write(good1)                      # a valid line AFTER the corrupt one
    with pytest.raises(LedgerIntegrityError):
        led.repair_tail("alice")


# --------------------------------------------------------------------------
# FableG12(c) — out-of-band prefix rewrite emits a LOUD event, not a silent rebuild
# --------------------------------------------------------------------------

def test_out_of_band_prefix_rewrite_emits_a_loud_event(tmp_path, ground, capsys):
    """An out-of-band replacement whose on-disk prefix differs from what we synced
    is accepted (the file is truth) but must NOT be silent: a loud stderr event
    fires so an operator on a shared machine can see the source of truth changed
    under a live instance."""
    path = tmp_path / "l.jsonl"
    led = Ledger(path, ground)
    led.append("fact", "w", {"v": "old", "pad": "x" * 40})
    assert led.entries()[0].body["v"] == "old"
    capsys.readouterr()   # clear

    # replace the file (new inode) with DIFFERENT content of >= size
    src = tmp_path / "new.jsonl"
    other = Ledger(src, ground)
    other.append("fact", "w", {"v": "new", "pad": "y" * 40})
    os.replace(src, path)

    assert led.entries()[0].body["v"] == "new"     # rebuilt from the file
    err = capsys.readouterr().err
    assert err.strip(), "prefix rewrite rebuilt the cache SILENTLY"
    assert "prefix" in err.lower() or "rewrit" in err.lower() or "replac" in err.lower()


def test_normal_append_is_silent(tmp_path, ground, capsys):
    """The loud rebuild event must not be a false alarm: ordinary growth-only
    appends emit nothing."""
    led = Ledger(tmp_path / "l.jsonl", ground)
    led.append("fact", "w", {"i": 0})
    led.append("fact", "w", {"i": 1})
    led.entries()
    assert capsys.readouterr().err.strip() == ""
