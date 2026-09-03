"""The risk-state writer must satisfy the readiness verifier exactly."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from lexguard.adapters.alpaca_trading import (
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
)
from lexguard.adapters.repository import CaseRepository, CaseRow
from lexguard.api.projections import RepositoryReadStore
from lexguard.cli import _verified_risk_state
from lexguard.services.risk_state import RiskStateService

NOW = datetime(2026, 9, 1, 14, 5, tzinfo=UTC)


class FakeBroker:
    def __init__(self, equity: str, last_equity: str) -> None:
        self.equity = Decimal(equity)
        self.last_equity = Decimal(last_equity)

    async def get_account(self) -> BrokerAccount:
        return BrokerAccount(
            status="ACTIVE",
            equity=self.equity,
            last_equity=self.last_equity,
            daily_pnl=self.equity - self.last_equity,
            base_url="https://paper-api.alpaca.markets",
        )

    async def get_orders(self) -> tuple[BrokerOrder, ...]:
        return (BrokerOrder(order_id="order-9", status="new"),)

    async def get_positions(self) -> tuple[BrokerPosition, ...]:
        return (BrokerPosition(symbol="SPY260904P00640000", quantity=1, side="long"),)


def _repository() -> CaseRepository:
    repository = CaseRepository("sqlite://")
    repository.create_schema()
    return repository


@pytest.mark.asyncio
async def test_refresh_round_trips_through_readiness_verifier() -> None:
    repository = _repository()
    service = RiskStateService(FakeBroker("100250", "100000"), repository)

    await service.refresh(NOW)

    state = _verified_risk_state(repository)
    assert state is not None
    assert state["daily_pnl"] == Decimal("250")
    assert state["competition_peak_equity"] == Decimal("100250")
    assert state["competition_drawdown"] == Decimal("0")
    assert state["competition_counter"] == 1


@pytest.mark.asyncio
async def test_peak_equity_only_ratchets_and_drawdown_uses_it() -> None:
    repository = _repository()
    await RiskStateService(FakeBroker("101000", "100000"), repository).refresh(NOW)
    await RiskStateService(FakeBroker("99500", "101000"), repository).refresh(NOW)

    state = _verified_risk_state(repository)
    assert state is not None
    assert state["competition_peak_equity"] == Decimal("101000")
    assert state["competition_drawdown"] == Decimal("1500")
    assert state["competition_counter"] == 2


@pytest.mark.asyncio
async def test_refresh_records_performance_snapshot_with_broker_truth() -> None:
    repository = _repository()
    await RiskStateService(FakeBroker("100250", "100000"), repository).refresh(NOW)

    artifact = repository.latest_artifact("performance_snapshot")
    assert artifact is not None
    metrics = artifact[0]["metrics"]
    assert metrics["equity"] == "100250"
    assert metrics["order_ids"] == ["order-9"]
    assert metrics["position_symbols"] == ["SPY260904P00640000"]


@pytest.mark.asyncio
async def test_system_case_is_excluded_from_public_projections() -> None:
    repository = _repository()
    await RiskStateService(FakeBroker("100250", "100000"), repository).refresh(NOW)

    store = RepositoryReadStore(repository)
    assert store.list_cases(0, 10).items == ()
    system_case = repository.get_or_create_system_case(NOW.date())
    assert store.get_case(system_case.case_id) is None


def test_system_case_window_fits_the_persisted_column() -> None:
    decision_window = CaseRow.__table__.c.decision_window.type
    assert decision_window.length >= len("SYSTEM")
