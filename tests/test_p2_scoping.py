"""Phase-2 DM-scoping (D36): a DM's content never crosses to a channel, and — the
Lane-E residual this closes — one human's DM read never crosses into a DIFFERENT
human's DM packet. The include/exclude at compilation runs through
surfaces.can_flow with the FULL source ConversationKey, not a bare privacy rank
(rank-only saw two DMs as equal and leaked). Memory writes record their source
scope so the reader can make that decision; unscoped legacy reads fail closed.
"""

from trellis.context import ContextCompiler
from trellis.memory import Workspace
from trellis.surfaces import ConversationKey, Surface


def _write_scoped(ws, path, content, title, scope):
    ws.write(path, content, "witness:w",
             "this synthesized read exists nowhere else in this form right now",
             title=title, scope=scope)


def _block_for(ledger, ground, ws, packet_key):
    cc = ContextCompiler(ledger, ground).compile(
        subjects=["fact"], workspace=ws, packet_key=packet_key)
    return cc, cc.to_prompt_block()


def test_dm_read_is_excluded_from_a_channel_packet(ledger, ground, tmp_path):
    ws = Workspace(tmp_path / "ws", ledger, ground)
    dm = ConversationKey("witness:w", Surface.DM, "dm-alex", "alex")
    _write_scoped(ws, "read/dm.md", "# DM\nDM_ALEX_SECRET keep me private", "DM read", dm)

    channel = ConversationKey("witness:w", Surface.CHANNEL, "chiefs", "")
    cc, block = _block_for(ledger, ground, ws, channel)
    assert "DM_ALEX_SECRET" not in block
    reasons = " ".join(x["reason"] for x in cc.manifest.excluded)
    assert "withheld" in reasons or "private" in reasons


def test_dm_read_for_humanA_is_excluded_from_humanB_dm_packet(ledger, ground, tmp_path):
    """The residual: rank-only saw both DMs at rank 3 and let A's read into B's
    packet. can_flow refuses the cross-human DM path even at equal rank."""
    ws = Workspace(tmp_path / "ws", ledger, ground)
    dm_a = ConversationKey("witness:w", Surface.DM, "dm-alex", "alex")
    _write_scoped(ws, "read/dm_a.md", "# DM A\nALEX_ONLY_SECRET not for brett", "DM A read", dm_a)

    dm_b = ConversationKey("witness:w", Surface.DM, "dm-brett", "brett")
    cc, block = _block_for(ledger, ground, ws, dm_b)
    assert "ALEX_ONLY_SECRET" not in block               # never crosses to brett's DM
    reasons = " ".join(x["reason"] for x in cc.manifest.excluded)
    assert "withheld" in reasons or "private" in reasons


def test_same_scope_dm_read_is_included(ledger, ground, tmp_path):
    ws = Workspace(tmp_path / "ws", ledger, ground)
    dm_a = ConversationKey("witness:w", Surface.DM, "dm-alex", "alex")
    _write_scoped(ws, "read/dm_a.md", "# DM A\nALEX_CONTINUITY carry me forward", "DM A read", dm_a)

    # the same human's DM packet — the read is this very conversation's continuity
    same = ConversationKey("witness:w", Surface.DM, "dm-alex", "alex")
    _cc, block = _block_for(ledger, ground, ws, same)
    assert "ALEX_CONTINUITY" in block


def test_dm_read_flows_up_to_the_same_humans_channel_never(ledger, ground, tmp_path):
    """A same-human DM→channel is still a privacy DROP, not a same-human pass —
    can_flow refuses it on rank. (Guards against a naive 'same human ⇒ ok'.)"""
    ws = Workspace(tmp_path / "ws", ledger, ground)
    dm_a = ConversationKey("witness:w", Surface.DM, "dm-alex", "alex")
    _write_scoped(ws, "read/dm_a.md", "# DM A\nALEX_DM_BODY", "DM A read", dm_a)

    channel = ConversationKey("witness:w", Surface.CHANNEL, "chiefs", "alex")
    _cc, block = _block_for(ledger, ground, ws, channel)
    assert "ALEX_DM_BODY" not in block


def test_unscoped_legacy_dm_tag_fails_closed_cross_human(ledger, ground, tmp_path):
    """A legacy write with only a `surface` tag (no recorded human) must not leak
    into another human's DM packet — reconstructed with an unknown human, can_flow
    fails the cross-human DM path closed."""
    ws = Workspace(tmp_path / "ws", ledger, ground)
    (ws.root / "read").mkdir(parents=True, exist_ok=True)
    (ws.root / "read" / "legacy.md").write_text("# Legacy\nLEGACY_DM_SECRET", encoding="utf-8")
    ledger.append("memory_write", "witness:w",
                  {"path": "read/legacy.md", "title": "Legacy DM read", "surface": "dm"},
                  tags=("memory",))

    dm_b = ConversationKey("witness:w", Surface.DM, "dm-brett", "brett")
    _cc, block = _block_for(ledger, ground, ws, dm_b)
    assert "LEGACY_DM_SECRET" not in block


def test_recorded_but_unrankable_scope_fails_closed(ledger, ground, tmp_path):
    """A read that RECORDED a scope_key whose surface no longer resolves (corrupt/
    unknown) must fail CLOSED — it is a scoped read we cannot honour, not an
    untagged own-read. Conflating the two leaked a corrupt-surface DM body into a
    channel packet (the Phase-2 scoping verifier's break)."""
    ws = Workspace(tmp_path / "ws", ledger, ground)
    (ws.root / "read").mkdir(parents=True, exist_ok=True)
    (ws.root / "read" / "corrupt.md").write_text("# X\nCORRUPT_DM_SECRET", encoding="utf-8")
    ledger.append("memory_write", "witness:w",
                  {"path": "read/corrupt.md", "title": "Corrupt-scope read",
                   "scope_key": {"agent": "witness:w", "surface": "martian",
                                 "scope": "dm-alex", "human": "alex"}},
                  tags=("memory",))
    channel = ConversationKey("witness:w", Surface.CHANNEL, "chiefs", "")
    _cc, block = _block_for(ledger, ground, ws, channel)
    assert "CORRUPT_DM_SECRET" not in block


def test_untagged_own_read_still_loads(ledger, ground, tmp_path):
    """No scope + no surface tag = the agent's own working read; content loads
    (backward compatibility — the Phase-1 contract must not regress)."""
    ws = Workspace(tmp_path / "ws", ledger, ground)
    ws.write("read/own.md", "# Own\nOWN_WORKING_READ", "witness:w",
             "this synthesized working read exists nowhere else in this form",
             title="Own read")
    channel = ConversationKey("witness:w", Surface.CHANNEL, "chiefs", "")
    _cc, block = _block_for(ledger, ground, ws, channel)
    assert "OWN_WORKING_READ" in block


def test_write_records_the_source_scope_key(ledger, ground, tmp_path):
    ws = Workspace(tmp_path / "ws", ledger, ground)
    dm = ConversationKey("witness:w", Surface.DM, "dm-alex", "alex")
    _write_scoped(ws, "read/dm.md", "# DM\nbody", "DM read", dm)
    e = [x for x in ledger.active("memory_write") if x.body.get("path") == "read/dm.md"][0]
    sk = e.body.get("scope_key")
    assert sk and sk["surface"] == "dm" and sk["human"] == "alex" and sk["scope"] == "dm-alex"


def test_write_without_scope_is_backward_compatible(ledger, ground, tmp_path):
    ws = Workspace(tmp_path / "ws", ledger, ground)
    ws.write("read/plain.md", "# Plain\nbody", "witness:w",
             "this synthesized read exists nowhere else in this form", title="Plain read")
    e = [x for x in ledger.active("memory_write") if x.body.get("path") == "read/plain.md"][0]
    assert e.body.get("scope_key") is None            # optional; None for legacy callers
