"""Credential-gated, read-only smoke test for the local Alpaca MCP server."""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from lexguard.adapters.alpaca_mcp import AlpacaMcpGateway

_repo_root = Path(__file__).resolve().parents[3]
_enabled = (
    os.environ.get("LEXGUARD_RUN_ALPACA_SMOKE") == "1"
    and bool(os.environ.get("ALPACA_API_KEY"))
    and bool(os.environ.get("ALPACA_SECRET_KEY"))
    and os.environ.get("ALPACA_PAPER_TRADE", "true").lower() == "true"
)

pytestmark = [
    pytest.mark.alpaca_smoke,
    pytest.mark.skipif(
        not _enabled,
        reason="set LEXGUARD_RUN_ALPACA_SMOKE=1 with paper credentials to run",
    ),
]


@pytest.mark.asyncio
async def test_read_only_paper_observation_smoke() -> None:
    pytest.importorskip("fastmcp")
    sys.path.insert(0, str(_repo_root / "alpaca-mcp-server-main" / "src"))
    from alpaca_mcp_server.server import build_server  # type: ignore[import-not-found]
    from fastmcp import Client  # type: ignore[import-not-found]

    server = build_server()
    async with Client(transport=server) as client:
        gateway = AlpacaMcpGateway(
            client,
            retries=0,
            timeout_seconds=30.0,
            option_feed=os.environ.get("LEXGUARD_OPTION_FEED", "opra"),
            competition_peak_provider=lambda: Decimal("100000"),
        )
        account = await gateway.get_account_info()
        quotes = await gateway.get_option_chain("SPY", limit=10)

    assert account.status == "ACTIVE"
    assert account.equity > 0
    assert quotes
    assert all(quote.feed == gateway.option_feed for quote in quotes)
