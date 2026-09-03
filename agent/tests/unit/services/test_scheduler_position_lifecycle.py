"""Scheduler-owned lifecycle tests for exits and dependency composition."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from lexguard.adapters.alpaca_trading import BrokerClock, BrokerOrder, BrokerPosition
from lexguard.domain.models import OptionQuote
from lexguard.services.execution import ExecutionService
from lexguard.services.position_manager import PositionEvidence, PositionManager
from lexguard.services.reconciliation import ReconciliationReport
from lexguard.services.scheduler import CalendarSession, PositionSnapshot, Scheduler

NY_OFFSET = timedelta(hours=-4)


def at_et(hour: int, minute: int) -> datetime:
    # Fixed offset is enough for this lifecycle test; scheduler converts it to New York.
    return datetime(2026, 8, 24, hour, minute, tzinfo=UTC) - NY_OFFSET


def session() -> CalendarSession:
    return CalendarSession(
        date(2026, 8, 24),
        datetime(2026, 8, 24, 9, 30, tzinfo=UTC),
        datetime(2026, 8, 24, 20, tzinfo=UTC),
    )


class Calendar:
    async def get_calendar(self, start: date, end: date) -> tuple[CalendarSession, ...]:
        return (session(),)

    async def get_clock(self) -> BrokerClock:
        return BrokerClock(timestamp=datetime.now(UTC), is_open=True)


class Reconciler:
    async def reconcile(self) -> ReconciliationReport:
        return ReconciliationReport("CONSISTENT", (), (), (), (), ())


class Lease:
    def acquire_window_lease(self, *args: object, **kwargs: object) -> bool:
        return True


class SnapshotProvider:
    def __init__(self, snapshot: PositionSnapshot) -> None:
        self.snapshot_value = snapshot
        self.calls = 0

    async def snapshot(self, now: datetime) -> PositionSnapshot:
        self.calls += 1
        return self.snapshot_value


class CloseBroker:
    base_url = "https://paper-api.alpaca.markets"

    def __init__(
        self,
        order: BrokerOrder,
        positions_after_close: tuple[BrokerPosition, ...],
    ) -> None:
        self.order = order
        self.positions_after_close = positions_after_close
        self.submits = 0

    async def submit_close_mleg(self, positions, *, limit_price):  # type: ignore[no-untyped-def]
        self.submits += 1
        return BrokerOrder(order_id="close-1", status="NEW")

    async def get_order(self, order_id: str) -> BrokerOrder:
        return self.order.model_copy(update={"order_id": order_id})

    async def get_positions(self) -> tuple[BrokerPosition, ...]:
        return self.positions_after_close


class CloseQuotes:
    async def get_option_chain(self, underlying_symbol, *, expiration_date=None, limit=100):  # type: ignore[no-untyped-def]
        now = datetime(2026, 8, 24, 19, 30, tzinfo=UTC)
        return tuple(
            OptionQuote(
                symbol=symbol,
                underlying="SPY",
                expiration=date(2026, 8, 25),
                strike={
                    "SPY260825P00575000": Decimal("575"),
                    "SPY260825P00580000": Decimal("580"),
                    "SPY260825C00590000": Decimal("590"),
                    "SPY260825C00595000": Decimal("595"),
                }[symbol],
                right="C" if "C" in symbol else "P",
                bid=Decimal("1.00"),
                ask=Decimal("1.10"),
                observed_at=now,
                feed="opra",
            )
            for symbol in (
                "SPY260825P00575000",
                "SPY260825P00580000",
                "SPY260825C00590000",
                "SPY260825C00595000",
            )
        )


def _positions() -> tuple[BrokerPosition, ...]:
    return tuple(
        BrokerPosition(symbol=symbol, quantity=1, side=side)
        for symbol, side in (
            ("SPY260825P00575000", "short"),
            ("SPY260825P00580000", "long"),
            ("SPY260825C00590000", "long"),
            ("SPY260825C00595000", "short"),
        )
    )


def _scheduler(close_broker: CloseBroker) -> tuple[Scheduler, CloseBroker]:
    now = at_et(15, 30)
    positions = _positions()
    provider = SnapshotProvider(
        PositionSnapshot(
            positions=positions,
            evidence=PositionEvidence(
                observed_at=now,
                unrealized_pnl=Decimal("0"),
                edge_valid=True,
                evaluation_complete=False,
                risk_halt=False,
            ),
        )
    )
    scheduler = Scheduler(
        calendar=Calendar(),
        reconciliation=Reconciler(),
        repository=Lease(),
        case_service=object(),  # no evaluation window is due
        entries_enabled=lambda: False,
        owner="position-lifecycle-test",
        position_manager=PositionManager(profit_target=Decimal("50"), stop_loss=Decimal("50")),
        position_snapshot_provider=provider,
        position_closer=ExecutionService(close_broker, quote_checker=CloseQuotes()),
    )
    return scheduler, close_broker


@pytest.mark.asyncio
async def test_scheduler_reports_closed_only_when_broker_order_filled_and_flat() -> None:
    broker = CloseBroker(
        BrokerOrder(order_id="close-1", status="FILLED", filled_quantity=1),
        (),
    )
    scheduler, broker = _scheduler(broker)

    result = await scheduler.tick(at_et(15, 30))

    assert result.status == "EXECUTED"
    assert result.state == "CLOSED"
    assert result.reason == "TIME_EXIT"
    assert broker.submits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("order", "positions_after_close"),
    [
        (BrokerOrder(order_id="close-1", status="NEW"), ()),
        (BrokerOrder(order_id="close-1", status="REJECTED"), ()),
        (
            BrokerOrder(order_id="close-1", status="PARTIALLY_FILLED", filled_quantity=1),
            _positions(),
        ),
        (BrokerOrder(order_id="close-1", status="FILLED", filled_quantity=1), _positions()),
    ],
)
async def test_scheduler_never_claims_closed_for_nonterminal_partial_or_nonflat_close(
    order: BrokerOrder,
    positions_after_close: tuple[BrokerPosition, ...],
) -> None:
    scheduler, broker = _scheduler(CloseBroker(order, positions_after_close))

    result = await scheduler.tick(at_et(15, 30))

    assert result.status == "HALTED"
    assert result.state != "CLOSED"
    assert result.reason in {
        "POSITION_CLOSE_RECONCILIATION_REQUIRED",
        "POSITION_CLOSE_REJECTED",
    }
    assert broker.submits == 1
