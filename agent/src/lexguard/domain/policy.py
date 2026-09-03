"""The deterministic risk constitution for every proposed structure."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from .models import CandidateStructure, ImmutableModel
from .payoff import exact_max_loss

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
MARKET_TIMEZONE = ZoneInfo("America/New_York")


EARLIEST_EXECUTION: dict[str, time] = {
    "10:05": time(10, 10),
    "11:35": time(11, 40),
    "13:05": time(13, 10),
    "14:20": time(14, 25),
}


class RiskContext(ImmutableModel):
    now: datetime
    decision_window: Literal["10:05", "11:35", "13:05", "14:20"]
    evidence_observed_at: datetime
    evidence_max_age_seconds: int = Field(default=120, ge=0)
    daily_pnl: Decimal
    competition_drawdown: Decimal
    account_equity: Decimal = Decimal("0")
    entries_today: int = Field(ge=0)
    traded_symbols_today: tuple[str, ...]
    open_structure_count: int = Field(ge=0)
    open_order_count: int = Field(ge=0)
    open_position_count: int = Field(ge=0)
    account_status: Literal["ACTIVE", "INACTIVE", "UNKNOWN"]
    options_level: int = Field(ge=0)
    opra_available: bool
    base_url: str
    certificate_expires_at: datetime | None = None
    entry_attempt: bool = False


class PolicyDecision(ImmutableModel):
    allowed: bool
    reason_codes: tuple[str, ...]
    details: dict[str, str]


class RiskPolicy:
    """Evaluate all independent safety gates and return every refusal reason."""

    def __init__(
        self,
        *,
        max_trade_loss: Decimal = Decimal("1000"),
        max_daily_loss: Decimal = Decimal("1500"),
        max_competition_drawdown: Decimal = Decimal("4000"),
        max_entries_per_day: int = 2,
    ) -> None:
        if max_entries_per_day < 1:
            raise ValueError("max_entries_per_day must be at least 1")
        self.max_trade_loss = max_trade_loss
        self.max_daily_loss = max_daily_loss
        self.max_competition_drawdown = max_competition_drawdown
        self.max_entries_per_day = max_entries_per_day

    def evaluate(self, proposal: CandidateStructure, context: RiskContext) -> PolicyDecision:
        reasons: set[str] = set()
        details: dict[str, str] = {}

        computed_loss = exact_max_loss(proposal)
        details["computed_max_loss"] = str(computed_loss)
        if proposal.max_loss > self.max_trade_loss or computed_loss > self.max_trade_loss:
            reasons.add("MAX_TRADE_LOSS")
        if context.daily_pnl <= -self.max_daily_loss or (
            context.daily_pnl - computed_loss <= -self.max_daily_loss
        ):
            reasons.add("DAILY_LOSS_LIMIT")
        if context.competition_drawdown >= self.max_competition_drawdown:
            reasons.add("COMPETITION_DRAWDOWN")

        if context.open_structure_count > 0:
            reasons.add("OPEN_STRUCTURE_EXISTS")
        if context.open_order_count > 0:
            reasons.add("WORKING_ORDER_EXISTS")
        if context.open_position_count > 0:
            reasons.add("OPEN_POSITION_EXISTS")
        if context.entries_today >= self.max_entries_per_day:
            reasons.add("DAILY_ENTRY_LIMIT")
        if proposal.underlying in context.traded_symbols_today:
            reasons.add("SAME_SYMBOL_REENTRY")

        market_now = context.now.astimezone(MARKET_TIMEZONE)
        earliest = EARLIEST_EXECUTION[context.decision_window]
        if context.entry_attempt and market_now.time() < earliest:
            reasons.add("ENTRY_WINDOW_CLOSED")

        age = context.now - context.evidence_observed_at
        if age < timedelta(0) or age > timedelta(seconds=context.evidence_max_age_seconds):
            reasons.add("STALE_EVIDENCE")

        dte = (proposal.expiration - market_now.date()).days
        details["dte"] = str(dte)
        if dte < 1 or dte > 3:
            reasons.add("DTE_OUT_OF_RANGE")

        if context.account_status != "ACTIVE":
            reasons.add("ACCOUNT_NOT_ACTIVE")
        if context.options_level < 3:
            reasons.add("OPTIONS_LEVEL_INSUFFICIENT")
        if not context.opra_available:
            reasons.add("OPRA_UNAVAILABLE")
        if context.base_url.rstrip("/") != PAPER_ENDPOINT:
            reasons.add("NON_PAPER_ENDPOINT")
        if (
            context.certificate_expires_at is not None
            and context.certificate_expires_at <= context.now
        ):
            reasons.add("CERTIFICATE_EXPIRED")

        if proposal.strategy == "LONG_VOL" and proposal.entry_limit <= 0:
            reasons.add("INVALID_DEBIT_SIGN")
        if proposal.strategy == "SHORT_VOL" and proposal.entry_limit >= 0:
            reasons.add("INVALID_CREDIT_SIGN")

        ordered = tuple(sorted(reasons))
        return PolicyDecision(allowed=not ordered, reason_codes=ordered, details=details)
