"""Metrics and promotion-gate tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from lexguard.research import metrics as metrics_module
from lexguard.research.metrics import (
    BacktestMetrics,
    EquityPoint,
    RoundTrip,
    calculate_metrics,
    evaluate_gate,
)


def valid_metrics() -> BacktestMetrics:
    return BacktestMetrics(
        total_return=Decimal("0.10"),
        annualized_return=Decimal("0.12"),
        daily_sharpe=Decimal("1.2"),
        max_drawdown=Decimal("-0.03"),
        profit_factor=Decimal("1.5"),
        completed_trades=60,
        win_rate=Decimal("0.55"),
        largest_day_profit_share=Decimal("0.20"),
        exposure=Decimal("0.10"),
        turnover=Decimal("1.0"),
        abstention_rate=Decimal("0.20"),
        long_vol_trades=30,
        short_vol_trades=30,
        missing_data_count=0,
        warnings=(),
    )


def test_gate_rejects_concentrated_profit() -> None:
    result = evaluate_gate(
        valid_metrics().model_copy(update={"largest_day_profit_share": Decimal("0.36")})
    )

    assert not result.passed
    assert "LARGEST_DAY_PROFIT_SHARE" in result.reason_codes


def test_gate_requires_every_oos_threshold() -> None:
    result = evaluate_gate(valid_metrics().model_copy(update={"daily_sharpe": Decimal("0.99")}))

    assert not result.passed
    assert result.reason_codes == ("DAILY_SHARPE",)


def test_calculate_metrics_uses_daily_sample_sharpe_and_round_trips() -> None:
    equity = tuple(
        EquityPoint(trading_date=day, equity=value)
        for day, value in (
            (date(2026, 1, 2), Decimal("100")),
            (date(2026, 1, 5), Decimal("110")),
            (date(2026, 1, 6), Decimal("105")),
        )
    )
    trades = (
        RoundTrip(trading_date=date(2026, 1, 5), net_pnl=Decimal("10"), strategy="LONG_VOL"),
        RoundTrip(trading_date=date(2026, 1, 6), net_pnl=Decimal("-5"), strategy="SHORT_VOL"),
    )

    result = calculate_metrics(
        equity,
        trades,
        exposure=Decimal("0.5"),
        turnover=Decimal("0.2"),
        abstention_rate=Decimal("0.1"),
    )

    assert result.total_return == Decimal("0.05")
    assert result.max_drawdown == Decimal("105") / Decimal("110") - Decimal("1")
    assert result.profit_factor == Decimal("2")
    assert result.completed_trades == 2
    assert result.long_vol_trades == 1
    assert result.short_vol_trades == 1


def test_hybrid_ships_only_with_improvement_and_no_more_than_ten_percent_return_loss() -> None:
    quant = valid_metrics()
    accepted = metrics_module.evaluate_hybrid_influence(
        quant,
        quant.model_copy(
            update={"profit_factor": Decimal("1.6"), "total_return": Decimal("0.09")}
        ),
    )
    rejected = metrics_module.evaluate_hybrid_influence(
        quant,
        quant.model_copy(
            update={"profit_factor": Decimal("1.6"), "total_return": Decimal("0.089")}
        ),
    )

    assert accepted.mode == "HYBRID"
    assert rejected.mode == "VETO_EXPLANATION_ONLY"
    assert rejected.reason_codes == ("NET_RETURN_DEGRADATION",)


@pytest.mark.parametrize(
    ("long_passes", "short_passes", "expected"),
    [
        (True, True, "BOTH"),
        (True, False, "LONG_ONLY"),
        (False, True, "SHORT_ONLY"),
        (False, False, "STOP_REDESIGN"),
    ],
)
def test_deployment_outcome_uses_both_side_gates(
    long_passes: bool, short_passes: bool, expected: str
) -> None:
    long_gate = evaluate_gate(
        valid_metrics() if long_passes else valid_metrics().model_copy(update={"total_return": 0}),
        strategy_side="LONG_VOL",
    )
    short_gate = evaluate_gate(
        valid_metrics() if short_passes else valid_metrics().model_copy(update={"total_return": 0}),
        strategy_side="SHORT_VOL",
    )

    assert metrics_module.deployment_outcome(long_gate, short_gate) == expected
