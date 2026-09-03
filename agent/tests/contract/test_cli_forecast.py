"""seed-forecast must emit an artifact the runtime loader verifies byte-for-byte."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from lexguard.cli import (
    _forecast_provider_from_file,
    _forecast_samples_from_gateway,
)
from lexguard.domain.models import UnderlyingBar
from lexguard.research.forecast import ForecastEnsemble

NOW = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)


class BarFakeGateway:
    """Serve synthetic but well-formed 5-minute session bars per day."""

    async def get_underlying_bars(
        self, symbol: str, *, start: datetime, end: datetime, limit: int = 1000
    ) -> tuple[UnderlyingBar, ...]:
        bars = []
        price = Decimal("640") + Decimal(start.day)
        timestamp = start
        while timestamp <= end:
            price = price + Decimal("0.05")
            bars.append(
                UnderlyingBar(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=price,
                    high=price + Decimal("0.10"),
                    low=price - Decimal("0.10"),
                    close=price + Decimal("0.02"),
                    volume=1000 + timestamp.minute,
                )
            )
            timestamp = timestamp + timedelta(minutes=5)
        return tuple(bars)


@pytest.mark.asyncio
async def test_forecast_samples_cover_only_weekday_sessions() -> None:
    samples = await _forecast_samples_from_gateway(
        BarFakeGateway(), "SPY", days=10, now=NOW
    )

    assert len(samples) == 10
    assert all(sample.features.symbol == "SPY" for sample in samples)
    assert all(sample.features.as_of.weekday() < 5 for sample in samples)


@pytest.mark.asyncio
async def test_fitted_artifact_round_trips_through_runtime_loader(tmp_path: Path) -> None:
    samples = await _forecast_samples_from_gateway(
        BarFakeGateway(), "SPY", days=10, now=NOW
    )
    artifact = ForecastEnsemble.fit(samples, NOW)
    payload = {
        "training_end": artifact.training_end.isoformat(),
        "feature_schema_hash": artifact.feature_schema_hash,
        "sample_count": artifact.sample_count,
        "weights": [str(weight) for weight in artifact.weights],
        "quantile_center": str(artifact.quantile_center),
        "quantile_scale": str(artifact.quantile_scale),
        "volatility_scale": str(artifact.volatility_scale),
        "regime_center": str(artifact.regime_center),
        "regime_scale": str(artifact.regime_scale),
        "artifact_hash": artifact.artifact_hash,
    }
    target = tmp_path / "forecast-SPY.json"
    target.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

    provider = _forecast_provider_from_file(str(target))

    assert provider.forecast_artifact_verified is True
    assert provider.artifact_hash == artifact.artifact_hash
