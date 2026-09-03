"""Forecast ensemble and fixed scenario-transform tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from lexguard.domain.enums import Scenario
from lexguard.domain.models import UnderlyingBar
from lexguard.research.features import build_features
from lexguard.research.forecast import (
    ForecastEnsemble,
    HistoricalSample,
    apply_scenario,
)

AS_OF = datetime(2026, 8, 24, 14, 5, tzinfo=UTC)


def _features(offset: int) -> object:
    bars = tuple(
        UnderlyingBar(
            symbol="SPY",
            timestamp=AS_OF - timedelta(minutes=(5 - index) * 5) + timedelta(days=offset),
            open=Decimal("590") + Decimal(index),
            high=Decimal("591") + Decimal(index),
            low=Decimal("589") + Decimal(index),
            close=Decimal("590.50") + Decimal(index) + Decimal(index % 2) / Decimal("2"),
            volume=1000 + index * 10,
        )
        for index in range(6)
    )
    return build_features(bars, AS_OF + timedelta(days=offset))


def _history() -> tuple[HistoricalSample, ...]:
    return tuple(
        HistoricalSample(
            features=_features(index),
            target_return=Decimal("-0.012") + Decimal(index) * Decimal("0.004"),
        )
        for index in range(5)
    )


def test_fit_uses_only_history_at_or_before_training_end() -> None:
    history = _history()
    training_end = history[2].features.as_of
    artifact = ForecastEnsemble.fit(history, training_end)
    future_included = ForecastEnsemble.fit(history[:3], training_end)

    assert artifact == future_included
    assert artifact.training_end == training_end


def test_forecast_artifact_and_distribution_are_deterministic() -> None:
    artifact_left = ForecastEnsemble.fit(_history(), AS_OF + timedelta(days=4))
    artifact_right = ForecastEnsemble.fit(_history(), AS_OF + timedelta(days=4))
    distribution_left = ForecastEnsemble(artifact_left).predict(_features(5))
    distribution_right = ForecastEnsemble(artifact_right).predict(_features(5))

    assert artifact_left.artifact_hash == artifact_right.artifact_hash
    assert distribution_left == distribution_right
    assert sum(node.probability for node in distribution_left.nodes) == Decimal("1")


def test_vol_up_increases_dispersion(distribution_fixture: object) -> None:
    distribution = distribution_fixture
    adjusted = apply_scenario(distribution, Scenario.VOL_UP)  # type: ignore[arg-type]

    assert _std(adjusted) == pytest.approx(_std(distribution) * Decimal("1.10"))  # type: ignore[arg-type]
    assert sum(node.probability for node in adjusted.nodes) == Decimal("1")


def test_vol_down_reduces_dispersion_and_left_tail_reweights() -> None:
    distribution = ForecastEnsemble(
        ForecastEnsemble.fit(_history(), AS_OF + timedelta(days=4))
    ).predict(_features(5))
    down = apply_scenario(distribution, Scenario.VOL_DOWN)
    left = apply_scenario(distribution, Scenario.LEFT_TAIL)

    assert _std(down) == pytest.approx(_std(distribution) * Decimal("0.90"))
    negative_mass = sum(node.probability for node in distribution.nodes if node.return_value < 0)
    adjusted_negative_mass = sum(node.probability for node in left.nodes if node.return_value < 0)
    assert adjusted_negative_mass > negative_mass


def _std(distribution: object) -> Decimal:
    nodes = distribution.nodes  # type: ignore[attr-defined]
    mean = sum((node.return_value * node.probability for node in nodes), Decimal("0"))
    variance = sum(((node.return_value - mean) ** 2) * node.probability for node in nodes)
    return variance.sqrt()


@pytest.fixture
def distribution_fixture():
    return ForecastEnsemble(ForecastEnsemble.fit(_history(), AS_OF + timedelta(days=4))).predict(
        _features(5)
    )
