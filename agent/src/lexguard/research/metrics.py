"""Deterministic daily metrics and machine-readable research gates."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from lexguard.domain.models import ImmutableModel


class EquityPoint(ImmutableModel):
    trading_date: date
    equity: Decimal = Field(gt=0)


class RoundTrip(ImmutableModel):
    trading_date: date
    net_pnl: Decimal
    strategy: Literal["LONG_VOL", "SHORT_VOL"]


class BacktestMetrics(ImmutableModel):
    total_return: Decimal
    annualized_return: Decimal
    daily_sharpe: Decimal
    max_drawdown: Decimal
    profit_factor: Decimal = Field(allow_inf_nan=True)
    completed_trades: int = Field(ge=0)
    win_rate: Decimal = Field(ge=0, le=1)
    largest_day_profit_share: Decimal = Field(ge=0)
    exposure: Decimal = Field(ge=0)
    turnover: Decimal = Field(ge=0)
    abstention_rate: Decimal = Field(ge=0, le=1)
    long_vol_trades: int = Field(ge=0)
    short_vol_trades: int = Field(ge=0)
    missing_data_count: int = Field(ge=0)
    warnings: tuple[str, ...]


class GateResult(ImmutableModel):
    passed: bool
    reason_codes: tuple[str, ...]
    metrics: BacktestMetrics
    strategy_side: Literal["LONG_VOL", "SHORT_VOL", "HYBRID", "QUANT_ONLY"] = "HYBRID"


class HybridInfluenceResult(ImmutableModel):
    mode: Literal["HYBRID", "VETO_EXPLANATION_ONLY"]
    reason_codes: tuple[str, ...]


class BacktestResult(ImmutableModel):
    run_id: str
    metrics: BacktestMetrics
    gate: GateResult
    equity: tuple[EquityPoint, ...]
    round_trips: tuple[RoundTrip, ...]
    data_fingerprint: dict[str, object]
    warnings: tuple[str, ...]


def calculate_metrics(
    equity: Sequence[EquityPoint],
    round_trips: Sequence[RoundTrip],
    *,
    exposure: Decimal,
    turnover: Decimal,
    abstention_rate: Decimal,
    missing_data_count: int = 0,
    warnings: Sequence[str] = (),
) -> BacktestMetrics:
    if not equity:
        raise ValueError("equity curve cannot be empty")
    ordered = tuple(sorted(equity, key=lambda point: point.trading_date))
    if len({point.trading_date for point in ordered}) != len(ordered):
        raise ValueError("equity curve dates must be unique")
    initial = ordered[0].equity
    total_return = ordered[-1].equity / initial - Decimal("1")
    daily_returns = tuple(
        current.equity / previous.equity - Decimal("1")
        for previous, current in zip(ordered[:-1], ordered[1:], strict=True)
    )
    daily_sharpe = _sample_sharpe(daily_returns)
    running_max = ordered[0].equity
    drawdowns: list[Decimal] = []
    for point in ordered:
        running_max = max(running_max, point.equity)
        drawdowns.append(point.equity / running_max - Decimal("1"))
    days = len(ordered) - 1
    annualized = (
        (Decimal("1") + total_return) ** (Decimal("252") / Decimal(days)) - Decimal("1")
        if days > 0
        else Decimal("0")
    )
    winning = tuple(trip.net_pnl for trip in round_trips if trip.net_pnl > 0)
    losing = tuple(trip.net_pnl for trip in round_trips if trip.net_pnl < 0)
    gross_wins = sum(winning, Decimal("0"))
    gross_losses = abs(sum(losing, Decimal("0")))
    profit_factor = (
        gross_wins / gross_losses
        if gross_losses
        else Decimal("Infinity")
        if gross_wins
        else Decimal("0")
    )
    daily_profit: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    for trip in round_trips:
        daily_profit[trip.trading_date] += trip.net_pnl
    total_profit = sum((max(value, Decimal("0")) for value in daily_profit.values()), Decimal("0"))
    largest_day = max(daily_profit.values(), default=Decimal("0"))
    long_count = sum(trip.strategy == "LONG_VOL" for trip in round_trips)
    short_count = sum(trip.strategy == "SHORT_VOL" for trip in round_trips)
    return BacktestMetrics(
        total_return=total_return,
        annualized_return=annualized,
        daily_sharpe=daily_sharpe,
        max_drawdown=min(drawdowns),
        profit_factor=profit_factor,
        completed_trades=len(round_trips),
        win_rate=Decimal(len(winning)) / Decimal(len(round_trips)) if round_trips else Decimal("0"),
        largest_day_profit_share=largest_day / total_profit if total_profit else Decimal("0"),
        exposure=exposure,
        turnover=turnover,
        abstention_rate=abstention_rate,
        long_vol_trades=long_count,
        short_vol_trades=short_count,
        missing_data_count=missing_data_count,
        warnings=tuple(sorted(set(warnings))),
    )


def _sample_sharpe(returns: Sequence[Decimal]) -> Decimal:
    if len(returns) < 2:
        return Decimal("0")
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((value - mean) ** 2 for value in returns) / Decimal(len(returns) - 1)
    if variance == 0:
        return Decimal("0")
    return mean / variance.sqrt() * Decimal("252").sqrt()


def evaluate_gate(
    metrics: BacktestMetrics,
    *,
    strategy_side: Literal["LONG_VOL", "SHORT_VOL", "HYBRID", "QUANT_ONLY"] = "HYBRID",
) -> GateResult:
    reasons: set[str] = set()
    if metrics.total_return <= 0:
        reasons.add("NET_RETURN")
    if metrics.profit_factor < Decimal("1.20"):
        reasons.add("PROFIT_FACTOR")
    if metrics.daily_sharpe < Decimal("1.0"):
        reasons.add("DAILY_SHARPE")
    if abs(metrics.max_drawdown) > Decimal("0.04"):
        reasons.add("MAX_DRAWDOWN")
    if metrics.completed_trades < 60:
        reasons.add("COMPLETED_TRADES")
    if metrics.largest_day_profit_share > Decimal("0.35"):
        reasons.add("LARGEST_DAY_PROFIT_SHARE")
    if metrics.missing_data_count > 0:
        reasons.add("MISSING_DATA")
    if metrics.warnings:
        reasons.add("WARNINGS")
    return GateResult(
        passed=not reasons,
        reason_codes=tuple(sorted(reasons)),
        metrics=metrics,
        strategy_side=strategy_side,
    )


def evaluate_hybrid_influence(
    quant_only: BacktestMetrics, hybrid: BacktestMetrics
) -> HybridInfluenceResult:
    """Apply the frozen hybrid promotion rule from the research design."""

    reasons: list[str] = []
    improved = (
        hybrid.profit_factor > quant_only.profit_factor
        or hybrid.max_drawdown > quant_only.max_drawdown
    )
    if not improved:
        reasons.append("NO_RISK_ADJUSTED_IMPROVEMENT")
    return_floor = quant_only.total_return * Decimal("0.90")
    if hybrid.total_return < return_floor:
        reasons.append("NET_RETURN_DEGRADATION")
    return HybridInfluenceResult(
        mode="VETO_EXPLANATION_ONLY" if reasons else "HYBRID",
        reason_codes=tuple(sorted(reasons)),
    )


def deployment_outcome(
    long_gate: GateResult, short_gate: GateResult
) -> Literal["BOTH", "LONG_ONLY", "SHORT_ONLY", "STOP_REDESIGN"]:
    if long_gate.passed and short_gate.passed:
        return "BOTH"
    if long_gate.passed:
        return "LONG_ONLY"
    if short_gate.passed:
        return "SHORT_ONLY"
    return "STOP_REDESIGN"
