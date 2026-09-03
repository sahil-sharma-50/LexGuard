"""Evidence collection tests using a deterministic MCP fixture."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from lexguard.adapters.alpaca_mcp import AlpacaMcpGateway
from lexguard.domain.enums import DecisionWindow
from lexguard.services.evidence import EvidenceService, EvidenceUnavailable

OBSERVED = datetime(2026, 8, 24, 14, 5, tzinfo=UTC)
CASE_ID = UUID("11111111-1111-1111-1111-111111111111")


class StubMcp:
    def __init__(self) -> None:
        self.fault: str | None = None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.fault == "timeout":
            await asyncio.sleep(0.02)
        if self.fault == "bad_json":
            return "{not-json"
        if name == "get_clock":
            return {
                "timestamp": OBSERVED.isoformat().replace("+00:00", "Z"),
                "is_open": True,
                "next_open": "2026-08-25T13:30:00Z",
                "next_close": "2026-08-24T20:00:00Z",
            }
        if name == "get_account_info":
            return {
                "status": "ACTIVE",
                "equity": "100000",
                "buying_power": "100000",
                "daily_pnl": "0",
                "competition_drawdown": "0",
                "options_trading_level": 3,
                "opra_available": True,
            }
        if name in {"get_orders", "get_all_positions"}:
            return {"orders" if name == "get_orders" else "positions": []}
        if name == "get_stock_bars":
            return {
                "bars": {
                    "SPY": [
                        {
                            "t": "2026-08-24T14:05:00Z",
                            "o": "590.00",
                            "h": "591.00",
                            "l": "589.50",
                            "c": "590.75",
                            "v": 1000,
                        }
                    ]
                }
            }
        if name == "get_option_chain":
            if self.fault == "indicative_feed":
                return {"feed": "indicative", "snapshots": {}}
            if self.fault == "missing_quote":
                return {"feed": "opra", "snapshots": {}}
            return {
                "feed": "opra",
                "snapshots": {
                    "SPY260825P00575000": {
                        "latestQuote": {"bp": "1.00", "ap": "1.10", "t": "2026-08-24T14:05:00Z"},
                        "latestTrade": {"p": "1.05", "t": "2026-08-24T14:05:00Z"},
                        "impliedVolatility": "0.22",
                        "openInterest": 1200,
                    }
                },
            }
        if name == "get_news":
            return {
                "news": [
                    {
                        "id": 123,
                        "headline": "SPY volatility rises",
                        "created_at": "2026-08-24T14:05:00Z",
                        "url": "https://example.test/news/123",
                        "symbols": ["SPY"],
                        "source": "fixture",
                    }
                ]
            }
        raise AssertionError(f"unexpected tool {name}")


def _service(stub: StubMcp) -> EvidenceService:
    return EvidenceService(
        AlpacaMcpGateway(stub, timeout_seconds=0.001, retries=0),
        case_id=CASE_ID,
        underlying="SPY",
        base_url="https://paper-api.alpaca.markets",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["timeout", "bad_json", "missing_quote", "indicative_feed"])
async def test_evidence_fault_refuses_case(fault: str) -> None:
    stub = StubMcp()
    stub.fault = fault

    with pytest.raises(EvidenceUnavailable):
        await _service(stub).collect(DecisionWindow.MORNING, OBSERVED)


@pytest.mark.asyncio
async def test_evidence_hash_is_stable() -> None:
    first = await _service(StubMcp()).collect(DecisionWindow.MORNING, OBSERVED)
    second = await _service(StubMcp()).collect(DecisionWindow.MORNING, OBSERVED)

    assert first == second
    assert first.content_hash == second.content_hash
    assert first.source == "alpaca_mcp"
    assert first.account_snapshot.opra_available is True
    assert first.option_quotes[0].feed == "opra"
