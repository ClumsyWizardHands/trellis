"""Pass persistence is atomic + optimistic-concurrency-checked (Codex Medium 13):
a crash mid-write can't tear the file, and two concurrent editors can't silently
clobber each other."""

import json

import pytest

from trellis.clock import TimeGround
from trellis.passes import Pass, PassExchange, PassConflictError, PassStatus


def _pass():
    return Pass(sender="peter", receiver="atlas", ask="please review the pricing draft",
                context="the CF pricing one-pager needs a second look before it goes out")


def test_save_is_atomic_no_tmp_left_behind(tmp_path):
    ex = PassExchange(tmp_path, TimeGround())
    ex.save(_pass())
    # the only file is the real pass file — no .tmp turd, no torn write
    files = sorted(p.name for p in tmp_path.glob("*"))
    assert any(f.startswith("pass-") and f.endswith(".json") for f in files)
    assert not any(f.endswith(".tmp") for f in files)


def test_version_increments_on_each_save(tmp_path):
    ex = PassExchange(tmp_path, TimeGround())
    p = _pass()
    ex.save(p); assert p.version == 1
    ex.save(p); assert p.version == 2


def test_concurrent_edit_is_detected_not_clobbered(tmp_path):
    ex = PassExchange(tmp_path, TimeGround())
    p = _pass()
    ex.save(p)                                  # version 1 on disk
    a = ex.load(p.id)                            # actor A loads v1
    b = ex.load(p.id)                            # actor B loads v1
    a.comment("atlas", "on it", ex.ground)
    ex.save(a)                                   # A saves → v2 on disk
    b.comment("peter", "any update?", ex.ground)
    with pytest.raises(PassConflictError):
        ex.save(b)                              # B's save is REFUSED (stale base), not a clobber
    # A's update survived
    assert any(c.text == "on it" for c in ex.load(p.id).comments)


def test_reload_reapply_retry_succeeds(tmp_path):
    ex = PassExchange(tmp_path, TimeGround())
    p = _pass(); ex.save(p)
    b = ex.load(p.id)
    other = ex.load(p.id); other.comment("atlas", "first", ex.ground); ex.save(other)
    b.comment("peter", "second", ex.ground)
    with pytest.raises(PassConflictError):
        ex.save(b)
    # reload, re-apply, retry — the honest optimistic-concurrency flow
    b2 = ex.load(p.id); b2.comment("peter", "second", ex.ground); ex.save(b2)
    texts = {c.text for c in ex.load(p.id).comments}
    assert "first" in texts and "second" in texts
