"""Conservative next-five-minute-bar option fill tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from lexguard.research import options_simulator as simulator
from lexguard.research.options_simulator import (
    AtomicSignal,
    HistoricalBar,
    SignalLeg,
    buy_fill,
    sell_fill,
    simulate_atomic_fill,
)

SIGNAL_TIME = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)


def signal() -> AtomicSignal:
    terms = (
        ("SPY260105P00500000", "SELL", "PUT", "500"),
        ("SPY260105P00505000", "BUY", "PUT", "505"),
        ("SPY260105C00550000", "BUY", "CALL", "550"),
        ("SPY260105C00555000", "SELL", "CALL", "555"),
    )
    return AtomicSignal(
        signal_id=UUID("11111111-1111-1111-1111-111111111111"),
        signaled_at=SIGNAL_TIME,
        legs=tuple(
            SignalLeg(
                symbol=symbol,
                side=side,
                underlying="SPY",
                expiration=date(2026, 1, 5),
                right=right,
                strike=Decimal(strike),
            )
            for symbol, side, right, strike in terms
        ),
    )


def bar(symbol: str, *, offset: int = 5, open_price: str = "1.00") -> HistoricalBar:
    return HistoricalBar(
        symbol=symbol,
        timestamp=SIGNAL_TIME + timedelta(minutes=offset),
        open=Decimal(open_price),
        metadata_resolved=True,
        corporate_action_continuous=True,
    )


def test_atomic_fill_requires_next_bar_for_all_four_legs() -> None:
    candidate = signal()
    bars = {leg.symbol: (bar(leg.symbol),) for leg in candidate.legs[:-1]}

    assert simulate_atomic_fill(candidate, bars) is None


def test_conservative_leg_prices() -> None:
    assert buy_fill(Decimal("1.00")) == Decimal("1.06")
    assert sell_fill(Decimal("1.00")) == Decimal("0.94")
    assert buy_fill(Decimal("0.10")) == Decimal("0.12")


def test_atomic_fill_uses_one_next_bar_for_each_leg_and_separate_fees() -> None:
    candidate = signal()
    bars = {leg.symbol: (bar(leg.symbol),) for leg in candidate.legs}

    result = simulate_atomic_fill(candidate, bars, fee_per_contract=Decimal("0.02"))

    assert result is not None
    assert result.filled_at == SIGNAL_TIME + timedelta(minutes=5)
    assert tuple(fill.price for fill in result.legs) == (
        Decimal("0.94"),
        Decimal("1.06"),
        Decimal("1.06"),
        Decimal("0.94"),
    )
    assert result.fees == Decimal("0.08")


def test_unresolved_contract_metadata_rejects_atomic_fill() -> None:
    candidate = signal()
    bars = {
        leg.symbol: (
            bar(leg.symbol)
            if leg is not candidate.legs[0]
            else HistoricalBar(
                symbol=leg.symbol,
                timestamp=SIGNAL_TIME + timedelta(minutes=5),
                open=Decimal("1"),
                metadata_resolved=False,
                corporate_action_continuous=True,
            ),
        )
        for leg in candidate.legs
    }

    assert simulate_atomic_fill(candidate, bars) is None


def test_atomic_signal_rejects_an_uncovered_or_mixed_expiry_structure() -> None:
    candidate = signal()
    invalid_legs = list(candidate.legs)
    invalid_legs[-1] = SignalLeg(
        symbol="SPY260106C00555000",
        side="SELL",
        underlying="SPY",
        expiration=date(2026, 1, 6),
        right="CALL",
        strike=Decimal("555"),
    )

    with pytest.raises(ValueError, match="same expiration"):
        AtomicSignal(
            signal_id=candidate.signal_id,
            signaled_at=candidate.signaled_at,
            legs=tuple(invalid_legs),
        )


def test_point_in_time_candidate_selection_ignores_future_only_contracts() -> None:
    contracts = tuple(
        simulator.OptionContractMetadata(
            symbol=leg.symbol,
            underlying=leg.underlying,
            expiration=leg.expiration,
            right=leg.right,
            strike=leg.strike,
            multiplier=100,
            deliverable_shares=100,
        )
        for leg in signal().legs
    )
    future_contracts = tuple(
        simulator.OptionContractMetadata(
            symbol=f"AAA260105{right[0]}{strike:08d}",
            underlying="SPY",
            expiration=date(2026, 1, 5),
            right=right,
            strike=Decimal(strike),
            multiplier=100,
            deliverable_shares=100,
        )
        for right, strike in (("PUT", 490), ("PUT", 495), ("CALL", 560), ("CALL", 565))
    )
    histories = {
        contract.symbol: (
            HistoricalBar(
                symbol=contract.symbol,
                timestamp=SIGNAL_TIME,
                open=Decimal("1"),
                metadata_resolved=True,
                corporate_action_continuous=True,
            ),
        )
        for contract in contracts
    }
    histories.update(
        {
            contract.symbol: (
                HistoricalBar(
                    symbol=contract.symbol,
                    timestamp=SIGNAL_TIME + timedelta(minutes=5),
                    open=Decimal("1"),
                    metadata_resolved=True,
                    corporate_action_continuous=True,
                ),
            )
            for contract in future_contracts
        }
    )

    selected = simulator.select_candidate_structure(
        signal_id=UUID("22222222-2222-2222-2222-222222222222"),
        signaled_at=SIGNAL_TIME,
        contracts=contracts + future_contracts,
        bars_by_contract=histories,
        strategy="LONG_VOL",
    )

    assert selected is not None
    assert tuple(leg.symbol for leg in selected.legs) == tuple(leg.symbol for leg in signal().legs)


def test_atomic_fill_rejects_a_timezone_mismatch() -> None:
    candidate = signal()
    bars = {leg.symbol: (bar(leg.symbol),) for leg in candidate.legs}
    first = candidate.legs[0]
    bars[first.symbol] = (
        HistoricalBar(
            symbol=first.symbol,
            timestamp=(SIGNAL_TIME + timedelta(minutes=5)).astimezone(
                timezone(timedelta(hours=1))
            ),
            open=Decimal("1"),
            metadata_resolved=True,
            corporate_action_continuous=True,
        ),
    )

    assert simulate_atomic_fill(candidate, bars) is None


def test_required_option_fees_follow_the_frozen_alpaca_schedule() -> None:
    assert simulator.calculate_option_fees("BUY", Decimal("1.00"), 1) == Decimal("0.0403")
    assert simulator.calculate_option_fees("SELL", Decimal("1.00"), 1) == Decimal("0.04565")


def test_atomic_fill_models_required_option_fees_by_default() -> None:
    candidate = signal()
    bars = {leg.symbol: (bar(leg.symbol),) for leg in candidate.legs}

    result = simulate_atomic_fill(candidate, bars)

    assert result is not None
    assert result.fees == Decimal("0.1716528")
