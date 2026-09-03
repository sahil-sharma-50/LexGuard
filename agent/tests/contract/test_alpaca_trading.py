"""Offline contracts for the Alpaca paper trading adapter."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from alpaca.trading.enums import (
    OrderClass,
    OrderSide,
    PositionIntent,
    QueryOrderStatus,
    TimeInForce,
)

from lexguard.adapters.alpaca_trading import (
    BrokerAmbiguousOrderError,
    BrokerPosition,
    PaperBroker,
    PaperTradingConfigurationError,
)
from lexguard.domain.hashing import canonical_sha256
from lexguard.domain.models import CandidateStructure, OptionLeg, TradeCertificate

NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)
EXPIRATION = date(2026, 8, 25)
CASE_ID = UUID("44444444-4444-4444-4444-444444444444")


def _certificate() -> TradeCertificate:
    candidate = CandidateStructure(
        candidate_id=UUID("11111111-1111-1111-1111-111111111111"),
        strategy="LONG_VOL",
        underlying="SPY",
        expiration=EXPIRATION,
        legs=(
            OptionLeg(
                symbol="SPY260825P00575000",
                underlying="SPY",
                expiration=EXPIRATION,
                strike=Decimal("575"),
                right="P",
                side="SELL",
                ratio=1,
            ),
            OptionLeg(
                symbol="SPY260825P00580000",
                underlying="SPY",
                expiration=EXPIRATION,
                strike=Decimal("580"),
                right="P",
                side="BUY",
                ratio=1,
            ),
            OptionLeg(
                symbol="SPY260825C00590000",
                underlying="SPY",
                expiration=EXPIRATION,
                strike=Decimal("590"),
                right="C",
                side="BUY",
                ratio=1,
            ),
            OptionLeg(
                symbol="SPY260825C00595000",
                underlying="SPY",
                expiration=EXPIRATION,
                strike=Decimal("595"),
                right="C",
                side="SELL",
                ratio=1,
            ),
        ),
        quantity=2,
        entry_limit=Decimal("1.25"),
        max_loss=Decimal("375"),
        modeled_friction=Decimal("2"),
        modeled_fees=Decimal("1"),
        robust_ev=Decimal("25"),
    )
    return TradeCertificate(
        certificate_id=UUID("22222222-2222-2222-2222-222222222222"),
        case_id=CASE_ID,
        candidate=candidate,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        policy_version="risk.v1",
        proposal_hash=canonical_sha256(candidate),
        account_equity=Decimal("100000"),
        daily_pnl=Decimal("0"),
        competition_drawdown=Decimal("0"),
    )


class _TradingClientSpy:
    def __init__(self) -> None:
        self.submitted: list[object] = []
        self.replaced: list[tuple[str, object]] = []
        self.canceled: list[str] = []
        self.order_filters: list[object] = []
        self.all_orders: list[object] = []

    def submit_order(self, request: object) -> object:
        self.submitted.append(request)
        return SimpleNamespace(id="order-1", status="new", filled_qty=0, filled_avg_price=None)

    def get_order_by_id(self, order_id: str, filter: object = None) -> object:
        return SimpleNamespace(id=order_id, status="new", filled_qty=0, filled_avg_price=None)

    def get_order_by_client_id(self, client_order_id: str) -> object:
        return SimpleNamespace(
            id="close-existing",
            status="canceled",
            filled_qty=0,
            filled_avg_price=None,
            client_order_id=client_order_id,
        )

    def replace_order_by_id(self, order_id: str, request: object) -> object:
        self.replaced.append((order_id, request))
        return SimpleNamespace(id="order-2", status="new", filled_qty=0, filled_avg_price=None)

    def cancel_order_by_id(self, order_id: str) -> None:
        self.canceled.append(order_id)

    def get_all_positions(self) -> list[object]:
        return []

    def get_account(self) -> object:
        return SimpleNamespace(status="ACTIVE", equity="100000")

    def get_orders(self, filter: object = None) -> list[object]:
        if filter is not None:
            self.order_filters.append(filter)
            return self.all_orders
        return []

    def get_clock(self) -> object:
        return SimpleNamespace(timestamp=NOW, is_open=True)


def test_certificate_maps_to_one_four_leg_mleg_order() -> None:
    client = _TradingClientSpy()
    broker = PaperBroker("key", "secret", client=client)

    import asyncio

    asyncio.run(broker.submit_mleg(_certificate()))

    request = client.submitted[0]
    assert request.order_class == OrderClass.MLEG  # type: ignore[union-attr]
    assert request.time_in_force == TimeInForce.DAY  # type: ignore[union-attr]
    assert request.limit_price == 1.25  # type: ignore[union-attr]
    assert len(request.legs) == 4  # type: ignore[union-attr]
    assert request.legs[0].side == OrderSide.SELL  # type: ignore[union-attr]
    assert request.legs[0].position_intent == PositionIntent.SELL_TO_OPEN  # type: ignore[union-attr]
    assert request.legs[1].position_intent == PositionIntent.BUY_TO_OPEN  # type: ignore[union-attr]


def test_paper_broker_rejects_non_paper_endpoint() -> None:
    with pytest.raises(PaperTradingConfigurationError):
        PaperBroker("key", "secret", base_url="https://api.alpaca.markets")


def test_paper_broker_does_not_synthesize_missing_risk_values() -> None:
    import asyncio

    account = asyncio.run(PaperBroker("key", "secret", client=_TradingClientSpy()).get_account())

    assert account.last_equity is None
    assert account.daily_pnl is None
    assert account.competition_drawdown is None
    assert account.options_level is None


def test_paper_broker_normalizes_naive_calendar_times_to_new_york() -> None:
    class CalendarClient(_TradingClientSpy):
        def get_calendar(self, request: object) -> list[object]:
            return [
                SimpleNamespace(
                    date=date(2026, 8, 24),
                    open=datetime(2026, 8, 24, 9, 30),
                    close=datetime(2026, 8, 24, 16, 0),
                )
            ]

    import asyncio

    sessions = asyncio.run(
        PaperBroker("key", "secret", client=CalendarClient()).get_calendar(
            date(2026, 8, 24), date(2026, 8, 24)
        )
    )

    new_york = ZoneInfo("America/New_York")
    assert sessions[0].open == datetime(2026, 8, 24, 9, 30, tzinfo=new_york)
    assert sessions[0].close == datetime(2026, 8, 24, 16, 0, tzinfo=new_york)


def test_close_legs_invert_actual_positions() -> None:
    positions = (
        BrokerPosition(symbol="SPY260825P00580000", quantity=2, side="long"),
        BrokerPosition(symbol="SPY260825P00575000", quantity=-2, side="short"),
    )

    requests = PaperBroker.build_close_legs(positions)

    assert requests[0].side == OrderSide.SELL
    assert PaperBroker.close_quantity(positions) == 2
    assert requests[0].ratio_qty == 1
    assert requests[0].position_intent == PositionIntent.SELL_TO_CLOSE
    assert requests[1].side == OrderSide.BUY
    assert requests[1].ratio_qty == 1
    assert requests[1].position_intent == PositionIntent.BUY_TO_CLOSE


def test_close_prefers_explicit_short_side_over_positive_quantity() -> None:
    requests = PaperBroker.build_close_legs(
        (BrokerPosition(symbol="SPY260825P00580000", quantity=2, side="short"),)
    )

    assert requests[0].side == OrderSide.BUY
    assert requests[0].position_intent == PositionIntent.BUY_TO_CLOSE


def test_close_submit_passes_client_order_id_to_alpaca_request() -> None:
    import asyncio

    client = _TradingClientSpy()
    broker = PaperBroker("key", "secret", client=client)
    positions = (
        BrokerPosition(symbol="SPY260825P00580000", quantity=2, side="long"),
        BrokerPosition(symbol="SPY260825P00575000", quantity=2, side="short"),
    )

    asyncio.run(
        broker.submit_close_mleg(
            positions,
            limit_price=Decimal("1.20"),
            client_order_id="lexguard-close-test",
        )
    )

    request = client.submitted[-1]
    assert request.client_order_id == "lexguard-close-test"  # type: ignore[union-attr]


def test_client_order_lookup_uses_all_status_get_orders_request() -> None:
    import asyncio

    client = _TradingClientSpy()
    client.all_orders = [
        SimpleNamespace(
            id="historical-order",
            status="canceled",
            filled_qty=0,
            filled_avg_price=None,
            client_order_id="lexguard-client-id",
        )
    ]
    broker = PaperBroker("key", "secret", client=client)

    order = asyncio.run(broker.get_order_by_client_id("lexguard-client-id"))

    assert order.order_id == "historical-order"
    assert client.order_filters[0].status == QueryOrderStatus.ALL


def test_client_order_lookup_rejects_ambiguous_matches() -> None:
    import asyncio

    client = _TradingClientSpy()
    client.all_orders = [
        SimpleNamespace(
            id="historical-order-1",
            status="canceled",
            filled_qty=0,
            filled_avg_price=None,
            client_order_id="duplicate-client-id",
        ),
        SimpleNamespace(
            id="historical-order-2",
            status="rejected",
            filled_qty=0,
            filled_avg_price=None,
            client_order_id="duplicate-client-id",
        ),
    ]
    broker = PaperBroker("key", "secret", client=client)

    with pytest.raises(BrokerAmbiguousOrderError):
        asyncio.run(broker.get_order_by_client_id("duplicate-client-id"))
