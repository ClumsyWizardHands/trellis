"""test_p2_registry.py — the IdentityRegistry (D32, the audit's G11).

A snowflake is the identity; the display name is a mutable label. A rename can
never poison attribution: the same snowflake always resolves to the same
canonical trellis id, and two distinct humans that happen to fold to the same
name stay distinct people. Rebuildable from the ledger like every projection.
"""

from datetime import timezone

import pytest

from trellis.identity import require_identity
from trellis.registry import IdentityRegistry


def test_register_on_first_sight(ledger):
    reg = IdentityRegistry(ledger)
    cid = reg.resolve("1000000000001", "Alice")
    assert cid                       # a usable canonical id was minted
    assert cid == require_identity(cid)   # it is a valid ASCII canonical identity
    # it was recorded append-only (auto-registration)
    regs = [e for e in ledger.entries() if e.kind == IdentityRegistry.REGISTRATION_KIND]
    assert len(regs) == 1
    assert regs[0].body["discord_user_id"] == "1000000000001"
    assert regs[0].body["canonical_id"] == cid
    # attribution holds: the registry (not the human) authored the event
    assert regs[0].author == IdentityRegistry.AUTHOR
    assert reg.label(cid) == "Alice"


def test_reresolve_same_snowflake_is_stable_across_rename(ledger):
    reg = IdentityRegistry(ledger)
    cid1 = reg.resolve("42", "Bob")
    cid2 = reg.resolve("42", "Bobby McNewname")     # same person, new display name
    assert cid1 == cid2                              # identity did not move
    assert reg.label(cid1) == "Bobby McNewname"      # label followed the rename
    # the rename is an APPEND, never a rewrite (D2): the registration survives
    regs = [e for e in ledger.entries() if e.kind == IdentityRegistry.REGISTRATION_KIND]
    labels = [e for e in ledger.entries() if e.kind == IdentityRegistry.LABEL_KIND]
    assert len(regs) == 1 and len(labels) == 1


def test_two_snowflakes_same_folded_name_stay_distinct(ledger):
    reg = IdentityRegistry(ledger)
    a = reg.resolve("111", "alice")
    b = reg.resolve("222", "alice")     # a DIFFERENT human, same display name
    assert a != b                       # two humans are never merged
    assert reg.canonical_for("111") == a
    assert reg.canonical_for("222") == b


def test_canonical_for_does_not_register(ledger):
    reg = IdentityRegistry(ledger)
    assert reg.canonical_for("999") is None
    assert [e for e in ledger.entries() if e.kind == IdentityRegistry.REGISTRATION_KIND] == []
    reg.resolve("999", "Carol")
    assert reg.canonical_for("999") is not None


def test_rebuild_from_ledger_is_identical(ledger):
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "alice")
    reg.resolve("222", "alice")
    reg.resolve("333", "Dave")
    reg.resolve("111", "alice renamed")
    before = {i.discord_user_id: i.canonical_id for i in reg.all()}
    # a fresh registry over the same ledger yields the same mapping
    rebuilt = IdentityRegistry(ledger)
    after = {i.discord_user_id: i.canonical_id for i in rebuilt.all()}
    assert before == after
    assert rebuilt.label(before["111"]) == "alice renamed"


def test_nonascii_display_name_still_yields_usable_canonical(ledger):
    reg = IdentityRegistry(ledger)
    cid = reg.resolve("500", "日本語")       # non-ASCII display name must not crash
    assert cid == require_identity(cid)      # canonical id is valid ASCII
    assert reg.label(cid) == "日本語"         # the label keeps the real display name
    # a second non-ASCII name still stays distinct
    cid2 = reg.resolve("501", "日本語")
    assert cid != cid2


def test_all_reports_snowflake_canonical_label_first_seen(ledger):
    reg = IdentityRegistry(ledger)
    reg.resolve("111", "Alice")
    ids = reg.all()
    assert len(ids) == 1
    rec = ids[0]
    assert rec.discord_user_id == "111"
    assert rec.canonical_id
    assert rec.label == "Alice"
    assert rec.first_seen.tzinfo is not None      # a real, tz-aware timestamp
