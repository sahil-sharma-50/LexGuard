"""Durable daily/competition risk counters and performance snapshots.

The readiness gate refuses to run without a hash-verified ``risk_state``
ledger artifact, and the public ``/api/performance`` projection reads a
``performance_snapshot`` artifact. This service is the only writer of both:
it derives every number from broker truth plus the previously persisted peak,
so the recorded drawdown can only ratchet with real account history.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from lexguard.adapters.alpaca_trading import (
    BROKER_ACTIVE_ORDER_STATES,
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
)

_NEW_YORK = ZoneInfo("America/New_York")


def runtime_state_hash(payload: Mapping[str, Any]) -> str:
    """Hash a runtime-state payload exactly as the readiness verifier does."""

    encoded = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class RiskStateService:
    """Refresh the persisted risk state and performance snapshot from broker truth."""

    def __init__(
        self,
        broker: Any,
        repository: Any,
        *,
        baseline_equity: Decimal = Decimal("100000"),
        environment: str = "development",
    ) -> None:
        if baseline_equity <= 0:
            raise ValueError("baseline_equity must be positive")
        self.broker = broker
        self.repository = repository
        self.baseline_equity = baseline_equity
        self.environment = environment

    async def refresh(self, now: datetime) -> dict[str, Any]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("risk state refresh time must be timezone-aware")
        account: BrokerAccount = await self.broker.get_account()
        orders: tuple[BrokerOrder, ...] = await self.broker.get_orders()
        positions: tuple[BrokerPosition, ...] = await self.broker.get_positions()
        if account.status.upper() != "ACTIVE" or not account.equity.is_finite():
            raise RuntimeError("broker account is not usable for risk state")

        previous = self._previous_state()
        peak = max(
            previous.get("competition_peak_equity", Decimal("0")),
            self.baseline_equity,
            account.equity,
        )
        if account.daily_pnl is not None:
            daily_pnl = account.daily_pnl
        elif account.last_equity is not None:
            daily_pnl = account.equity - account.last_equity
        else:
            raise RuntimeError("broker daily P&L is unavailable")
        drawdown = max(Decimal("0"), peak - account.equity)
        counter = int(previous.get("competition_counter", 0)) + 1

        trading_date = now.astimezone(_NEW_YORK).date()
        risk_payload: dict[str, Any] = {
            "daily_pnl": str(daily_pnl),
            "competition_drawdown": str(drawdown),
            "competition_peak_equity": str(peak),
            "competition_counter": counter,
            "environment": self.environment,
            "updated_at": now.isoformat(),
        }
        self.repository.save_runtime_artifact(
            trading_date,
            "risk_state",
            risk_payload,
            content_hash=runtime_state_hash(risk_payload),
            now=now,
        )
        active_order_ids = sorted(
            order.order_id
            for order in orders
            if order.status.upper() in BROKER_ACTIVE_ORDER_STATES
        )
        position_symbols = sorted(
            position.symbol for position in positions if position.quantity
        )
        performance_payload: dict[str, Any] = {
            "environment": self.environment,
            "recorded_at": now.isoformat(),
            "metrics": {
                "equity": str(account.equity),
                "daily_pnl": str(daily_pnl),
                "competition_drawdown": str(drawdown),
                "competition_peak_equity": str(peak),
                "order_ids": active_order_ids,
                "position_symbols": position_symbols,
            },
        }
        self.repository.save_runtime_artifact(
            trading_date,
            "performance_snapshot",
            performance_payload,
            now=now,
        )
        return risk_payload

    def _previous_state(self) -> dict[str, Any]:
        try:
            artifact = self.repository.latest_artifact("risk_state")
        except Exception:
            return {}
        if artifact is None:
            return {}
        payload, _, _ = artifact
        if not isinstance(payload, Mapping):
            return {}
        try:
            return {
                "competition_peak_equity": Decimal(
                    str(payload["competition_peak_equity"])
                ),
                "competition_counter": int(payload["competition_counter"]),
            }
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return {}
