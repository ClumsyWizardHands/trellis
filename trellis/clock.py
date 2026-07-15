"""clock.py — the harness owns time, because the model cannot. (DECISIONS.md D6)

Failure record this answers:
  - "why are the three agents consistently failing at time, place, and identity
    points of facts?" — Brett, 2026-04-03
  - mint_slut stamped mint-time with a hardcoded "ET" string, so "a conversation
    from April minted today reads June 10" — loop-provenance audit, 2026-06-10
  - "we never verified whether the cron jobs were actually scheduled. They were
    not." — Sarah, 2026-07-01

Mechanisms:
  * TimeGround   — one source of truth for "now"; injectable for tests.
  * Stamp        — bitemporal pair (event_time, write_time). Never one without
                   the other.
  * Staleness    — half-life decay per volatility class; annotate() renders age
                   INTO the text the model reads, so stale data *looks* stale.
  * Schedule     — scheduled intent as verifiable state: registering a schedule
                   is a record; `verify_scheduled` answers "is it actually
                   scheduled?" instead of hoping.
  * heartbeat vs cron — two different things, kept apart on purpose:
      heartbeat = the agent's judgment pass over a small checklist, cheap context
      cron      = a detached commitment, fresh session, standalone prompt
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Optional

ISO = "%Y-%m-%dT%H:%M:%S%z"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Naive timestamps are a lie about time; refuse to guess silently.
        raise ValueError(f"naive timestamp refused (no timezone): {s!r}")
    return dt


class Staleness(str, Enum):
    FRESH = "fresh"      # freshness >= 0.5  (younger than one half-life)
    AGING = "aging"      # 0.25 <= f < 0.5
    STALE = "stale"      # 0.05 <= f < 0.25
    EXPIRED = "expired"  # f < 0.05 — do not treat as current under any framing


#: Volatility classes → half-lives. How fast does this kind of fact rot?
HALF_LIVES: dict[str, timedelta] = {
    "conversation": timedelta(days=2),     # what someone said in passing
    "position": timedelta(days=14),        # someone's stated stance (views shift)
    "commitment": timedelta(days=30),      # a promise with an owner
    "principle": timedelta(days=180),      # doctrine; slow, not immortal
    "fact": timedelta(days=90),            # default
}


@dataclass(frozen=True)
class Stamp:
    """Bitemporal stamp. event_time = when it happened; write_time = when we
    recorded it. The gap between them is itself information (late capture)."""

    event_time: datetime
    write_time: datetime

    def __post_init__(self) -> None:
        for name in ("event_time", "write_time"):
            dt = getattr(self, name)
            if dt.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")

    @property
    def capture_lag(self) -> timedelta:
        return self.write_time - self.event_time

    def to_dict(self) -> dict:
        return {"event_time": _iso(self.event_time), "write_time": _iso(self.write_time)}

    @staticmethod
    def from_dict(d: dict) -> "Stamp":
        return Stamp(parse_iso(d["event_time"]), parse_iso(d["write_time"]))


class TimeGround:
    """The single clock. Pass `now_fn` in tests to control time deterministically
    — determinism in tests is how time bugs get caught before they get lived."""

    def __init__(self, now_fn: Optional[Callable[[], datetime]] = None):
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def now(self) -> datetime:
        dt = self._now_fn()
        if dt.tzinfo is None:
            raise ValueError("TimeGround now_fn returned a naive datetime")
        return dt

    def stamp(self, event_time: Optional[datetime] = None) -> Stamp:
        """Stamp something. If event_time is omitted the event is happening now;
        if provided, we are recording the past and both truths are kept."""
        now = self.now()
        return Stamp(event_time=event_time or now, write_time=now)

    # ----- staleness -------------------------------------------------------

    def freshness(self, event_time: datetime, volatility: str = "fact") -> float:
        half_life = HALF_LIVES.get(volatility, HALF_LIVES["fact"])
        age = self.now() - event_time
        if age.total_seconds() <= 0:
            return 1.0
        return 0.5 ** (age.total_seconds() / half_life.total_seconds())

    def staleness(self, event_time: datetime, volatility: str = "fact") -> Staleness:
        f = self.freshness(event_time, volatility)
        if f >= 0.5:
            return Staleness.FRESH
        if f >= 0.25:
            return Staleness.AGING
        if f >= 0.05:
            return Staleness.STALE
        return Staleness.EXPIRED

    def age_phrase(self, event_time: datetime) -> str:
        delta = self.now() - event_time
        secs = int(delta.total_seconds())
        if secs < 0:
            return "in the future"
        if secs < 3600:
            return f"{max(secs // 60, 0)}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"

    def annotate(self, text: str, event_time: datetime, volatility: str = "fact") -> str:
        """Render age INTO what the model reads. A time-blind reader should
        still be unable to mistake April for July."""
        s = self.staleness(event_time, volatility)
        tag = f"[{s.value} · {self.age_phrase(event_time)} · {event_time.date().isoformat()}]"
        return f"{tag} {text}"

    def newest_wins(self, items: list[tuple[datetime, str]]) -> tuple[datetime, str]:
        """Given (event_time, statement) pairs about the same subject, return the
        current one. The caller should surface that older ones were superseded."""
        if not items:
            raise ValueError("newest_wins requires at least one item")
        return max(items, key=lambda pair: pair[0])


# ----- scheduling as verifiable state ---------------------------------------


class ScheduleKind(str, Enum):
    HEARTBEAT = "heartbeat"  # judgment pass: small checklist, cheap context
    CRON = "cron"            # detached commitment: fresh session, no history


@dataclass
class Schedule:
    """A scheduled intent that can be *verified*, not just hoped for.

    Registering a Schedule writes a record; every firing writes a record; and
    `verify` compares expectation against the firing log. 'The cron jobs were
    not actually scheduled' becomes an answerable question."""

    name: str
    kind: ScheduleKind
    interval: timedelta
    checklist: Optional[str] = None       # heartbeat: path to a short checklist
    prompt: Optional[str] = None          # cron: the standalone prompt
    active_hours: Optional[tuple[int, int]] = None  # e.g. (7, 22) local-quiet
    light_context: bool = True            # heartbeat cost lever (OpenClaw lesson)
    firings: list[datetime] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind == ScheduleKind.HEARTBEAT and not self.checklist:
            raise ValueError("a heartbeat needs a checklist path — a heartbeat "
                             "with nothing to check is a cost leak, not a pulse")
        if self.kind == ScheduleKind.CRON and not self.prompt:
            raise ValueError("a cron schedule needs a standalone prompt — each "
                             "firing is a fresh session with no memory of this one")

    def due(self, ground: TimeGround) -> bool:
        now = ground.now()
        if self.active_hours is not None:
            lo, hi = self.active_hours
            if not (lo <= now.hour < hi):
                return False
        if not self.firings:
            return True
        return (now - self.firings[-1]) >= self.interval

    def record_firing(self, ground: TimeGround) -> datetime:
        t = ground.now()
        self.firings.append(t)
        return t

    def verify(self, ground: TimeGround, tolerance: float = 2.0) -> dict:
        """Did this schedule actually run on cadence? Returns evidence, never a
        bare boolean — the caller can put this in front of a human."""
        now = ground.now()
        if not self.firings:
            return {"ok": False, "reason": "never fired", "expected_every": str(self.interval)}
        gap = now - self.firings[-1]
        ok = gap <= self.interval * tolerance
        return {
            "ok": ok,
            "last_fired": _iso(self.firings[-1]),
            "gap": str(gap),
            "expected_every": str(self.interval),
            "reason": "on cadence" if ok else f"silent for {gap} (> {tolerance}x interval)",
        }


HEARTBEAT_OK = "HEARTBEAT_OK"  # suppression contract: this reply means "checked, nothing needs you"
