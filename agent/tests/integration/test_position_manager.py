"""Frozen exit policy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from lexguard.services.position_manager import (
    HOLD,
    Close,
    PositionEvidence,
    PositionManager,
)

NY = ZoneInfo("America/New_York")


def at_et(hh: int, minute: int) -> datetime:
    return datetime(2026, 8, 24, hh, minute, tzinfo=NY).astimezone(UTC)


def evidence(
    *,
    pnl: str = "0",
    edge_valid: bool = True,
    completed: bool = True,
    risk_halt: bool = False,
    market_close: datetime | None = None,
    observed_at: datetime | None = None,
) -> PositionEvidence:
    return PositionEvidence(
        observed_at=observed_at or at_et(10, 10),
        unrealized_pnl=Decimal(pnl),
        edge_valid=edge_valid,
        evaluation_complete=completed,
        risk_halt=risk_halt,
        market_close=market_close,
    )


@pytest.mark.asyncio
async def test_invalidated_edge_requires_two_consecutive_completed_evaluations() -> None:
    manager = PositionManager(profit_target=Decimal("50"), stop_loss=Decimal("50"))

    assert await manager.evaluate(at_et(11, 0), evidence(edge_valid=False)) is HOLD
    result = await manager.evaluate(
        at_et(11, 5), evidence(edge_valid=False, observed_at=at_et(10, 15))
    )

    assert isinstance(result, Close)
    assert result.reason == "EDGE_INVALIDATED_TWICE"


@pytest.mark.asyncio
async def test_target_stop_and_risk_halt_are_frozen_exits() -> None:
    manager = PositionManager(profit_target=Decimal("50"), stop_loss=Decimal("40"))

    target = await manager.evaluate(at_et(11, 0), evidence(pnl="50"))
    assert isinstance(target, Close)
    assert target.reason == "PROFIT_TARGET"

    stop = await manager.evaluate(at_et(11, 5), evidence(pnl="-40"))
    assert isinstance(stop, Close)
    assert stop.reason == "STOP_LOSS"

    halt = await manager.evaluate(at_et(11, 10), evidence(risk_halt=True))
    assert isinstance(halt, Close)
    assert halt.reason == "RISK_HALT"


@pytest.mark.asyncio
async def test_force_close_at_1530_et_and_early_close_shift() -> None:
    manager = PositionManager(profit_target=Decimal("50"), stop_loss=Decimal("40"))

    result = await manager.evaluate(at_et(15, 30), evidence())
    assert isinstance(result, Close)
    assert result.reason == "TIME_EXIT"

    early_close = datetime(2026, 8, 24, 14, 0, tzinfo=NY)
    shifted = await manager.evaluate(at_et(13, 30), evidence(market_close=early_close))
    assert isinstance(shifted, Close)
    assert shifted.reason == "TIME_EXIT"


@pytest.mark.asyncio
async def test_incomplete_evaluation_does_not_count_as_invalidation() -> None:
    manager = PositionManager(profit_target=Decimal("50"), stop_loss=Decimal("40"))

    assert await manager.evaluate(at_et(11, 0), evidence(edge_valid=False, completed=False)) is HOLD
    assert await manager.evaluate(at_et(11, 5), evidence(edge_valid=False)) is HOLD
