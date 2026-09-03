"""Collect and hash one immutable, auditable market-evidence snapshot."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from lexguard.adapters.alpaca_mcp import (
    AlpacaMcpGateway,
    McpSchemaError,
)
from lexguard.domain.enums import DecisionWindow
from lexguard.domain.hashing import canonical_sha256
from lexguard.domain.models import (
    AccountSnapshot,
    AllowedUnderlying,
    MarketEvidence,
    OptionQuote,
    UnderlyingBar,
)


class EvidenceUnavailable(RuntimeError):
    """Required evidence could not be collected or validated."""


_NEW_YORK = ZoneInfo("America/New_York")
# The strategy only trades 1-3 DTE structures whose strikes sit near spot; a
# bounded chain request keeps the snapshot inside the provider's row limit
# instead of receiving an arbitrary slice of a many-thousand-contract chain.
_CHAIN_STRIKE_BAND = Decimal("0.06")
_CHAIN_LIMIT_PER_EXPIRATION = 250
_CHAIN_DTE_RANGE = (1, 2, 3)


class EvidenceService:
    def __init__(
        self,
        gateway: AlpacaMcpGateway,
        *,
        case_id: UUID,
        underlying: AllowedUnderlying,
        base_url: str | None = None,
    ) -> None:
        self.gateway = gateway
        self.case_id = case_id
        self.underlying = underlying
        self.base_url = base_url or gateway.base_url

    async def collect(self, window: DecisionWindow, observed_at: datetime) -> MarketEvidence:
        try:
            results = await asyncio.gather(
                self.gateway.get_clock(),
                self.gateway.get_account_info(),
                self.gateway.get_orders(status="open"),
                self.gateway.get_positions(),
                self.gateway.get_underlying_bars(
                    self.underlying,
                    start=observed_at - timedelta(minutes=65),
                    end=observed_at,
                ),
                self.gateway.get_news(self.underlying, end=observed_at),
            )
            clock, account, orders, positions, bars, news = results
            if not clock.is_open:
                raise EvidenceUnavailable("Alpaca clock is closed")
            if not bars:
                raise EvidenceUnavailable("required market evidence is empty")
            quotes = await self._collect_option_chain(bars, observed_at)
            if not quotes:
                raise EvidenceUnavailable("required market evidence is empty")
            status = cast(
                Literal["ACTIVE", "INACTIVE", "UNKNOWN"],
                account.status if account.status in {"ACTIVE", "INACTIVE"} else "UNKNOWN",
            )
            snapshot = AccountSnapshot(
                observed_at=observed_at,
                status=status,
                equity=account.equity,
                buying_power=account.buying_power,
                daily_pnl=account.daily_pnl,
                competition_drawdown=account.competition_drawdown,
                options_level=account.options_level,
                opra_available=account.opra_available,
                # The account payload cannot count structures; any open broker
                # position is conservatively treated as an open structure.
                open_structure_count=max(
                    account.open_structure_count, 1 if positions else 0
                ),
                open_order_count=len(orders),
                open_position_count=len(positions),
                base_url=self.base_url,
            )
            evidence = MarketEvidence(
                case_id=self.case_id,
                observed_at=observed_at,
                decision_window=window.value,
                underlying=self.underlying,
                underlying_bars=tuple(bars),
                option_quotes=tuple(quotes),
                news=tuple(news),
                account_snapshot=snapshot,
                source="alpaca_mcp",
                content_hash="",
            )
            return evidence.model_copy(update={"content_hash": canonical_sha256(evidence)})
        except EvidenceUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - all provider failures veto evidence collection
            raise EvidenceUnavailable("Alpaca evidence is unavailable") from exc

    async def _collect_option_chain(
        self, bars: tuple[UnderlyingBar, ...], observed_at: datetime
    ) -> tuple[OptionQuote, ...]:
        """Fetch tradable-window chains bounded by expiration and strike.

        Chain filters are supported by the MCP ``get_option_chain`` tool; a
        holiday expiration returning no snapshots is not an error because the
        candidate DTE gate re-filters whatever this returns.
        """

        spot = bars[-1].close
        low = spot * (Decimal("1") - _CHAIN_STRIKE_BAND)
        high = spot * (Decimal("1") + _CHAIN_STRIKE_BAND)
        observed_date = observed_at.astimezone(_NEW_YORK).date()
        expirations = [
            expiration
            for dte in _CHAIN_DTE_RANGE
            if (expiration := observed_date + timedelta(days=dte)).weekday() < 5
        ]
        merged: dict[str, OptionQuote] = {}
        for expiration in expirations:
            try:
                quotes = await self.gateway.get_option_chain(
                    self.underlying,
                    expiration_date=expiration,
                    strike_price_gte=low,
                    strike_price_lte=high,
                    limit=_CHAIN_LIMIT_PER_EXPIRATION,
                )
            except McpSchemaError as exc:
                if "no snapshots" in str(exc):
                    continue
                raise
            for quote in quotes:
                merged[quote.symbol] = quote
        return tuple(merged.values())
