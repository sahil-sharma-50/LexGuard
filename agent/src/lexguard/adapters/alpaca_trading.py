"""Paper-only Alpaca Trading API adapter.

This module is deliberately narrow: it can submit and manage atomic options
orders only through the paper endpoint, and it exposes normalized values to
the application services so SDK objects never cross the domain boundary.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderClass,
    OrderSide,
    OrderType,
    PositionIntent,
    QueryOrderStatus,
    TimeInForce,
)
from alpaca.trading.requests import (
    GetCalendarRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    OptionLegRequest,
    ReplaceOrderRequest,
)
from pydantic import BaseModel, ConfigDict

from lexguard.domain.models import TradeCertificate

PAPER_BASE_URL = "https://paper-api.alpaca.markets"

# Keep the broker lifecycle vocabulary in one place.  The Trading API can
# report transitional states that are neither a fill nor a terminal reject;
# treating those as active is required for safe restart reconciliation.
BROKER_ACTIVE_ORDER_STATES = frozenset(
    {
        "NEW",
        "ACCEPTED",
        "PENDING_NEW",
        "PENDING_REPLACE",
        "PARTIALLY_FILLED",
        "PARTIAL_FILLED",
        "PENDING_CANCEL",
        "SUSPENDED",
        "CALCULATED",
        "STOPPED",
        "ACCEPTED_FOR_BIDDING",
    }
)
BROKER_REPLACED_ORDER_STATES = frozenset({"REPLACED"})
BROKER_FILLED_ORDER_STATES = frozenset({"FILLED", "DONE"})
BROKER_CANCELED_ORDER_STATES = frozenset({"CANCELED", "CANCELLED", "DONE_FOR_DAY"})
BROKER_REJECTED_ORDER_STATES = frozenset({"REJECTED", "EXPIRED"})
BROKER_KNOWN_ORDER_STATES = (
    BROKER_ACTIVE_ORDER_STATES
    | BROKER_REPLACED_ORDER_STATES
    | BROKER_FILLED_ORDER_STATES
    | BROKER_CANCELED_ORDER_STATES
    | BROKER_REJECTED_ORDER_STATES
)


class PaperTradingConfigurationError(ValueError):
    """The adapter was configured for a non-paper endpoint."""


class BrokerMutationError(RuntimeError):
    """A broker mutation was rejected or raced with another state change."""


class BrokerSchemaError(RuntimeError):
    """The Trading API returned a payload outside the expected shape."""


class BrokerAmbiguousOrderError(BrokerSchemaError):
    """A deterministic client order id matched more than one order."""


class BrokerValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BrokerOrder(BrokerValue):
    order_id: str
    status: str
    filled_quantity: int = 0
    average_fill_price: Decimal | None = None
    client_order_id: str | None = None


class BrokerAccount(BrokerValue):
    status: str
    equity: Decimal
    base_url: str
    buying_power: Decimal | None = None
    last_equity: Decimal | None = None
    daily_pnl: Decimal | None = None
    competition_drawdown: Decimal | None = None
    options_level: int | None = None
    opra_available: bool = False
    # Alpaca's TradeAccount does not expose historical activity.  This field
    # is reserved for an independently verified operator artifact.
    historical_activity_verified: bool | None = None


class BrokerClock(BrokerValue):
    timestamp: Any
    is_open: bool


class BrokerPosition(BrokerValue):
    symbol: str
    quantity: int
    side: str
    unrealized_pnl: Decimal | None = None


def position_is_long(position: BrokerPosition) -> bool:
    """Interpret broker position direction without guessing from its quantity sign."""

    side = position.side.strip().lower()
    if side == "long":
        return True
    if side == "short":
        return False
    raise BrokerSchemaError(f"unsupported broker position side: {position.side}")


class BrokerCalendarSession(BrokerValue):
    trading_date: date
    open: datetime
    close: datetime


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw).lower()


def _order_status(value: Any) -> str:
    return _enum_value(value).upper()


def _decimal(value: Any, *, field: str) -> Decimal:
    if value is None:
        raise BrokerSchemaError(f"missing broker field: {field}")
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise BrokerSchemaError(f"invalid broker field: {field}") from exc


def _optional_decimal(value: Any, *, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field=field)


class PaperBroker:
    """Small async facade over the synchronous ``alpaca-py`` TradingClient."""

    def __init__(
        self,
        api_key: str | None,
        secret_key: str | None,
        *,
        base_url: str = PAPER_BASE_URL,
        client: TradingClient | Any | None = None,
        competition_baseline: Decimal | None = None,
    ) -> None:
        if base_url.rstrip("/") != PAPER_BASE_URL:
            raise PaperTradingConfigurationError(
                "paper broker requires https://paper-api.alpaca.markets"
            )
        if competition_baseline is not None and competition_baseline <= 0:
            raise PaperTradingConfigurationError("competition_baseline must be positive")
        self.base_url = PAPER_BASE_URL
        self.competition_baseline = competition_baseline
        self._client = client or TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=True,
            url_override=PAPER_BASE_URL,
        )

    @staticmethod
    def build_mleg_request(
        certificate: TradeCertificate,
        *,
        limit_price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> LimitOrderRequest:
        candidate = certificate.candidate
        legs = [
            OptionLegRequest(
                symbol=leg.symbol,
                ratio_qty=float(leg.ratio),
                side=OrderSide[leg.side],
                position_intent=(
                    PositionIntent.BUY_TO_OPEN if leg.side == "BUY" else PositionIntent.SELL_TO_OPEN
                ),
            )
            for leg in candidate.legs
        ]
        return LimitOrderRequest(
            qty=float(candidate.quantity),
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.MLEG,
            limit_price=float(limit_price if limit_price is not None else candidate.entry_limit),
            client_order_id=client_order_id,
            legs=legs,
        )

    @staticmethod
    def build_close_legs(positions: Sequence[BrokerPosition]) -> list[OptionLegRequest]:
        if not positions:
            raise ValueError("cannot close an empty position set")
        quantity = PaperBroker.close_quantity(positions)
        legs: list[OptionLegRequest] = []
        for position in positions:
            if position.quantity == 0:
                raise ValueError("cannot close a zero-quantity position")
            is_long = position_is_long(position)
            legs.append(
                OptionLegRequest(
                    symbol=position.symbol,
                    ratio_qty=float(abs(position.quantity) // quantity),
                    side=OrderSide.SELL if is_long else OrderSide.BUY,
                    position_intent=(
                        PositionIntent.SELL_TO_CLOSE if is_long else PositionIntent.BUY_TO_CLOSE
                    ),
                )
            )
        return legs

    @staticmethod
    def close_quantity(positions: Sequence[BrokerPosition]) -> int:
        """Derive the parent mleg quantity from actual broker position sizes."""

        quantities = [abs(position.quantity) for position in positions if position.quantity]
        if not quantities:
            raise ValueError("cannot close zero-quantity positions")
        return math.gcd(*quantities)

    async def submit_mleg(
        self,
        certificate: TradeCertificate,
        limit_price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> BrokerOrder:
        request = self.build_mleg_request(
            certificate, limit_price=limit_price, client_order_id=client_order_id
        )
        return await self._run_and_normalize("submit_order", request)

    async def submit_close_mleg(
        self,
        positions: Sequence[BrokerPosition],
        *,
        limit_price: Decimal,
        client_order_id: str | None = None,
    ) -> BrokerOrder:
        request = LimitOrderRequest(
            qty=float(self.close_quantity(positions)),
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.MLEG,
            limit_price=float(limit_price),
            client_order_id=client_order_id,
            legs=self.build_close_legs(positions),
        )
        return await self._run_and_normalize("submit_order", request)

    async def get_order(self, order_id: str) -> BrokerOrder:
        return await self._run_and_normalize("get_order_by_id", order_id)

    async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder:
        """Look up an order across all broker lifecycle statuses."""

        request = GetOrdersRequest(status=QueryOrderStatus.ALL)
        try:
            rows = await asyncio.to_thread(self._client.get_orders, request)
        except Exception as exc:
            raise BrokerSchemaError("get all orders failed") from exc
        matches = [
            order
            for order in (self._normalize_order(row) for row in rows)
            if order.client_order_id == client_order_id
        ]
        if len(matches) > 1:
            raise BrokerAmbiguousOrderError(
                f"multiple orders matched client id {client_order_id}"
            )
        if not matches:
            raise BrokerSchemaError("order client id was not found")
        return matches[0]

    async def replace_order(self, order_id: str, limit_price: Decimal) -> BrokerOrder:
        request = ReplaceOrderRequest(
            time_in_force=TimeInForce.DAY,
            limit_price=float(limit_price),
        )
        try:
            return await self._run_and_normalize("replace_order_by_id", order_id, request)
        except Exception as exc:
            raise BrokerMutationError(f"replace failed for {order_id}") from exc

    async def cancel_order(self, order_id: str) -> None:
        try:
            await asyncio.to_thread(self._client.cancel_order_by_id, order_id)
        except Exception as exc:
            raise BrokerMutationError(f"cancel failed for {order_id}") from exc

    async def get_orders(self) -> tuple[BrokerOrder, ...]:
        try:
            rows = await asyncio.to_thread(self._client.get_orders)
        except Exception as exc:
            raise BrokerSchemaError("get_orders failed") from exc
        return tuple(self._normalize_order(row) for row in rows)

    async def get_positions(self) -> tuple[BrokerPosition, ...]:
        try:
            rows = await asyncio.to_thread(self._client.get_all_positions)
        except Exception as exc:
            raise BrokerSchemaError("get_all_positions failed") from exc
        return tuple(self._normalize_position(row) for row in rows)

    async def get_account(self) -> BrokerAccount:
        try:
            row = await asyncio.to_thread(self._client.get_account)
        except Exception as exc:
            raise BrokerSchemaError("get_account failed") from exc
        equity = _decimal(getattr(row, "equity", None), field="equity")
        last_equity = _optional_decimal(getattr(row, "last_equity", None), field="last_equity")
        # alpaca-py's TradeAccount has no daily_pnl or competition_drawdown
        # fields; both are derived from real values so the risk gates operate
        # on broker truth instead of permanently-missing placeholders.
        reported_daily_pnl = _optional_decimal(
            getattr(row, "daily_pnl", None), field="daily_pnl"
        )
        if reported_daily_pnl is None and last_equity is not None:
            reported_daily_pnl = equity - last_equity
        reported_drawdown = _optional_decimal(
            getattr(row, "competition_drawdown", None), field="competition_drawdown"
        )
        if reported_drawdown is None and self.competition_baseline is not None:
            reported_drawdown = max(Decimal("0"), self.competition_baseline - equity)
        options_level_raw = next(
            (
                value
                for value in (
                    getattr(row, "options_trading_level", None),
                    getattr(row, "effective_options_trading_level", None),
                    getattr(row, "options_approved_level", None),
                )
                if value is not None
            ),
            None,
        )
        return BrokerAccount(
            status=_enum_value(getattr(row, "status", "")),
            equity=equity,
            base_url=self.base_url,
            buying_power=_optional_decimal(
                getattr(row, "buying_power", None), field="buying_power"
            ),
            last_equity=last_equity,
            daily_pnl=reported_daily_pnl,
            competition_drawdown=reported_drawdown,
            options_level=int(options_level_raw) if options_level_raw is not None else None,
        )

    async def get_activity_count(self) -> int:
        """Count account activities; zero proves a fresh competition account."""

        # alpaca-py 0.42.2 exposes no typed activities call on TradingClient,
        # so read the documented GET /v2/account/activities endpoint directly.
        try:
            rows = await asyncio.to_thread(
                self._client.get, "/account/activities", {"page_size": 100}
            )
        except Exception as exc:
            raise BrokerSchemaError("get account activities failed") from exc
        if not isinstance(rows, list):
            raise BrokerSchemaError("account activities payload is not a list")
        return len(rows)

    async def get_clock(self) -> BrokerClock:
        try:
            row = await asyncio.to_thread(self._client.get_clock)
        except Exception as exc:
            raise BrokerSchemaError("get_clock failed") from exc
        return BrokerClock(
            timestamp=getattr(row, "timestamp", None),
            is_open=bool(getattr(row, "is_open", False)),
        )

    async def get_calendar(self, start: date, end: date) -> tuple[BrokerCalendarSession, ...]:
        request = GetCalendarRequest(start=start, end=end)
        try:
            rows = await asyncio.to_thread(self._client.get_calendar, request)
        except Exception as exc:
            raise BrokerSchemaError("get_calendar failed") from exc
        sessions: list[BrokerCalendarSession] = []
        for row in rows:
            session_date = getattr(row, "date", None)
            opened = getattr(row, "open", None)
            closed = getattr(row, "close", None)
            if session_date is None or opened is None or closed is None:
                raise BrokerSchemaError("calendar response is missing date, open, or close")
            sessions.append(
                BrokerCalendarSession(
                    trading_date=session_date,
                    open=opened,
                    close=closed,
                )
            )
        return tuple(sessions)

    async def _run_and_normalize(self, method: str, *args: Any) -> BrokerOrder:
        try:
            row = await asyncio.to_thread(getattr(self._client, method), *args)
        except Exception as exc:
            if method == "submit_order":
                raise BrokerMutationError("submit failed") from exc
            raise BrokerSchemaError(f"{method} failed") from exc
        return self._normalize_order(row)

    @staticmethod
    def _normalize_order(row: Any) -> BrokerOrder:
        order_id = getattr(row, "id", None)
        if order_id is None:
            raise BrokerSchemaError("order response has no id")
        filled_raw = getattr(row, "filled_qty", 0) or 0
        try:
            filled_quantity = int(Decimal(str(filled_raw)))
        except Exception as exc:
            raise BrokerSchemaError("invalid filled_qty") from exc
        return BrokerOrder(
            order_id=str(order_id),
            status=_order_status(getattr(row, "status", "unknown")),
            filled_quantity=filled_quantity,
            average_fill_price=_optional_decimal(
                getattr(row, "filled_avg_price", None), field="filled_avg_price"
            ),
            client_order_id=(
                str(client_order_id)
                if (client_order_id := getattr(row, "client_order_id", None)) is not None
                else None
            ),
        )

    @staticmethod
    def _normalize_position(row: Any) -> BrokerPosition:
        symbol = getattr(row, "symbol", None)
        quantity = getattr(row, "qty", None)
        side = getattr(row, "side", None)
        if symbol is None or quantity is None or side is None:
            raise BrokerSchemaError("position response is missing symbol, qty, or side")
        try:
            quantity_int = int(Decimal(str(quantity)))
        except Exception as exc:
            raise BrokerSchemaError("invalid position qty") from exc
        return BrokerPosition(
            symbol=str(symbol),
            quantity=quantity_int,
            side=_enum_value(side),
            unrealized_pnl=_optional_decimal(
                getattr(row, "unrealized_pl", None), field="unrealized_pl"
            ),
        )
