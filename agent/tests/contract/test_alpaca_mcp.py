"""Offline contract tests for the read-only Alpaca MCP boundary."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from lexguard.adapters.alpaca_mcp import (
    AlpacaMcpGateway,
    IndicativeFeedError,
    McpSchemaError,
)

OBSERVED = "2026-08-24T14:05:00Z"


def _responses() -> dict[str, Any]:
    return {
        "get_clock": {
            "timestamp": OBSERVED,
            "is_open": True,
            "next_open": "2026-08-25T13:30:00Z",
            "next_close": "2026-08-24T20:00:00Z",
        },
        "get_account_info": {
            "status": "ACTIVE",
            "equity": "100000",
            "buying_power": "100000",
            "daily_pnl": "0",
            "competition_drawdown": "0",
            "options_trading_level": 3,
            "opra_available": True,
        },
        "get_orders": {"orders": []},
        "get_all_positions": {"positions": []},
        "get_stock_bars": {
            "bars": {
                "SPY": [
                    {
                        "t": OBSERVED,
                        "o": "590.00",
                        "h": "591.00",
                        "l": "589.50",
                        "c": "590.75",
                        "v": 1000,
                    }
                ]
            }
        },
        "get_option_chain": {
            "feed": "opra",
            "snapshots": {
                "SPY260825P00575000": {
                    "latestQuote": {
                        "bp": "1.00",
                        "ap": "1.10",
                        "t": OBSERVED,
                    },
                    "latestTrade": {"p": "1.05", "t": OBSERVED},
                    "impliedVolatility": "0.22",
                    "openInterest": 1200,
                }
            },
        },
        "get_news": {
            "news": [
                {
                    "id": 123,
                    "headline": "SPY volatility rises",
                    "created_at": OBSERVED,
                    "url": "https://example.test/news/123",
                    "symbols": ["SPY"],
                    "source": "fixture",
                }
            ]
        },
    }


class StubMcp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = _responses()
        self.fault: str | None = None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if self.fault == "timeout":
            await asyncio.sleep(0.02)
        if self.fault == "bad_json":
            return "{not-json"
        response = self.responses[name]
        if self.fault == "indicative_feed" and name == "get_option_chain":
            response = {**response, "feed": "indicative"}
        if self.fault == "missing_quote" and name == "get_option_chain":
            response = {"feed": "opra", "snapshots": {}}
        return response


@pytest.mark.asyncio
async def test_gateway_maps_read_only_mcp_tools() -> None:
    stub = StubMcp()
    gateway = AlpacaMcpGateway(stub, timeout_seconds=0.1, retries=0)

    clock = await gateway.get_clock()
    account = await gateway.get_account_info()
    orders = await gateway.get_orders()
    positions = await gateway.get_positions()
    bars = await gateway.get_underlying_bars(
        "SPY",
        start=datetime(2026, 8, 24, 13, 0, tzinfo=UTC),
        end=datetime(2026, 8, 24, 14, 5, tzinfo=UTC),
    )
    quotes = await gateway.get_option_chain("SPY")
    news = await gateway.get_news("SPY")

    assert clock.is_open is True
    assert account.options_level == 3
    assert orders == ()
    assert positions == ()
    assert bars[0].symbol == "SPY"
    assert quotes[0].feed == "opra"
    assert news[0].evidence_id == "123"
    assert {name for name, _ in stub.calls} == {
        "get_clock",
        "get_account_info",
        "get_orders",
        "get_all_positions",
        "get_stock_bars",
        "get_option_chain",
        "get_news",
    }
    assert "place_option_order" not in gateway.READ_ONLY_TOOLS


@pytest.mark.asyncio
async def test_gateway_passes_required_provenance_and_filters() -> None:
    stub = StubMcp()
    gateway = AlpacaMcpGateway(stub, timeout_seconds=0.1, retries=0)

    await gateway.get_option_chain("SPY", expiration_date="2026-08-25", limit=25)
    await gateway.get_news("SPY", start=datetime(2026, 8, 24, 13, tzinfo=UTC), limit=10)

    chain_args = next(args for name, args in stub.calls if name == "get_option_chain")
    news_args = next(args for name, args in stub.calls if name == "get_news")
    assert chain_args == {
        "underlying_symbol": "SPY",
        "expiration_date": "2026-08-25",
        "limit": 25,
        "feed": "opra",
    }
    assert news_args["symbols"] == "SPY"
    assert news_args["limit"] == 10
    assert news_args["sort"] == "desc"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["bad_json", "missing_quote"])
async def test_gateway_rejects_invalid_market_payloads(fault: str) -> None:
    stub = StubMcp()
    stub.fault = fault
    gateway = AlpacaMcpGateway(stub, timeout_seconds=0.01, retries=0)

    with pytest.raises(McpSchemaError):
        if fault == "bad_json":
            await gateway.get_clock()
        else:
            await gateway.get_option_chain("SPY")


@pytest.mark.asyncio
async def test_gateway_rejects_indicative_option_feed() -> None:
    stub = StubMcp()
    stub.fault = "indicative_feed"
    gateway = AlpacaMcpGateway(stub, timeout_seconds=0.1, retries=0)

    with pytest.raises(IndicativeFeedError, match="configured feed"):
        await gateway.get_option_chain("SPY")


@pytest.mark.asyncio
async def test_gateway_accepts_configured_indicative_feed() -> None:
    stub = StubMcp()
    stub.fault = "indicative_feed"
    gateway = AlpacaMcpGateway(
        stub, timeout_seconds=0.1, retries=0, option_feed="indicative"
    )

    quotes = await gateway.get_option_chain("SPY")

    assert quotes
    assert all(quote.feed == "indicative" for quote in quotes)


def test_gateway_rejects_unknown_option_feed() -> None:
    with pytest.raises(ValueError, match="option_feed"):
        AlpacaMcpGateway(StubMcp(), option_feed="sip")


@pytest.mark.asyncio
async def test_gateway_retries_read_only_timeout_once() -> None:
    stub = StubMcp()
    stub.fault = "timeout"
    gateway = AlpacaMcpGateway(stub, timeout_seconds=0.001, retries=1)

    with pytest.raises(TimeoutError):
        await gateway.get_clock()
    assert len(stub.calls) == 2


def test_fixture_is_json_serializable() -> None:
    assert json.dumps(_responses())
