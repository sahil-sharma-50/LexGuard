"""Typed, read-only boundary for the Alpaca Trading MCP server."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast
from uuid import uuid4

from lexguard.domain.models import (
    AllowedUnderlying,
    NewsEvidence,
    OptionFeed,
    OptionQuote,
    OptionRight,
    UnderlyingBar,
)

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
OPTION_FEEDS: tuple[str, ...] = ("opra", "indicative")
_OPTION_SYMBOL = re.compile(
    r"^(?P<underlying>[A-Z]{1,6})(?P<expiration>\d{6})(?P<right>[CP])(?P<strike>\d{8})$"
)


class McpClient(Protocol):
    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call one MCP tool and return its raw result."""


class FastMcpHttpClient:
    """Create one short-lived FastMCP HTTP session per read-only call.

    The service deliberately keeps this transport behind :class:`McpClient` so
    tests can inject a deterministic client and never open a network connection.
    A short-lived session also avoids carrying a stale MCP session across a
    scheduler restart.
    """

    def __init__(self, url: str) -> None:
        if not url.startswith(("https://", "http://")):
            raise ValueError("MCP endpoint must be an HTTP(S) URL")
        try:
            from fastmcp.client import Client
            from fastmcp.client.transports import StreamableHttpTransport
        except ImportError as exc:  # pragma: no cover - exercised by deployment preflight
            raise McpGatewayError("fastmcp is required for the configured MCP endpoint") from exc
        self.url = url
        self._client_type = Client
        self._transport_type = StreamableHttpTransport

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        transport = self._transport_type(url=self.url)
        async with self._client_type(transport) as client:
            return await client.call_tool(name, dict(arguments))


class McpGatewayError(RuntimeError):
    """Base error for transport or provider failures."""


class McpSchemaError(McpGatewayError):
    """The provider returned a payload outside the documented shape."""


class IndicativeFeedError(McpSchemaError):
    """The option payload's feed provenance differs from the configured feed."""


@dataclass(frozen=True, slots=True)
class ClockObservation:
    timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime


@dataclass(frozen=True, slots=True)
class AccountObservation:
    observed_at: datetime
    status: str
    equity: Decimal
    buying_power: Decimal
    daily_pnl: Decimal
    competition_drawdown: Decimal
    options_level: int
    opra_available: bool
    open_structure_count: int


@dataclass(frozen=True, slots=True)
class OrderObservation:
    order_id: str
    status: str
    symbol: str | None


@dataclass(frozen=True, slots=True)
class PositionObservation:
    symbol: str
    quantity: Decimal


class AlpacaMcpGateway:
    """Expose only read-only Alpaca MCP calls for evidence collection."""

    READ_ONLY_TOOLS = frozenset(
        {
            "get_clock",
            "get_account_info",
            "get_orders",
            "get_all_positions",
            "get_stock_bars",
            "get_option_chain",
            "get_news",
        }
    )

    def __init__(
        self,
        client: McpClient,
        *,
        base_url: str = PAPER_BASE_URL,
        timeout_seconds: float = 5.0,
        retries: int = 1,
        option_feed: str = "opra",
        competition_peak_provider: Callable[[], Decimal | None] | None = None,
    ) -> None:
        if base_url.rstrip("/") != PAPER_BASE_URL:
            raise ValueError("Alpaca MCP gateway requires the paper API endpoint")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if retries < 0:
            raise ValueError("retries must be non-negative")
        if option_feed not in OPTION_FEEDS:
            raise ValueError("option_feed must be one of: " + ", ".join(OPTION_FEEDS))
        self._client = client
        self.base_url = PAPER_BASE_URL
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.option_feed = cast(OptionFeed, option_feed)
        self._competition_peak_provider = competition_peak_provider

    async def get_clock(self) -> ClockObservation:
        payload = _as_mapping(await self._call("get_clock", {}), "clock")
        return ClockObservation(
            timestamp=_datetime(_required(payload, "timestamp")),
            is_open=_bool(_required(payload, "is_open", "isOpen")),
            next_open=_datetime(_required(payload, "next_open", "nextOpen")),
            next_close=_datetime(_required(payload, "next_close", "nextClose")),
        )

    async def get_account_info(self) -> AccountObservation:
        payload = _as_mapping(await self._call("get_account_info", {}), "account")
        observed_at = _datetime(
            payload.get("observed_at") or payload.get("updated_at") or datetime.now().astimezone()
        )
        options_level = payload.get("options_trading_level", payload.get("options_level"))
        if options_level is None:
            options_level = payload.get("options_approved_level", 0)
        equity = _decimal(_required(payload, "equity"))
        # The real /v2/account payload carries equity and last_equity but no
        # explicit daily P&L; derive it rather than requiring an invented key.
        daily_raw = payload.get("daily_pnl", payload.get("pnl"))
        if daily_raw is not None:
            daily_pnl = _decimal(daily_raw)
        else:
            daily_pnl = equity - _decimal(_required(payload, "last_equity"))
        # Competition drawdown is a durable ledger fact (persisted peak equity),
        # never a broker field. An explicit payload value still wins for tests.
        drawdown_raw = payload.get("competition_drawdown")
        if drawdown_raw is not None:
            competition_drawdown = _decimal(drawdown_raw)
        else:
            peak = (
                self._competition_peak_provider()
                if self._competition_peak_provider is not None
                else None
            )
            if peak is None:
                raise McpSchemaError("competition peak equity is unavailable")
            competition_drawdown = max(Decimal("0"), peak - equity)
        # Feed availability is proven per option-chain call, where provenance is
        # enforced; at the account boundary it reflects that enforcement being
        # configured, unless the payload states otherwise.
        opra_raw = payload.get("opra_available")
        return AccountObservation(
            observed_at=observed_at,
            status=str(payload.get("status", "UNKNOWN")).upper(),
            equity=equity,
            buying_power=_decimal(_required(payload, "buying_power")),
            daily_pnl=daily_pnl,
            competition_drawdown=competition_drawdown,
            options_level=int(options_level),
            opra_available=_bool(opra_raw) if opra_raw is not None else True,
            open_structure_count=int(payload.get("open_structure_count", 0)),
        )

    async def get_orders(
        self, *, status: str = "open", limit: int = 100
    ) -> tuple[OrderObservation, ...]:
        payload = await self._call("get_orders", {"status": status, "limit": limit})
        rows = _sequence(payload, "orders", "result")
        return tuple(
            OrderObservation(
                order_id=str(row.get("id", row.get("order_id", ""))),
                status=str(row.get("status", "unknown")).lower(),
                symbol=_optional_str(row.get("symbol")),
            )
            for row in rows
            if isinstance(row, Mapping)
        )

    async def get_positions(self) -> tuple[PositionObservation, ...]:
        payload = await self._call("get_all_positions", {})
        rows = _sequence(payload, "positions", "result")
        return tuple(
            PositionObservation(
                symbol=str(_required(row, "symbol")),
                quantity=_decimal(row.get("qty", row.get("quantity", "0"))),
            )
            for row in rows
            if isinstance(row, Mapping)
        )

    async def get_underlying_bars(
        self,
        symbol: AllowedUnderlying,
        *,
        start: datetime,
        end: datetime,
        limit: int = 1000,
    ) -> tuple[UnderlyingBar, ...]:
        payload = await self._call(
            "get_stock_bars",
            {
                "symbols": symbol,
                "timeframe": "5Min",
                "start": _format_datetime(start),
                "end": _format_datetime(end),
                "limit": limit,
                "feed": "iex",
                "adjustment": "raw",
                "sort": "asc",
            },
        )
        bars_payload = _as_mapping(payload, "bars")
        rows = bars_payload.get(symbol, bars_payload.get(symbol.upper()))
        if not isinstance(rows, Sequence) or isinstance(rows, str | bytes) or not rows:
            raise McpSchemaError("stock bars missing for underlying")
        return tuple(
            UnderlyingBar(
                symbol=symbol,
                timestamp=_datetime(_required(row, "t", "timestamp")),
                open=_decimal(_required(row, "o", "open")),
                high=_decimal(_required(row, "h", "high")),
                low=_decimal(_required(row, "l", "low")),
                close=_decimal(_required(row, "c", "close")),
                volume=int(_required(row, "v", "volume")),
            )
            for row in rows
            if isinstance(row, Mapping)
        )

    async def get_option_chain(
        self,
        underlying_symbol: AllowedUnderlying,
        *,
        expiration_date: date | str | None = None,
        strike_price_gte: Decimal | None = None,
        strike_price_lte: Decimal | None = None,
        limit: int = 100,
    ) -> tuple[OptionQuote, ...]:
        arguments: dict[str, Any] = {
            "underlying_symbol": underlying_symbol,
            "limit": limit,
            "feed": self.option_feed,
        }
        if expiration_date is not None:
            arguments["expiration_date"] = (
                expiration_date.isoformat()
                if isinstance(expiration_date, date)
                else expiration_date
            )
        if strike_price_gte is not None:
            arguments["strike_price_gte"] = float(strike_price_gte)
        if strike_price_lte is not None:
            arguments["strike_price_lte"] = float(strike_price_lte)
        payload = _as_mapping(await self._call("get_option_chain", arguments), "option chain")
        # The market-data response schema does not echo the requested feed. The
        # explicit feed request is therefore part of the provenance; an explicit
        # mismatching response still wins and is rejected below.
        feed = str(payload.get("feed", payload.get("source", self.option_feed))).lower()
        if feed != self.option_feed:
            raise IndicativeFeedError("option chain feed differs from the configured feed")
        snapshots = payload.get("snapshots")
        if not isinstance(snapshots, Mapping) or not snapshots:
            raise McpSchemaError("option chain contains no snapshots")

        quotes: list[OptionQuote] = []
        for symbol, snapshot in snapshots.items():
            if not isinstance(snapshot, Mapping):
                raise McpSchemaError("option snapshot is not an object")
            match = _OPTION_SYMBOL.fullmatch(str(symbol))
            if match is None:
                raise McpSchemaError("option chain contains an invalid OCC symbol")
            quote = snapshot.get("latestQuote", snapshot.get("latest_quote"))
            if not isinstance(quote, Mapping):
                raise McpSchemaError("option snapshot is missing its quote")
            bid = quote.get("bp", quote.get("bid_price", quote.get("bid")))
            ask = quote.get("ap", quote.get("ask_price", quote.get("ask")))
            if bid is None or ask is None:
                raise McpSchemaError("option quote is missing bid or ask")
            trade = snapshot.get("latestTrade", snapshot.get("latest_trade", {}))
            if not isinstance(trade, Mapping):
                trade = {}
            observed_at = quote.get("t") or trade.get("t") or snapshot.get("observed_at")
            if observed_at is None:
                raise McpSchemaError("option quote is missing its timestamp")
            quote_feed = str(snapshot.get("feed", feed)).lower()
            if quote_feed != self.option_feed:
                raise IndicativeFeedError("option quote feed differs from the configured feed")
            open_interest_raw = snapshot.get("openInterest", snapshot.get("open_interest"))
            quotes.append(
                OptionQuote(
                    symbol=str(symbol),
                    underlying=cast(AllowedUnderlying, match.group("underlying")),
                    expiration=datetime.strptime(match.group("expiration"), "%y%m%d").date(),
                    strike=Decimal(match.group("strike")) / Decimal("1000"),
                    right=cast(OptionRight, match.group("right")),
                    bid=_decimal(bid),
                    ask=_decimal(ask),
                    last=_decimal(trade["p"]) if trade.get("p") is not None else None,
                    open_interest=(
                        int(open_interest_raw) if open_interest_raw is not None else None
                    ),
                    implied_volatility=(
                        _decimal(snapshot["impliedVolatility"])
                        if snapshot.get("impliedVolatility") is not None
                        else None
                    ),
                    observed_at=_datetime(observed_at),
                    feed=self.option_feed,
                )
            )
        return tuple(quotes)

    async def get_news(
        self,
        symbols: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
    ) -> tuple[NewsEvidence, ...]:
        arguments: dict[str, Any] = {"symbols": symbols, "sort": "desc", "limit": limit}
        if start is not None:
            arguments["start"] = _format_datetime(start)
        if end is not None:
            arguments["end"] = _format_datetime(end)
        payload = await self._call("get_news", arguments)
        rows = _sequence(payload, "news", "articles")
        return tuple(
            NewsEvidence(
                evidence_id=str(_required(row, "id", "evidence_id")),
                headline=str(_required(row, "headline")),
                published_at=_datetime(_required(row, "created_at", "published_at")),
                source=str(row.get("source", "alpaca")),
                url=_optional_str(row.get("url")),
            )
            for row in rows
            if isinstance(row, Mapping)
        )

    async def _call(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        if tool_name not in self.READ_ONLY_TOOLS:
            raise ValueError(f"MCP tool is outside the read-only boundary: {tool_name}")
        correlation_id = uuid4().hex
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                raw = await asyncio.wait_for(
                    self._client.call_tool(tool_name, arguments), timeout=self.timeout_seconds
                )
                return _unwrap_payload(raw)
            except (McpSchemaError, IndicativeFeedError):
                raise
            except TimeoutError:
                last_error = TimeoutError(
                    f"MCP call timed out correlation_id={correlation_id} tool={tool_name}"
                )
            except Exception as exc:  # noqa: BLE001 - provider errors are normalized here
                last_error = McpGatewayError(
                    f"MCP call failed correlation_id={correlation_id} tool={tool_name}: {exc}"
                )
            if attempt < self.retries:
                continue
        if last_error is not None:
            raise last_error
        raise McpGatewayError("MCP call failed without an error")


def _unwrap_payload(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise McpSchemaError("MCP returned invalid JSON text") from exc
    if isinstance(raw, Mapping):
        if raw.get("isError") or raw.get("is_error"):
            raise McpGatewayError("MCP reported an error result")
        if raw.get("data") is not None:
            return _unwrap_payload(raw["data"])
        structured = raw.get("structuredContent", raw.get("structured_content"))
        if structured is not None:
            return _unwrap_payload(structured)
        content = raw.get("content")
        if content is not None:
            return _unwrap_content(content)
        return raw
    data = getattr(raw, "data", None)
    if data is not None:
        return _unwrap_payload(data)
    model_dump = getattr(raw, "model_dump", None)
    if callable(model_dump):
        return _unwrap_payload(model_dump())
    structured = getattr(raw, "structuredContent", getattr(raw, "structured_content", None))
    if structured is not None:
        return _unwrap_payload(structured)
    content = getattr(raw, "content", None)
    if content is not None:
        return _unwrap_content(content)
    raise McpSchemaError("MCP returned an unsupported result type")


def _unwrap_content(content: Any) -> Any:
    if not isinstance(content, Sequence) or isinstance(content, str | bytes):
        raise McpSchemaError("MCP content is not a sequence")
    text_blocks: list[str] = []
    for block in content:
        if isinstance(block, Mapping) and block.get("type") == "text":
            text_blocks.append(str(block.get("text", "")))
        elif getattr(block, "type", None) == "text":
            text_blocks.append(str(getattr(block, "text", "")))
    if len(text_blocks) != 1:
        raise McpSchemaError("MCP content did not contain one JSON text block")
    return _unwrap_payload(text_blocks[0])


def _as_mapping(payload: Any, nested_key: str) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        nested = payload.get(nested_key)
        if isinstance(nested, Mapping):
            return nested
        return payload
    raise McpSchemaError(f"MCP {nested_key} payload is not an object")


def _sequence(payload: Any, *keys: str) -> Sequence[Any]:
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        return payload
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, str | bytes):
                return value
    raise McpSchemaError("MCP payload is missing its list")


def _required(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    raise McpSchemaError(f"MCP payload is missing one of: {', '.join(keys)}")


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise McpSchemaError(f"invalid decimal value: {value!r}") from exc


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise McpSchemaError(f"invalid boolean value: {value!r}")


def _datetime(value: Any) -> datetime:
    if not isinstance(value, datetime | str):
        raise McpSchemaError(f"invalid timestamp value: {value!r}")
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
    except ValueError as exc:
        raise McpSchemaError(f"invalid timestamp value: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise McpSchemaError("MCP timestamps must be timezone-aware")
    return parsed


def _format_datetime(value: datetime) -> str:
    _datetime(value)
    return value.isoformat().replace("+00:00", "Z")
