"""Pydantic contracts shared by every Lexguard boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AllowedUnderlying = Literal["SPY", "QQQ", "IWM"]
# Fixed New-York evaluation windows; execution runs five minutes after each.
# 14:20 is the latest window whose entry still satisfies the 60-minute
# minimum hold before the 15:30 forced exit.
DecisionWindow = Literal["10:05", "11:35", "13:05", "14:20"]
# OPRA is the consolidated feed; "indicative" is Alpaca's derived feed for
# accounts without an OPRA subscription. The configured feed is an explicit,
# disclosed operator choice enforced end-to-end as quote provenance.
OptionFeed = Literal["opra", "indicative"]
OptionRight = Literal["C", "P"]
OrderSide = Literal["BUY", "SELL"]
Strategy = Literal["LONG_VOL", "SHORT_VOL"]
Scenario = Literal["BASE", "VOL_UP", "VOL_DOWN", "LEFT_TAIL", "RIGHT_TAIL", "VETO"]

_OPTION_SYMBOL = re.compile(
    r"^(?P<root>[A-Z]{1,6})(?P<expiry>\d{6})(?P<right>[CP])(?P<strike>\d{8})$"
)


def _reject_naive_datetimes(data: Any) -> Any:
    if isinstance(data, Mapping):
        for value in data.values():
            if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("timestamps must be timezone-aware")
    return data


class ImmutableModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        str_strip_whitespace=True,
    )

    @model_validator(mode="before")
    @classmethod
    def reject_naive_datetime_values(cls, data: Any) -> Any:
        return _reject_naive_datetimes(data)


class UnderlyingBar(ImmutableModel):
    symbol: AllowedUnderlying
    timestamp: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> UnderlyingBar:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC bounds are inconsistent")
        return self


class OptionLeg(ImmutableModel):
    symbol: str
    underlying: AllowedUnderlying
    expiration: date
    strike: Decimal = Field(gt=0)
    right: OptionRight
    side: OrderSide
    ratio: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_option_symbol(self) -> OptionLeg:
        match = _OPTION_SYMBOL.fullmatch(self.symbol)
        if match is None:
            raise ValueError("invalid option symbol")
        if match.group("root") != self.underlying:
            raise ValueError("option symbol underlying does not match leg")
        encoded_expiration = datetime.strptime(match.group("expiry"), "%y%m%d").date()
        if encoded_expiration != self.expiration:
            raise ValueError("option symbol expiration does not match leg")
        encoded_strike = Decimal(match.group("strike")) / Decimal("1000")
        if encoded_strike != self.strike:
            raise ValueError("option symbol strike does not match leg")
        if match.group("right") != self.right:
            raise ValueError("option symbol right does not match leg")
        if self.ratio != 1:
            raise ValueError("each leg must have a 1:1:1:1 ratio")
        return self


class OptionQuote(ImmutableModel):
    symbol: str
    underlying: AllowedUnderlying
    expiration: date
    strike: Decimal = Field(gt=0)
    right: OptionRight
    bid: Decimal | None = Field(default=None, ge=0)
    ask: Decimal | None = Field(default=None, ge=0)
    last: Decimal | None = Field(default=None, ge=0)
    # Option snapshots do not always carry open interest; None means unknown,
    # which is distinct from a known zero.
    open_interest: int | None = Field(default=None, ge=0)
    implied_volatility: Decimal | None = Field(default=None, ge=0)
    observed_at: datetime
    feed: OptionFeed

    @model_validator(mode="after")
    def validate_quote(self) -> OptionQuote:
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("option quote is crossed")
        return self


class NewsEvidence(ImmutableModel):
    evidence_id: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    published_at: datetime
    source: str = Field(min_length=1)
    url: str | None = None


class AccountSnapshot(ImmutableModel):
    observed_at: datetime
    status: Literal["ACTIVE", "INACTIVE", "UNKNOWN"]
    equity: Decimal
    buying_power: Decimal
    daily_pnl: Decimal
    competition_drawdown: Decimal
    options_level: int = Field(ge=0)
    opra_available: bool
    open_structure_count: int = Field(default=0, ge=0)
    open_order_count: int = Field(default=0, ge=0)
    open_position_count: int = Field(default=0, ge=0)
    base_url: str


class MarketEvidence(ImmutableModel):
    case_id: UUID
    observed_at: datetime
    decision_window: DecisionWindow
    underlying: AllowedUnderlying
    underlying_bars: tuple[UnderlyingBar, ...]
    option_quotes: tuple[OptionQuote, ...]
    news: tuple[NewsEvidence, ...]
    account_snapshot: AccountSnapshot
    source: Literal["alpaca_mcp"]
    content_hash: str


class CatalystAssessment(ImmutableModel):
    scenario: Scenario
    confidence: Decimal = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...]
    rationale: str = Field(max_length=800)
    model: Literal["gpt-4o-mini"]
    prompt_version: str = Field(min_length=1)
    assessed_at: datetime | None = None


class ForecastNode(ImmutableModel):
    return_value: Decimal
    probability: Decimal = Field(ge=0, le=1)


class ForecastDistribution(ImmutableModel):
    nodes: tuple[ForecastNode, ...] = Field(min_length=1)
    calibrated_at: datetime
    training_end: datetime
    artifact_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_probabilities(self) -> ForecastDistribution:
        total = sum((node.probability for node in self.nodes), Decimal("0"))
        if total != Decimal("1"):
            raise ValueError("forecast probabilities must sum to 1")
        if self.training_end > self.calibrated_at:
            raise ValueError("training_end must not be after calibrated_at")
        return self


class CandidateStructure(ImmutableModel):
    candidate_id: UUID
    strategy: Strategy
    underlying: AllowedUnderlying
    expiration: date
    legs: tuple[OptionLeg, OptionLeg, OptionLeg, OptionLeg]
    quantity: int = Field(gt=0)
    entry_limit: Decimal
    max_loss: Decimal = Field(ge=0)
    modeled_friction: Decimal = Field(ge=0)
    modeled_fees: Decimal = Field(ge=0)
    robust_ev: Decimal

    @model_validator(mode="after")
    def validate_structure(self) -> CandidateStructure:
        if len(self.legs) != 4:
            raise ValueError("candidate requires exactly four legs")
        if any(leg.expiration != self.expiration for leg in self.legs):
            raise ValueError("all legs must have the same expiration")
        if any(leg.underlying != self.underlying for leg in self.legs):
            raise ValueError("all legs must have the same underlying")
        if any(leg.ratio != 1 for leg in self.legs):
            raise ValueError("candidate legs must use a 1:1:1:1 ratio")
        rights = tuple(leg.right for leg in self.legs)
        strikes = tuple(leg.strike for leg in self.legs)
        expected_sides = (
            ("SELL", "BUY", "BUY", "SELL")
            if self.strategy == "LONG_VOL"
            else ("BUY", "SELL", "SELL", "BUY")
        )
        if rights != ("P", "P", "C", "C") or any(
            left >= right for left, right in zip(strikes, strikes[1:], strict=False)
        ):
            raise ValueError("candidate is not an ordered covered condor")
        if tuple(leg.side for leg in self.legs) != expected_sides:
            raise ValueError("candidate is not a covered condor")
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> CandidateStructure:
        if update is None:
            return super().model_copy(deep=deep)
        data = self.model_dump(mode="python")
        data.update(update)
        return type(self).model_validate(data)


class TradeCertificate(ImmutableModel):
    certificate_id: UUID
    case_id: UUID
    candidate: CandidateStructure
    issued_at: datetime
    expires_at: datetime
    policy_version: str = Field(min_length=1)
    proposal_hash: str = Field(min_length=1)
    account_equity: Decimal
    daily_pnl: Decimal
    competition_drawdown: Decimal

    @model_validator(mode="after")
    def validate_expiry(self) -> TradeCertificate:
        if self.expires_at <= self.issued_at:
            raise ValueError("certificate expires_at must be after issued_at")
        return self


class RefusalRecord(ImmutableModel):
    case_id: UUID
    refused_at: datetime
    reason_codes: tuple[str, ...]
    details: dict[str, str]


class ExecutionRecord(ImmutableModel):
    case_id: UUID
    certificate_id: UUID
    alpaca_order_ids: tuple[str, ...]
    state: Literal[
        "SUBMITTED",
        "REPLACED",
        "FILLED",
        "CANCELED",
        "REJECTED",
        "RECONCILE_REQUIRED",
    ]
    submitted_at: datetime
    updated_at: datetime
    filled_quantity: int = Field(ge=0)
    average_fill_price: Decimal | None = None
