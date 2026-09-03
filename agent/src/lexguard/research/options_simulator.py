"""Deterministic custom options fill model used by historical research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import combinations
from typing import Final, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

SignalSide = Literal["BUY", "SELL"]
OptionRight = Literal["CALL", "PUT"]
StrategySide = Literal["LONG_VOL", "SHORT_VOL"]
_ORF_PER_CONTRACT: Final = Decimal("0.015")
_OCC_PER_CONTRACT: Final = Decimal("0.025")
_CAT_PER_EQUIVALENT_SHARE: Final = Decimal("0.000003")
_TAF_SELL_PER_CONTRACT: Final = Decimal("0.00329")
_SEC_SELL_RATE: Final = Decimal("0.0000206")
OPTION_FEE_SCHEDULE: Final = {
    "source_url": "https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf",
    "revision_date": "2026-07-20",
    "orf_per_contract": "0.015",
    "occ_per_contract": "0.025",
    "cat_per_executed_equivalent_share": "0.000003",
    "taf_sell_per_contract": "0.00329",
    "sec_sell_rate_on_trade_value": "0.0000206",
}


@dataclass(frozen=True, slots=True)
class OptionContractMetadata:
    symbol: str
    underlying: str
    expiration: date
    right: OptionRight
    strike: Decimal
    multiplier: int
    deliverable_shares: int

    def __post_init__(self) -> None:
        if (
            not self.symbol
            or not self.underlying
            or self.strike <= 0
            or self.multiplier <= 0
            or self.deliverable_shares <= 0
        ):
            raise ValueError("option contract metadata is incomplete")


@dataclass(frozen=True, slots=True)
class HistoricalBar:
    symbol: str
    timestamp: datetime
    open: Decimal
    metadata_resolved: bool
    corporate_action_continuous: bool

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("historical bar timestamp must be timezone-aware")
        if self.open <= 0:
            raise ValueError("historical bar open must be positive")


@dataclass(frozen=True, slots=True)
class SignalLeg:
    symbol: str
    side: SignalSide
    underlying: str
    expiration: date
    right: OptionRight
    strike: Decimal
    ratio: int = 1
    multiplier: int = 100
    deliverable_shares: int = 100

    def __post_init__(self) -> None:
        if not self.symbol or not self.underlying or self.ratio <= 0 or self.strike <= 0:
            raise ValueError("signal legs require a symbol and positive ratio")


@dataclass(frozen=True, slots=True)
class AtomicSignal:
    signal_id: UUID
    signaled_at: datetime
    legs: tuple[SignalLeg, SignalLeg, SignalLeg, SignalLeg]

    def __post_init__(self) -> None:
        if self.signaled_at.tzinfo is None or self.signaled_at.utcoffset() is None:
            raise ValueError("signal timestamp must be timezone-aware")
        if len({leg.symbol for leg in self.legs}) != 4:
            raise ValueError("atomic signal requires four distinct contracts")
        if len({leg.underlying for leg in self.legs}) != 1:
            raise ValueError("atomic signal legs require the same underlying")
        if len({leg.expiration for leg in self.legs}) != 1:
            raise ValueError("atomic signal legs require the same expiration")
        expiration = self.legs[0].expiration
        signal_date = self.signaled_at.astimezone(ZoneInfo("America/New_York")).date()
        if (expiration - signal_date).days not in {1, 2, 3}:
            raise ValueError("atomic signal expiration must be 1-3 DTE")
        if len({leg.ratio for leg in self.legs}) != 1:
            raise ValueError("atomic signal legs require equal ratios")
        if any(leg.multiplier != 100 or leg.deliverable_shares != 100 for leg in self.legs):
            raise ValueError("atomic signal requires standard covered option contracts")
        puts = sorted((leg for leg in self.legs if leg.right == "PUT"), key=lambda leg: leg.strike)
        calls = sorted(
            (leg for leg in self.legs if leg.right == "CALL"), key=lambda leg: leg.strike
        )
        if len(puts) != 2 or len(calls) != 2:
            raise ValueError("atomic signal requires two puts and two calls")
        if not (puts[0].strike < puts[1].strike < calls[0].strike < calls[1].strike):
            raise ValueError("atomic signal strikes do not form covered wings")
        side_pattern = tuple(leg.side for leg in (*puts, *calls))
        if side_pattern not in {
            ("BUY", "SELL", "SELL", "BUY"),
            ("SELL", "BUY", "BUY", "SELL"),
        }:
            raise ValueError("atomic signal is not an iron condor or reverse iron condor")

    @property
    def strategy(self) -> StrategySide:
        lower_put = min(
            (leg for leg in self.legs if leg.right == "PUT"), key=lambda leg: leg.strike
        )
        return "SHORT_VOL" if lower_put.side == "BUY" else "LONG_VOL"


@dataclass(frozen=True, slots=True)
class LegFill:
    symbol: str
    side: SignalSide
    ratio: int
    price: Decimal


@dataclass(frozen=True, slots=True)
class AtomicFill:
    signal_id: UUID
    filled_at: datetime
    legs: tuple[LegFill, LegFill, LegFill, LegFill]
    total_notional: Decimal
    fees: Decimal


def buy_fill(open_price: Decimal) -> Decimal:
    """Buy at the open plus the larger of two cents or six percent."""

    friction = max(Decimal("0.02"), Decimal("0.06") * open_price)
    return open_price + friction


def sell_fill(open_price: Decimal) -> Decimal:
    """Sell at the open less the larger of two cents or six percent."""

    friction = max(Decimal("0.02"), Decimal("0.06") * open_price)
    return max(Decimal("0.01"), open_price - friction)


def calculate_option_fees(side: SignalSide, premium: Decimal, contracts: int) -> Decimal:
    """Calculate unrounded pass-through fees from the frozen Alpaca fee schedule."""

    if premium <= 0 or contracts <= 0:
        raise ValueError("fee calculation requires positive premium and contract count")
    count = Decimal(contracts)
    common = count * (_ORF_PER_CONTRACT + _OCC_PER_CONTRACT + _CAT_PER_EQUIVALENT_SHARE * 100)
    if side == "BUY":
        return common
    return common + count * (
        _TAF_SELL_PER_CONTRACT + premium * Decimal("100") * _SEC_SELL_RATE
    )


def simulate_atomic_fill(
    signal: AtomicSignal,
    bars_by_contract: Mapping[str, Sequence[HistoricalBar]],
    *,
    fee_per_contract: Decimal | None = None,
) -> AtomicFill | None:
    """Fill all four legs at their exact next five-minute bar open or abstain."""

    if fee_per_contract is not None and fee_per_contract < 0:
        raise ValueError("fee_per_contract must be non-negative")
    expected_timestamp = signal.signaled_at + timedelta(minutes=5)
    fills: list[LegFill] = []
    total_notional = Decimal("0")
    contract_count = 0
    modeled_fees = Decimal("0")
    for leg in signal.legs:
        bars = bars_by_contract.get(leg.symbol)
        if not bars or tuple(bar.timestamp for bar in bars) != tuple(
            sorted(bar.timestamp for bar in bars)
        ):
            return None
        if len({bar.timestamp for bar in bars}) != len(bars):
            return None
        if any(bar.timestamp.tzinfo != signal.signaled_at.tzinfo for bar in bars):
            return None
        matching = [bar for bar in bars if bar.timestamp == expected_timestamp]
        if len(matching) != 1:
            return None
        next_bar = matching[0]
        if (
            next_bar.symbol != leg.symbol
            or not next_bar.metadata_resolved
            or not next_bar.corporate_action_continuous
        ):
            return None
        price = buy_fill(next_bar.open) if leg.side == "BUY" else sell_fill(next_bar.open)
        fills.append(LegFill(leg.symbol, leg.side, leg.ratio, price))
        total_notional += price * Decimal(leg.ratio) * Decimal("100")
        contract_count += leg.ratio
        modeled_fees += calculate_option_fees(leg.side, price, leg.ratio)
    return AtomicFill(
        signal_id=signal.signal_id,
        filled_at=expected_timestamp,
        legs=tuple(fills),  # type: ignore[arg-type]
        total_notional=total_notional,
        fees=(
            fee_per_contract * Decimal(contract_count)
            if fee_per_contract is not None
            else modeled_fees
        ),
    )


def select_candidate_structure(
    *,
    signal_id: UUID,
    signaled_at: datetime,
    contracts: Sequence[OptionContractMetadata],
    bars_by_contract: Mapping[str, Sequence[HistoricalBar]],
    strategy: StrategySide,
) -> AtomicSignal | None:
    """Select a deterministic valid structure using observations available by the signal."""

    if signaled_at.tzinfo is None or signaled_at.utcoffset() is None:
        raise ValueError("signal timestamp must be timezone-aware")
    signal_date = signaled_at.astimezone(ZoneInfo("America/New_York")).date()
    eligible: list[OptionContractMetadata] = []
    for contract in contracts:
        dte = (contract.expiration - signal_date).days
        if dte not in {1, 2, 3} or contract.multiplier != 100 or contract.deliverable_shares != 100:
            continue
        observed = tuple(
            bar for bar in bars_by_contract.get(contract.symbol, ()) if bar.timestamp <= signaled_at
        )
        if not observed or observed[-1].timestamp != signaled_at:
            continue
        if tuple(bar.timestamp for bar in observed) != tuple(
            sorted(bar.timestamp for bar in observed)
        ) or len({bar.timestamp for bar in observed}) != len(observed):
            continue
        if any(
            bar.timestamp.tzinfo != signaled_at.tzinfo
            or bar.symbol != contract.symbol
            or not bar.metadata_resolved
            or not bar.corporate_action_continuous
            for bar in observed
        ):
            continue
        eligible.append(contract)

    groups: dict[tuple[str, date], list[OptionContractMetadata]] = {}
    for contract in eligible:
        groups.setdefault((contract.underlying, contract.expiration), []).append(contract)
    candidates: list[tuple[tuple[object, ...], AtomicSignal]] = []
    for (underlying, expiration), group in groups.items():
        puts = sorted((item for item in group if item.right == "PUT"), key=_contract_key)
        calls = sorted((item for item in group if item.right == "CALL"), key=_contract_key)
        for put_pair in combinations(puts, 2):
            for call_pair in combinations(calls, 2):
                low_put, high_put = put_pair
                low_call, high_call = call_pair
                if not (low_put.strike < high_put.strike < low_call.strike < high_call.strike):
                    continue
                sides: tuple[SignalSide, SignalSide, SignalSide, SignalSide] = (
                    ("SELL", "BUY", "BUY", "SELL")
                    if strategy == "LONG_VOL"
                    else ("BUY", "SELL", "SELL", "BUY")
                )
                ordered_contracts = (low_put, high_put, low_call, high_call)
                legs = tuple(
                    SignalLeg(
                        symbol=contract.symbol,
                        side=side,
                        underlying=underlying,
                        expiration=expiration,
                        right=contract.right,
                        strike=contract.strike,
                        multiplier=contract.multiplier,
                        deliverable_shares=contract.deliverable_shares,
                    )
                    for contract, side in zip(ordered_contracts, sides, strict=True)
                )
                candidate = AtomicSignal(
                    signal_id=signal_id,
                    signaled_at=signaled_at,
                    legs=legs,  # type: ignore[arg-type]
                )
                key: tuple[object, ...] = (
                    expiration,
                    underlying,
                    *(contract.strike for contract in ordered_contracts),
                    *(contract.symbol for contract in ordered_contracts),
                )
                candidates.append((key, candidate))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _contract_key(contract: OptionContractMetadata) -> tuple[Decimal, str]:
    return contract.strike, contract.symbol
