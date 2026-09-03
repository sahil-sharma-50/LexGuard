"""Small credential-free safety drills that complement the focused service tests."""

from __future__ import annotations

from typing import cast

import pytest

from lexguard.adapters.alpaca_trading import BrokerOrder, BrokerPosition
from lexguard.services.execution import ExecutionBroker
from lexguard.services.reconciliation import ReconciliationService


class _UnknownBroker:
    base_url = "https://paper-api.alpaca.markets"

    async def get_orders(self) -> tuple[BrokerOrder, ...]:
        return (BrokerOrder(order_id="unknown", status="new"),)

    async def get_positions(self) -> tuple[BrokerPosition, ...]:
        return ()


@pytest.mark.asyncio
async def test_restart_with_unknown_working_order_requires_reconciliation() -> None:
    result = await ReconciliationService(cast(ExecutionBroker, _UnknownBroker())).reconcile()
    assert result.state == "RECONCILE_REQUIRED"
    assert result.reason_codes == ("UNKNOWN_BROKER_ORDER",)
