"""isolation.py — trellis touches only its own surfaces, in a many-agent estate.

The core guarantee: on a shared, server-wide bridge that can see every agent's
channel, trellis ingests and acts on ONLY its allowlisted surfaces, stamped as
trellis — everything else is refused (act) or dropped (read)."""

from datetime import timedelta

import pytest

from trellis.ingest import DiscordMessage
from trellis.isolation import (AgentIdentity, CredentialMissing, Isolation,
                               SurfaceAllowlist, SurfaceNotAllowed,
                               ingest_scoped_discord)


TRELLIS_CH = "chan-trellis"
OTHER_CH = "chan-vex-atlas"       # a different agent's channel on the same server


def _msg(author, content, channel, ground, **kw):
    return DiscordMessage(author=author, content=content,
                          posted_at=ground.now(), channel=channel, **kw)


# ---- the allowlist gate ----------------------------------------------------

def test_empty_allowlist_touches_nothing():
    a = SurfaceAllowlist()
    assert not a.may_read("anything")
    assert not a.may_act("anything")


def test_guard_act_refuses_non_allowlisted_and_allows_allowlisted():
    a = SurfaceAllowlist(act=frozenset({TRELLIS_CH}))
    a.guard_act(TRELLIS_CH)  # no raise
    with pytest.raises(SurfaceNotAllowed, match="act refused"):
        a.guard_act(OTHER_CH)


def test_read_and_act_are_independent_sets():
    # may watch a channel it must never post into, and vice versa
    a = SurfaceAllowlist(read=frozenset({TRELLIS_CH}), act=frozenset({"chan-outbox"}))
    assert a.may_read(TRELLIS_CH) and not a.may_act(TRELLIS_CH)
    assert a.may_act("chan-outbox") and not a.may_read("chan-outbox")


def test_filter_readable_drops_other_agents_channels():
    a = SurfaceAllowlist(read=frozenset({TRELLIS_CH}))
    items = [("m1", TRELLIS_CH), ("m2", OTHER_CH), ("m3", TRELLIS_CH)]
    kept = list(a.filter_readable(items, surface_of=lambda it: it[1]))
    assert [k[0] for k in kept] == ["m1", "m3"]


def test_from_env_parses_comma_lists(monkeypatch):
    monkeypatch.setenv("TRELLIS_READ_SURFACES", " a, b ,, c ")
    monkeypatch.setenv("TRELLIS_ACT_SURFACES", "x")
    a = SurfaceAllowlist.from_env()
    assert a.read == frozenset({"a", "b", "c"})
    assert a.act == frozenset({"x"})


def test_unset_env_is_inert():
    a = SurfaceAllowlist.from_env("NOPE_READ_XYZ", "NOPE_ACT_XYZ")
    assert a.read == frozenset() and a.act == frozenset()


# ---- identity + credentials -----------------------------------------------

def test_credential_fails_loud_when_unset(monkeypatch):
    monkeypatch.delenv("TRELLIS_DISCORD_TOKEN", raising=False)
    with pytest.raises(CredentialMissing, match="will not fall back"):
        AgentIdentity().credential()


def test_credential_returns_env_value_and_never_stores_it(monkeypatch):
    monkeypatch.setenv("TRELLIS_DISCORD_TOKEN", "s3cret")
    ident = AgentIdentity()
    assert ident.credential() == "s3cret"
    # the secret is not held on the object — only the env var NAME is
    assert "s3cret" not in repr(ident)
    assert ident.token_env == "TRELLIS_DISCORD_TOKEN"


# ---- the money test: another agent's traffic cannot reach trellis's ledger --

def test_shared_bridge_batch_only_lands_trellis_own_channel(ledger, ground):
    """A mixed batch from a server-wide bridge — trellis's channel + another
    agent's channel — must land ONLY trellis's messages, stamped agent='trellis'."""
    iso = Isolation(identity=AgentIdentity(name="trellis"),
                    allow=SurfaceAllowlist(read=frozenset({TRELLIS_CH})))
    batch = [
        _msg("alex", "for trellis", TRELLIS_CH, ground),
        _msg("someone", "private vex/atlas chatter", OTHER_CH, ground),
        _msg("alex", "also for trellis", TRELLIS_CH, ground),
    ]
    landed = ingest_scoped_discord(ledger, batch, iso)

    assert len(landed) == 2                                   # only trellis's two
    bodies = [e.body["content"] for e in landed]
    assert bodies == ["for trellis", "also for trellis"]
    assert all(e.body["channel"] == TRELLIS_CH for e in landed)

    # the other agent's message is NOWHERE in the ledger
    all_content = [e.body.get("content") for e in ledger.entries()
                   if e.kind == "discord_message"]
    assert "private vex/atlas chatter" not in all_content

    # everything trellis ingested is filed under storage keys scoped to agent=trellis
    for e in landed:
        assert e.body["storage_key"].startswith("trellis__")


def test_act_gate_blocks_posting_into_another_agents_channel():
    """Even if handed another agent's channel, trellis refuses to send there."""
    iso = Isolation(allow=SurfaceAllowlist(act=frozenset({TRELLIS_CH})))
    iso.allow.guard_act(TRELLIS_CH)  # ok
    with pytest.raises(SurfaceNotAllowed):
        iso.allow.guard_act(OTHER_CH)
