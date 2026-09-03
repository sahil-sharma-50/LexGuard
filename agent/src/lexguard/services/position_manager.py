"""Frozen deterministic exit rules for an open four-leg position."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from lexguard.services.scheduler import EARLY_CLOSE_BUFFER, FORCED_EXIT_TIME

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class Hold:
    reason: str = "HOLD"


HOLD = Hold()


@dataclass(frozen=True, slots=True)
class Close:
    reason: str


@dataclass(frozen=True, slots=True)
class PositionEvidence:
    observed_at: datetime
    unrealized_pnl: Decimal
    edge_valid: bool
    evaluation_complete: bool
    risk_halt: bool
    market_close: datetime | None = None


class PositionManager:
    """Apply research-frozen target, stop, invalidation, and time exit rules."""

    def __init__(
        self,
        *,
        profit_target: Decimal,
        stop_loss: Decimal,
        invalidation_count: int = 2,
        forced_exit_time: time = FORCED_EXIT_TIME,
        early_close_buffer: timedelta = EARLY_CLOSE_BUFFER,
    ) -> None:
        if profit_target <= 0 or stop_loss <= 0:
            raise ValueError("profit target and stop loss must be positive")
        if invalidation_count < 2:
            raise ValueError("invalidation_count must be at least two")
        if early_close_buffer < timedelta(0):
            raise ValueError("early_close_buffer must be non-negative")
        self.profit_target = profit_target
        self.stop_loss = stop_loss
        self.invalidation_count = invalidation_count
        self.forced_exit_time = forced_exit_time
        self.early_close_buffer = early_close_buffer
        self._invalidations = 0
        self._last_completed_observation: datetime | None = None

    async def evaluate(self, now: datetime, evidence: PositionEvidence) -> Hold | Close:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("position evaluation time must be timezone-aware")
        if evidence.observed_at.tzinfo is None or evidence.observed_at.utcoffset() is None:
            raise ValueError("position evidence time must be timezone-aware")
        local = now.astimezone(NEW_YORK)
        forced_exit = datetime.combine(local.date(), self.forced_exit_time, tzinfo=NEW_YORK)
        if evidence.market_close is not None:
            early_exit = evidence.market_close.astimezone(NEW_YORK) - self.early_close_buffer
            forced_exit = min(forced_exit, early_exit)
        if local >= forced_exit:
            return Close("TIME_EXIT")
        if evidence.risk_halt:
            return Close("RISK_HALT")
        if evidence.unrealized_pnl >= self.profit_target:
            return Close("PROFIT_TARGET")
        if evidence.unrealized_pnl <= -self.stop_loss:
            return Close("STOP_LOSS")
        if not evidence.evaluation_complete:
            return HOLD
        if (
            self._last_completed_observation is not None
            and evidence.observed_at <= self._last_completed_observation
        ):
            return HOLD
        self._last_completed_observation = evidence.observed_at
        if evidence.edge_valid:
            self._invalidations = 0
            return HOLD
        self._invalidations += 1
        if self._invalidations >= self.invalidation_count:
            return Close("EDGE_INVALIDATED_TWICE")
        return HOLD
