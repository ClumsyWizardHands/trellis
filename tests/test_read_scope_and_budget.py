"""test_read_scope_and_budget.py — D39 + D40 (ratified by Alex, 2026-07-22).

D39: a subscription seat (codex; claude on the Max login) runs with NO daily
dollar cap — a budget over a subscription is a fiction. Per-token seats keep
the conservative default; explicit settings win either way.

D40: with a guild configured, trellis's read scope is DERIVED from what its own
bot identity can actually see in the server — every public channel plus any
private one it was invited into. A refused channel is recorded (`no_access`),
never silently retried; the discovery itself is a ledger fact; D30's Isolation
machinery is unchanged (the discovered ids BECOME the allowlist).
"""

from __future__ import annotations

from trellis.backfill import (DISCOVERY_KIND, DiscordBackfill,
                              discover_guild_read_surfaces)
from trellis.discord_api import DiscordAPIError, MessageBatch
from trellis.ledger import Ledger
from trellis.registry import IdentityRegistry
from trellis.runner import budget_from_env
from tests.test_backfill import PagingClient, _iso

GUILD = "guild-1"


# --------------------------------------------------------------------------- #
# D39 — no daily budget on subscription seats                                  #
# --------------------------------------------------------------------------- #

def _clear(monkeypatch):
    for k in ("TRELLIS_DAILY_BUDGET", "TRELLIS_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_codex_seat_runs_uncapped(monkeypatch, ledger):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "codex")
    assert budget_from_env(ledger) is None


def test_claude_max_login_runs_uncapped(monkeypatch, ledger):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "claude")
    assert budget_from_env(ledger) is None


def test_claude_with_api_key_keeps_the_default_cap(monkeypatch, ledger):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-metered")
    b = budget_from_env(ledger)
    assert b is not None and b.cap == 5.0            # per-token seats stay bounded


def test_metered_seats_keep_the_default_cap(monkeypatch, ledger):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "openai")
    b = budget_from_env(ledger)
    assert b is not None and b.cap == 5.0


def test_explicit_number_caps_any_seat(monkeypatch, ledger):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "codex")
    monkeypatch.setenv("TRELLIS_DAILY_BUDGET", "12.5")
    b = budget_from_env(ledger)
    assert b is not None and b.cap == 12.5           # the human's number wins


def test_explicit_off_disables_any_seat(monkeypatch, ledger):
    _clear(monkeypatch)
    monkeypatch.setenv("TRELLIS_PROVIDER", "openai")
    monkeypatch.setenv("TRELLIS_DAILY_BUDGET", "off")
    assert budget_from_env(ledger) is None


# --------------------------------------------------------------------------- #
# D40 — read scope derived from the server itself                              #
# --------------------------------------------------------------------------- #

class GuildClient(PagingClient):
    """A PagingClient that also lists guild channels and can refuse access."""

    def __init__(self):
        super().__init__()
        self.guild_channels: list = []
        self.forbidden: set = set()

    def list_guild_channels(self, guild_id):
        assert guild_id == GUILD
        return list(self.guild_channels)

    def fetch_messages(self, channel_id, after=None, limit=50, **kw):
        if channel_id in self.forbidden:
            self.fetched.append(channel_id)
            raise DiscordAPIError("Discord API error 403: Missing Access",
                                  status=403)
        return super().fetch_messages(channel_id, after=after, limit=limit, **kw)


def _guild_client():
    c = GuildClient()
    c.guild_channels = [
        {"id": "100", "name": "general", "type": 0},
        {"id": "200", "name": "announcements", "type": 5},
        {"id": "300", "name": "voice-lounge", "type": 2},       # not text
        {"id": "400", "name": "chiefs-private", "type": 0},      # bot not invited
    ]
    c.add_history("100", 3)
    c.add_history("200", 2)
    c.forbidden.add("400")
    return c


def test_discovery_reads_what_the_bot_can_see(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    client = _guild_client()
    res = discover_guild_read_surfaces(client, ledger, GUILD)

    assert res.read_ids == {"100", "200"}            # public + invited only
    assert [s.channel_name for s in res.surfaces] == ["general", "announcements"]
    assert res.no_access and res.no_access[0]["name"] == "chiefs-private"
    assert res.skipped_types and res.skipped_types[0]["name"] == "voice-lounge"

    # the discovery is a ledger fact — "what may I read, and why" is a query
    disc = [e for e in ledger.entries() if e.kind == DISCOVERY_KIND]
    assert disc and disc[-1].body["guild"] == GUILD
    assert {c["name"] for c in disc[-1].body["readable"]} == {"general",
                                                              "announcements"}


def test_discovered_scope_drives_backfill_and_isolation(tmp_path, ground):
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    client = _guild_client()
    res = discover_guild_read_surfaces(client, ledger, GUILD)

    from trellis.isolation import Isolation, SurfaceAllowlist
    iso = Isolation(identity=_iso().identity,
                    allow=SurfaceAllowlist(read=res.read_ids, act=frozenset()))
    bf = DiscordBackfill(client, iso, IdentityRegistry(ledger), ledger,
                         surfaces=res.surfaces)
    report = bf.run()
    assert report.all_caught_up
    contents = [e.body["content"] for e in ledger.entries()
                if e.kind == "discord_message"]
    assert len(contents) == 5                        # general(3) + announcements(2)
    # the refused channel was probed once at discovery, then left alone
    assert client.fetched.count("400") == 1


def test_cli_scope_helper_derives_iso_from_the_guild(monkeypatch, tmp_path, ground):
    from trellis.cli import _discord_read_scope
    from trellis.isolation import Isolation
    ledger = Ledger(tmp_path / "l.jsonl", ground)
    monkeypatch.setenv("TRELLIS_DISCORD_GUILD", GUILD)
    monkeypatch.delenv("TRELLIS_READ_SURFACES", raising=False)
    iso0 = Isolation.from_env()
    iso, surfaces, note = _discord_read_scope(iso0, _guild_client(), ledger)
    assert iso.allow.read == frozenset({"100", "200"})
    assert [s.channel_id for s in surfaces] == ["100", "200"]
    assert "visible to my bot identity" in note

    # an explicit list still wins (the hand-picked scope is respected)
    monkeypatch.setenv("TRELLIS_READ_SURFACES", "100")
    iso2, surfaces2, _ = _discord_read_scope(iso0, _guild_client(), ledger)
    assert surfaces2 is None and iso2 is iso0
