import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trellis.clock import TimeGround
from trellis.ledger import Ledger


class FakeClock:
    """Deterministic, advanceable time — time bugs get caught in tests,
    not lived in production."""

    def __init__(self, start: datetime | None = None):
        self.t = start or datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kwargs) -> datetime:
        self.t = self.t + timedelta(**kwargs)
        return self.t


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def ground(clock):
    return TimeGround(now_fn=clock)


@pytest.fixture
def ledger(tmp_path, ground):
    return Ledger(tmp_path / "ledger.jsonl", ground)
