"""Startup reconciliation between Alpaca state and ledger projections."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from lexguard.adapters.alpaca_trading import (
    BROKER_ACTIVE_ORDER_STATES,
    BROKER_KNOWN_ORDER_STATES,
    BrokerOrder,
    BrokerPosition,
)
from lexguard.services.execution import ExecutionBroker

_ACTIVE_ORDER_STATES = BROKER_ACTIVE_ORDER_STATES
_KNOWN_ORDER_STATES = BROKER_KNOWN_ORDER_STATES


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    state: str
    reason_codes: tuple[str, ...]
    broker_order_ids: tuple[str, ...]
    broker_position_symbols: tuple[str, ...]
    ledger_order_ids: tuple[str, ...]
    ledger_position_symbols: tuple[str, ...]


class ReconciliationService:
    """Compare broker observations with known ledger projections.

    This service is intentionally read-only. A mismatch halts acceptance of a
    scheduler lease; it never invents an entry order or an assumed position.
    """

    def __init__(
        self,
        broker: ExecutionBroker,
        *,
        ledger_order_ids: Iterable[str] = (),
        ledger_position_symbols: Iterable[str] = (),
        expected_state_provider: Callable[
            [], tuple[Iterable[str], Iterable[str] | Mapping[str, int]]
        ]
        | None = None,
    ) -> None:
        self.broker = broker
        self.ledger_order_ids = tuple(sorted(set(ledger_order_ids)))
        self.ledger_position_symbols = tuple(sorted(set(ledger_position_symbols)))
        self.expected_state_provider = expected_state_provider

    async def reconcile(self) -> ReconciliationReport:
        orders = await self.broker.get_orders()
        positions = await self.broker.get_positions()
        expected_orders = self.ledger_order_ids
        expected_positions: Iterable[str] | Mapping[str, int] = self.ledger_position_symbols
        expected_position_state: Mapping[str, int] | None = None
        if self.expected_state_provider is not None:
            try:
                provided_orders, provided_positions = self.expected_state_provider()
                expected_orders = tuple(provided_orders)
                if isinstance(provided_positions, Mapping):
                    expected_position_state = provided_positions
                    expected_positions = tuple(provided_positions)
                else:
                    expected_positions = tuple(provided_positions)
            except Exception:
                return ReconciliationReport(
                    state="RECONCILE_REQUIRED",
                    reason_codes=("LEDGER_EXPECTATION_UNAVAILABLE",),
                    broker_order_ids=tuple(
                        sorted(
                            order.order_id
                            for order in orders
                            if order.status.upper() in _ACTIVE_ORDER_STATES
                        )
                    ),
                    broker_position_symbols=tuple(
                        sorted(position.symbol for position in positions if position.quantity)
                    ),
                    ledger_order_ids=tuple(sorted(set(expected_orders))),
                    ledger_position_symbols=tuple(
                        sorted(
                            set(expected_positions)
                            if not isinstance(expected_positions, Mapping)
                            else set(expected_positions)
                        )
                    ),
                )
        return self._compare(
            orders,
            positions,
            ledger_order_ids=expected_orders,
            ledger_position_symbols=expected_positions,
            ledger_position_state=expected_position_state,
        )

    def _compare(
        self,
        orders: Iterable[BrokerOrder],
        positions: Iterable[BrokerPosition],
        *,
        ledger_order_ids: Iterable[str] | None = None,
        ledger_position_symbols: Iterable[str] | Mapping[str, int] | None = None,
        ledger_position_state: Mapping[str, int] | None = None,
    ) -> ReconciliationReport:
        order_rows = tuple(orders)
        reasons: set[str] = set()
        if any(order.status.upper() not in _KNOWN_ORDER_STATES for order in order_rows):
            reasons.add("UNKNOWN_BROKER_ORDER_STATUS")
        active_order_ids = tuple(
            sorted(
                order.order_id
                for order in order_rows
                if order.status.upper() in _ACTIVE_ORDER_STATES
            )
        )
        position_rows = tuple(positions)
        position_symbols = tuple(
            sorted(position.symbol for position in position_rows if position.quantity)
        )
        expected_orders = set(
            self.ledger_order_ids if ledger_order_ids is None else ledger_order_ids
        )
        expected_positions = set(
            self.ledger_position_symbols
            if ledger_position_symbols is None or isinstance(ledger_position_symbols, Mapping)
            else ledger_position_symbols
        )
        if ledger_position_state is None and isinstance(ledger_position_symbols, Mapping):
            ledger_position_state = ledger_position_symbols
        observed_orders = set(active_order_ids)
        observed_positions = set(position_symbols)
        if observed_orders - expected_orders:
            reasons.add("UNKNOWN_BROKER_ORDER")
        if expected_orders - observed_orders:
            reasons.add("MISSING_BROKER_ORDER")
        if observed_positions - expected_positions:
            reasons.add("UNKNOWN_BROKER_POSITION")
        if expected_positions - observed_positions:
            reasons.add("MISSING_BROKER_POSITION")
        if ledger_position_state is not None:
            observed_state: dict[str, int] = {}
            for position in position_rows:
                if not position.quantity:
                    continue
                side = position.side.strip().lower()
                if side not in {"long", "short"}:
                    reasons.add("UNKNOWN_BROKER_POSITION_SIDE")
                    continue
                observed_state[position.symbol] = abs(position.quantity) * (
                    1 if side == "long" else -1
                )
            if set(observed_state) == set(ledger_position_state):
                for symbol, expected in ledger_position_state.items():
                    actual = observed_state[symbol]
                    if abs(actual) != abs(int(expected)):
                        reasons.add("POSITION_QUANTITY_MISMATCH")
                    if (actual < 0) != (int(expected) < 0):
                        reasons.add("POSITION_SIDE_MISMATCH")
        return ReconciliationReport(
            state="CONSISTENT" if not reasons else "RECONCILE_REQUIRED",
            reason_codes=tuple(sorted(reasons)),
            broker_order_ids=active_order_ids,
            broker_position_symbols=position_symbols,
            ledger_order_ids=tuple(sorted(expected_orders)),
            ledger_position_symbols=tuple(sorted(expected_positions)),
        )
