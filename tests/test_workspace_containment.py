"""Workspace path containment (Codex High 8): the workspace is the trust boundary.

read()/write()/map() must refuse a path that resolves OUTSIDE the workspace root —
a ../ traversal or a symlink escape — so an agent can't read the user's secrets
into the prompt or write outside its sandbox."""

import os

import pytest

from trellis.memory import Workspace, WorkspaceEscapeError


def test_read_cannot_escape_with_dotdot(tmp_path, ledger):
    secret = tmp_path / "secret.md"; secret.write_text("SSN 123-45-6789")
    ws = Workspace(tmp_path / "ws", ledger)
    with pytest.raises(WorkspaceEscapeError):
        ws.read("../secret.md")


def test_write_cannot_escape_with_dotdot(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    with pytest.raises(WorkspaceEscapeError):
        ws.write("../escape.md", "x", "witness",
                 "this synthesized note exists nowhere else in the record", title="Escape")
    assert not (tmp_path / "escape.md").exists()


def test_read_cannot_follow_a_symlink_out(tmp_path, ledger):
    secret = tmp_path / "secret.md"; secret.write_text("SSN 123-45-6789")
    ws = Workspace(tmp_path / "ws", ledger)
    link = ws.root / "innocent.md"
    os.symlink(secret, link)                              # a symlink pointing outside
    with pytest.raises(WorkspaceEscapeError):
        ws.read("innocent.md")


def test_map_skips_a_symlink_that_escapes(tmp_path, ledger):
    secret = tmp_path / "secret.md"; secret.write_text("# TOP SECRET\nSSN 123-45-6789")
    ws = Workspace(tmp_path / "ws", ledger)
    ws.write("read/r.md", "# a real note\nbody", "witness",
             "the current synthesized read exists nowhere else here", title="A real note")
    os.symlink(secret, ws.root / "leak.md")              # points outside the workspace
    mapped = "\n".join(ws.map())
    assert "a real note" in mapped.lower()               # the real note is mapped
    assert "SECRET" not in mapped and "SSN" not in mapped # the escaping symlink is NOT read in


def test_normal_read_write_still_work(tmp_path, ledger):
    ws = Workspace(tmp_path / "ws", ledger)
    ws.write("reads/pricing.md", "# Pricing\nbody", "witness",
             "the synthesized pricing read exists nowhere else in this form", title="Pricing")
    assert "Pricing" in ws.read("reads/pricing.md")
