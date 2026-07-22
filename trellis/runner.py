"""runner.py — the local always-on runner. (DECISIONS.md D37)

"trellis has a current system where it's not a server, but it's always on… as long
as my computer is on. If my computer turns off, then trellis turns off." — Alex,
2026-07-21.

Not a hosted daemon: a TICK the OS/login can drive (a launchd/login item that runs
`trellis tick`), plus an in-process loop (`trellis run`) that sleeps then ticks while
the machine is up. Everything is reconstructed from the ledger each tick, so a crash
loses nothing — the scheduler is ledger-backed (scheduler.py), the outbox is
ledger-backed (stage.py), and this runner adds two more crash-safe pieces:

  * ORPHAN SWEEP — a loop_run_start with no loop_run_end is a prior hard-kill; the
    finally block that writes the outcome never ran. At startup the runner sweeps
    those and records a PROTOCOL_VIOLATION end, so no-silent-failure covers process
    death, not just a graceful exit (loops.LoopRegistry.sweep_orphans).

  * WINDOWED LEDGER-DERIVED BUDGET — a daily spend cap summed from `charge` records
    on the ledger. Deriving it from the ledger avoids both failure modes: a
    fresh-per-tick counter has NO cap across ticks (the "$300 in two days"), and a
    shared in-memory counter never resets after a restart (permanent lockout). The
    cap is enforced PROSPECTIVELY — once the window's spend reaches it, the runner
    starts no new work until the window rolls over.

Stdlib only. The model is a seat behind a provider; this file wires none — handlers
are passed in (a MOCK in tests, the real Witness cycle in production).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from .clock import TimeGround
from .discord_api import DiscordAPIError
from .discord_gateway import ReactionOutcome
from .isolation import Isolation, ingest_scoped_discord_idempotent
from .ledger import Ledger
from .loops import LoopRegistry
from .scheduler import LedgerScheduler

CHARGE_KIND = "charge"
TICK_SKIPPED_KIND = "tick_skipped"
#: ledger kinds the Discord poll writes — the resume cursor and the per-tick summary
POLL_CURSOR_KIND = "discord_poll_cursor"
POLL_SUMMARY_KIND = "discord_poll"


def default_cadence() -> timedelta:
    """The in-process loop's sleep-then-tick interval. Configurable so a machine
    can dial cost/latency (TRELLIS_TICK_SECONDS); default 15 minutes — cheap enough
    to leave on, frequent enough to feel present."""
    raw = os.environ.get("TRELLIS_TICK_SECONDS", "").strip()
    if raw:
        try:
            secs = float(raw)
            if secs > 0:
                return timedelta(seconds=secs)
        except ValueError:
            pass
    return timedelta(minutes=15)


class DayBudget:
    """A daily spend cap DERIVED FROM THE LEDGER (D37).

    Spend is the sum of `charge` records inside the current window (a calendar day
    by default), so it (a) survives a restart — the ledger is the truth, not a
    process-local counter — and (b) RESETS when the window rolls over, so a spent
    day never becomes a permanent lockout. The cap is enforced prospectively: once
    the window's spend reaches it, no new work should start.
    """

    def __init__(self, ledger: Ledger, cap: float, ground: Optional[TimeGround] = None,
                 unit: str = "usd"):
        self.ledger = ledger
        self.cap = float(cap)
        self.ground = ground or ledger.ground
        self.unit = unit

    def window_start(self, now: Optional[datetime] = None) -> datetime:
        now = now or self.ground.now()
        tz = now.tzinfo or timezone.utc
        return datetime(now.year, now.month, now.day, tzinfo=tz)

    def spent(self, now: Optional[datetime] = None) -> float:
        now = now or self.ground.now()
        start = self.window_start(now)
        total = 0.0
        for e in self.ledger.entries():
            if e.kind != CHARGE_KIND:
                continue
            if e.stamp.event_time < start:
                continue
            try:
                total += float(e.body.get("amount", 0) or 0)
            except (TypeError, ValueError):
                continue
        return total

    def remaining(self, now: Optional[datetime] = None) -> float:
        return self.cap - self.spent(now)

    def would_block(self, now: Optional[datetime] = None, cost: float = 0.0) -> bool:
        """PROSPECTIVE gate: True when the window's spend has reached the cap (or the
        next unit of work — `cost` — would cross it). Default cost 0 means 'is there
        any headroom left this window?' — the runner refuses to start new work once
        the day's cap is spent, rather than discovering it one expensive call later."""
        return self.spent(now) + max(0.0, cost) >= self.cap

    def charge(self, amount: float, author: str, reason: str = "",
               now: Optional[datetime] = None):
        """Append a charge to the ledger — the single, restart-durable record of
        spend. Handlers (the Witness cycle, the reflection ritual) call this after
        real model work; the sum is what the cap is enforced against."""
        return self.ledger.append(
            kind=CHARGE_KIND, author=author,
            body={"amount": float(amount), "unit": self.unit, "reason": reason},
            event_time=now, tags=("budget", "charge"))


def _subscription_seat() -> bool:
    """True when the configured maker seat bills a SUBSCRIPTION, not per token:
    `codex` (ChatGPT login) always; `claude` when it runs on the Max login
    rather than an API key (ANTHROPIC_API_KEY takes precedence when set)."""
    kind = os.environ.get("TRELLIS_PROVIDER", "").strip().lower()
    if kind == "codex":
        return True
    return kind == "claude" and not os.environ.get("ANTHROPIC_API_KEY", "").strip()


def budget_from_env(ledger: Ledger, ground: Optional[TimeGround] = None
                    ) -> Optional[DayBudget]:
    """A DayBudget from TRELLIS_DAILY_BUDGET (in `unit`).

    D39 (Alex, 2026-07-22): a SUBSCRIPTION seat (codex, or claude on the Max
    login) bills nothing per call, so a dollar cap over it is a fiction — those
    seats run with NO daily budget by default. A per-token seat (an API key)
    keeps the conservative default cap, because "$300 in two days" is what
    happens when a metered personal agent runs unbounded. Explicit settings
    win either way: a number sets the cap for any seat; `off` disables it."""
    raw = os.environ.get("TRELLIS_DAILY_BUDGET", "").strip()
    if raw.lower() in ("off", "none", "unlimited"):
        return None
    cap: Optional[float] = None
    if raw:
        try:
            cap = float(raw)
        except ValueError:
            cap = None
    if cap is None:
        if _subscription_seat():
            return None                       # D39: no invented dollar ceiling
        cap = 5.0
    unit = os.environ.get("TRELLIS_BUDGET_UNIT", "usd").strip() or "usd"
    return DayBudget(ledger, cap=cap, ground=ground, unit=unit)


@dataclass(frozen=True)
class PollSurface:
    """One surface the runner polls each tick. A bare id can't tell a channel from a
    thread from a DM (D32), so the runner names it — mirroring the descriptors the
    DiscordClient's `fetch_messages` takes. Default construction from the read
    allowlist treats every id as a plain channel."""
    channel_id: str
    channel_name: str = ""
    is_thread: bool = False
    parent_channel: Optional[str] = None
    is_dm: bool = False


class DiscordPoll:
    """The tick's live-Discord step: POLL the REST API for new messages and for new
    reactions on staged proposals — the stdlib, tick-based alternative to a
    websocket gateway (D37 + D11). It NEVER decides what may be read or sent; every
    surface it touches is scoped by the D30 allowlist and every send stays behind
    the Outbox approve→fire path (D38). Concretely:

      * READ poll — for each READ-allowlisted surface, fetch messages `after` the
        cursor persisted on the ledger, run them through the IDEMPOTENT bridge
        (`ingest_scoped_discord_idempotent`) so a re-poll is a no-op, then persist
        the new cursor as a ledger event (a restart resumes; no naked now()).

      * APPROVAL poll — for each still-STAGED proposal posted to Discord, fetch the
        ✅/❌ reactions and feed the OWNER's reaction to the ApprovalGateway (which
        routes it through the hardened Outbox). A non-owner reaction, or a reaction
        already acted on, does nothing.

    Resilient by construction: a rate limit or API error on one surface is recorded
    in the summary and the poll moves on — one noisy channel never kills the tick.
    """

    def __init__(self, client, iso: Isolation, registry, ledger: Ledger,
                 ground: Optional[TimeGround] = None, gateway=None,
                 surfaces: Optional[List[PollSurface]] = None,
                 author: str = "trellis-runner", limit: int = 50,
                 ignore_bot_self: bool = True):
        self.client = client
        self.iso = iso
        self.registry = registry
        self.ledger = ledger
        self.ground = ground or ledger.ground
        self.gateway = gateway
        # default: every READ-allowlisted id, polled as a plain channel. A caller
        # that runs threads/DMs supplies richer descriptors.
        if surfaces is None:
            surfaces = [PollSurface(cid) for cid in sorted(iso.allow.read)]
        self.surfaces = list(surfaces)
        self.author = author
        self.limit = limit
        self.ignore_bot_self = ignore_bot_self
        # (message_ref, emoji, reactor) already fed this process — avoid churn.
        # The Outbox double-fire guard is the durable backstop; this only spares a
        # re-feed within a long-lived process.
        self._processed: set = set()

    # ----- read poll ---------------------------------------------------------

    def _readable(self, surf: PollSurface) -> bool:
        """A surface is polled ONLY if it is read-allowlisted — a thread via its own
        id OR its parent channel (D32). Guarantees a non-allowlisted channel is
        never even fetched, not merely dropped after the fact."""
        allow = self.iso.allow
        if surf.is_thread:
            return allow.may_read(surf.channel_id) or bool(
                surf.parent_channel and allow.may_read(surf.parent_channel))
        return allow.may_read(surf.channel_id)

    def _cursors(self) -> dict:
        """The latest persisted resume cursor per channel, folded from the ledger —
        so a fresh process picks up exactly where the last one left off."""
        cur: dict = {}
        for e in self.ledger.entries():
            if e.kind != POLL_CURSOR_KIND:
                continue
            ch = e.body.get("channel", "")
            c = e.body.get("cursor", "")
            if ch and c:
                cur[ch] = c
        return cur

    def _bot_id(self) -> str:
        if not self.ignore_bot_self:
            return ""
        try:
            return self.client.current_user_id() or ""
        except DiscordAPIError:
            return ""

    def _poll_reads(self, now: Optional[datetime], summary: dict) -> None:
        cursors = self._cursors()
        bot_id = self._bot_id()
        for surf in self.surfaces:
            if not self._readable(surf):
                continue
            cid = surf.channel_id
            cursor = cursors.get(cid)
            try:
                batch = self.client.fetch_messages(
                    cid, after=cursor, limit=self.limit,
                    channel_name=surf.channel_name, is_thread=surf.is_thread,
                    parent_channel=surf.parent_channel, is_dm=surf.is_dm)
            except DiscordAPIError as e:
                summary["errors"].append(
                    {"channel": cid, "error": str(e),
                     "retry_after": getattr(e, "retry_after", None)})
                continue
            summary["channels_polled"] += 1
            # never re-ingest the bot's own posts (it never approves or quotes itself)
            msgs = [m for m in batch.messages if not (bot_id and m.author_id == bot_id)]
            res = ingest_scoped_discord_idempotent(
                self.ledger, msgs, self.iso, self.registry)
            summary["admitted"] += res.admitted
            summary["dropped"] += res.dropped
            for k, v in res.dropped_by_surface.items():
                summary["dropped_by_surface"][k] = \
                    summary["dropped_by_surface"].get(k, 0) + v
            # persist the new cursor so a restart resumes (event_time = the tick's
            # clock, never a naked now()). An empty batch keeps the prior cursor, so
            # a quiet channel writes nothing new.
            if batch.cursor and batch.cursor != cursor:
                self.ledger.append(
                    kind=POLL_CURSOR_KIND, author=self.author,
                    body={"channel": cid, "cursor": batch.cursor},
                    event_time=now, tags=("discord", "cursor", cid))

    # ----- approval poll -----------------------------------------------------

    def _poll_approvals(self, now: Optional[datetime], summary: dict) -> None:
        gw = self.gateway
        owner = (gw.approver_discord_id or "").strip()
        if not owner:
            return
        for aid, surface, ref in gw.staged_proposal_posts():
            if not surface or not ref:
                continue
            for emoji in (gw.approve_emoji, gw.deny_emoji):
                try:
                    reactors = self.client.fetch_reactions(surface, ref, emoji)
                except DiscordAPIError as e:
                    summary["errors"].append(
                        {"action": aid, "error": str(e),
                         "retry_after": getattr(e, "retry_after", None)})
                    continue
                if owner not in reactors:
                    continue
                key = (ref, emoji, owner)
                if key in self._processed:
                    continue
                self._processed.add(key)
                res = gw.on_polled_reaction(message_ref=ref,
                                            reactor_discord_id=owner, emoji=emoji)
                summary["approvals"].append(
                    {"action": aid, "emoji": emoji, "status": res.status.value})
                # a decisive owner reaction settles the action — stop checking the
                # other emoji (an approved/denied action leaves the staged set).
                if res.status in (ReactionOutcome.APPROVED_AND_FIRED,
                                  ReactionOutcome.DENIED):
                    break

    # ----- the tick step -----------------------------------------------------

    def poll(self, now: Optional[datetime] = None) -> dict:
        """One poll pass. Records a per-tick summary (admitted/dropped/errors/
        approvals) on the ledger and returns it. Safe to call every tick: the
        cursor + bridge idempotency make a re-poll a no-op."""
        summary: dict = {"admitted": 0, "dropped": 0, "dropped_by_surface": {},
                         "channels_polled": 0, "errors": [], "approvals": []}
        self._poll_reads(now, summary)
        if self.gateway is not None:
            self._poll_approvals(now, summary)
        self.ledger.append(
            kind=POLL_SUMMARY_KIND, author=self.author,
            body={"admitted": summary["admitted"], "dropped": summary["dropped"],
                  "dropped_by_surface": summary["dropped_by_surface"],
                  "channels_polled": summary["channels_polled"],
                  "errors": summary["errors"], "approvals": summary["approvals"]},
            event_time=now, tags=("discord", "poll"))
        return summary


class Runner:
    """Constructs the ledger-backed scheduler + loop registry, registers the standing
    schedules if unregistered, and runs one pass (`tick`) or an always-on loop
    (`run`). Holds no durable state of its own — every tick reconstructs from the
    ledger, so a fresh process is indistinguishable from a resumed one."""

    #: (name, cadence, purpose). The witness cycle is the always-on read; reflection
    #: and harvest are the daily rituals. Registered on first tick if absent.
    DEFAULT_SCHEDULES: tuple = (
        ("witness.cycle", timedelta(minutes=15), "the contextual witness read pass"),
        ("witness.reflect", timedelta(hours=24), "the daily reflection ritual"),
        ("witness.harvest", timedelta(hours=24), "the daily confusion/burn harvest"),
    )

    def __init__(self, ledger: Ledger, ground: Optional[TimeGround] = None,
                 budget: Optional[DayBudget] = None, author: str = "trellis-runner",
                 discord: Optional[DiscordPoll] = None):
        self.ledger = ledger
        self.ground = ground or ledger.ground
        self.scheduler = LedgerScheduler(ledger, self.ground)
        self.registry = LoopRegistry(ledger, self.ground)
        self.budget = budget
        self.author = author
        # OPTIONAL live-Discord poll (D37/D38). Absent (every existing caller) → the
        # tick behaves exactly as before. Present → each tick also polls the
        # allowlisted surfaces for new messages and staged proposals for the owner's
        # approval reaction.
        self.discord = discord
        self._swept = False   # the orphan sweep is a startup act — once per process

    def ensure_schedules(self, specs: Optional[tuple] = None) -> None:
        specs = specs or self.DEFAULT_SCHEDULES
        registered = self.scheduler.registered()
        for name, interval, purpose in specs:
            if name not in registered:
                self.scheduler.register(name, interval, self.author, purpose=purpose)

    def sweep_orphans(self) -> list:
        return self.registry.sweep_orphans(self.author)

    def tick(self, handlers: Optional["dict[str, Callable[[], object]]"] = None,
             now: Optional[datetime] = None, specs: Optional[tuple] = None) -> dict:
        """One pass: sweep orphans (startup only), register standing schedules if
        absent, enforce the budget prospectively, then run the due schedules. Returns
        a report a runner/CLI/portal can print. Safe to call from an OS timer or the
        in-process loop; idempotent registration and cadence gating make repeated
        ticks cheap."""
        handlers = handlers or {}
        report: dict = {"swept": [], "budget_blocked": False, "fired": []}
        # STARTUP: a prior process's hard-kill is discovered here, on a fresh start.
        if not self._swept:
            report["swept"] = self.sweep_orphans()
            self._swept = True
        self.ensure_schedules(specs)
        # LIVE-DISCORD poll (guarded): ingest new allowlisted messages + route the
        # owner's approval reactions. Runs even when the budget is spent — it is
        # cheap reads and approvals (no model work), and the owner must still be able
        # to approve/deny a staged proposal on a capped day.
        if self.discord is not None:
            report["poll"] = self.discord.poll(now)
        # PROSPECTIVE budget gate: once the window's spend hits the cap, start no new
        # work (a witness cycle is a fresh session that costs money the moment it runs).
        if self.budget is not None and self.budget.would_block(now):
            report["budget_blocked"] = True
            self.ledger.append(
                kind=TICK_SKIPPED_KIND, author=self.author,
                body={"reason": "daily budget cap reached — no new work started",
                      "spent": round(self.budget.spent(now), 4), "cap": self.budget.cap,
                      "unit": self.budget.unit},
                event_time=now, tags=("runner", "budget"))
            return report
        report["fired"] = self.scheduler.run_due(handlers, self.author, now=now)
        return report

    def health(self, now: Optional[datetime] = None) -> dict:
        """What the portal/CLI surfaces so SILENCE is visible: any orphaned starts,
        and per-schedule verify (did it run on its cadence, or has it gone quiet?).
        A schedule registered-but-never-fired and a schedule silent past its cadence
        both read as `ok: False` with a reason — 'is it actually scheduled?' is a
        query, never a hope (Sarah, 2026-07-01)."""
        h: dict = {
            "orphan_starts": self.registry.orphan_starts(),
            "schedules": {name: self.scheduler.verify(name, now=now)
                          for name in self.scheduler.registered()},
            "loops": self.registry.health_report(),
        }
        if self.budget is not None:
            h["budget"] = {"spent": round(self.budget.spent(now), 4),
                           "cap": self.budget.cap, "unit": self.budget.unit,
                           "remaining": round(self.budget.remaining(now), 4)}
        return h

    def run(self, handlers: Optional["dict[str, Callable[[], object]]"] = None,
            cadence: Optional[timedelta] = None,
            stop: Optional[Callable[[], bool]] = None) -> None:  # pragma: no cover
        """The always-on loop: sleep then tick, while the machine is up. Meant to run
        under a launchd/login item — NOT a hosted daemon. Crash-safe by construction:
        each tick reconstructs state from the ledger, so a restart resumes cleanly."""
        import time
        cadence = cadence or default_cadence()
        while not (stop and stop()):
            self.tick(handlers)
            time.sleep(cadence.total_seconds())
