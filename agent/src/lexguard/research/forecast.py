"""Reproducible three-component forecast ensemble and scenario transforms."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from lexguard.domain.enums import Scenario
from lexguard.domain.models import ForecastDistribution, ForecastNode
from lexguard.research.features import FEATURE_SCHEMA_HASH, FeatureVector

_GRID = (
    Decimal("-2.5"),
    Decimal("-2.0"),
    Decimal("-1.5"),
    Decimal("-1.0"),
    Decimal("-0.5"),
    Decimal("0"),
    Decimal("0.5"),
    Decimal("1.0"),
    Decimal("1.5"),
    Decimal("2.0"),
    Decimal("2.5"),
)
_BASE_PROBABILITIES = (
    Decimal("0.03"),
    Decimal("0.05"),
    Decimal("0.08"),
    Decimal("0.12"),
    Decimal("0.15"),
    Decimal("0.14"),
    Decimal("0.15"),
    Decimal("0.12"),
    Decimal("0.08"),
    Decimal("0.05"),
    Decimal("0.03"),
)


@dataclass(frozen=True, slots=True)
class HistoricalSample:
    features: FeatureVector
    target_return: Decimal


type _SampleTuple = tuple[FeatureVector, Decimal]
type HistoryItem = HistoricalSample | _SampleTuple


@dataclass(frozen=True, slots=True)
class ForecastArtifact:
    training_end: datetime
    feature_schema_hash: str
    sample_count: int
    weights: tuple[Decimal, Decimal, Decimal]
    quantile_center: Decimal
    quantile_scale: Decimal
    volatility_scale: Decimal
    regime_center: Decimal
    regime_scale: Decimal
    artifact_hash: str


class ForecastEnsemble:
    """Quantile, EWMA/Student-t proxy, and regime-neighbor ensemble."""

    def __init__(self, artifact: ForecastArtifact) -> None:
        self.artifact = artifact

    @classmethod
    def fit(
        cls,
        history: Sequence[HistoryItem],
        training_end: datetime,
    ) -> ForecastArtifact:
        if training_end.tzinfo is None or training_end.utcoffset() is None:
            raise ValueError("training_end must be timezone-aware")
        samples = tuple(
            _coerce_sample(item)
            for item in history
            if _coerce_sample(item).features.as_of <= training_end
        )
        if not samples:
            raise ValueError("forecast history contains no observations before training_end")
        if any(sample.features.schema_hash != FEATURE_SCHEMA_HASH for sample in samples):
            raise ValueError("forecast history has an incompatible feature schema")

        targets = tuple(sample.target_return for sample in samples)
        quantile_center = _quantile(targets, Decimal("0.50"))
        quantile_scale = max(
            (_quantile(targets, Decimal("0.75")) - _quantile(targets, Decimal("0.25")))
            / Decimal("1.349"),
            Decimal("0.0001"),
        )
        volatility_scale = max(
            _mean(tuple(sample.features.ewma_volatility for sample in samples)), Decimal("0.0001")
        )
        regime_center = _mean(targets)
        regime_scale = max(_std(targets, regime_center), Decimal("0.0001"))
        weights = (Decimal("0.40"), Decimal("0.35"), Decimal("0.25"))
        artifact_payload = {
            "training_end": training_end.isoformat(),
            "feature_schema_hash": FEATURE_SCHEMA_HASH,
            "sample_count": len(samples),
            "weights": [str(weight) for weight in weights],
            "quantile_center": str(quantile_center),
            "quantile_scale": str(quantile_scale),
            "volatility_scale": str(volatility_scale),
            "regime_center": str(regime_center),
            "regime_scale": str(regime_scale),
        }
        artifact_hash = hashlib.sha256(
            json.dumps(artifact_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ForecastArtifact(
            training_end=training_end,
            feature_schema_hash=FEATURE_SCHEMA_HASH,
            sample_count=len(samples),
            weights=weights,
            quantile_center=quantile_center,
            quantile_scale=quantile_scale,
            volatility_scale=volatility_scale,
            regime_center=regime_center,
            regime_scale=regime_scale,
            artifact_hash=artifact_hash,
        )

    def predict(self, features: FeatureVector) -> ForecastDistribution:
        if features.schema_hash != self.artifact.feature_schema_hash:
            raise ValueError("feature schema does not match forecast artifact")
        quantile_mean = self.artifact.quantile_center + features.trend * Decimal("0.25")
        volatility_mean = features.mean_return
        regime_mean = self.artifact.regime_center
        weights = self.artifact.weights
        center = (
            weights[0] * quantile_mean + weights[1] * volatility_mean + weights[2] * regime_mean
        )
        scale = max(
            weights[0] * self.artifact.quantile_scale
            + weights[1] * max(features.ewma_volatility, self.artifact.volatility_scale)
            + weights[2] * self.artifact.regime_scale,
            Decimal("0.0001"),
        )
        nodes = tuple(
            ForecastNode(return_value=center + multiplier * scale, probability=probability)
            for multiplier, probability in zip(_GRID, _BASE_PROBABILITIES, strict=True)
        )
        return ForecastDistribution(
            nodes=nodes,
            calibrated_at=features.as_of,
            training_end=self.artifact.training_end,
            artifact_hash=self.artifact.artifact_hash,
        )


def apply_scenario(distribution: ForecastDistribution, scenario: Scenario) -> ForecastDistribution:
    """Apply the frozen, auditable scenario transformation."""

    if scenario in {Scenario.BASE, Scenario.VETO}:
        return distribution
    if scenario in {Scenario.VOL_UP, Scenario.VOL_DOWN}:
        factor = Decimal("1.10") if scenario == Scenario.VOL_UP else Decimal("0.90")
        mean = sum(
            (node.return_value * node.probability for node in distribution.nodes), Decimal("0")
        )
        nodes = tuple(
            ForecastNode(
                return_value=mean + (node.return_value - mean) * factor,
                probability=node.probability,
            )
            for node in distribution.nodes
        )
        return _replace_nodes(distribution, nodes)

    sign = Decimal("1.25")
    tail_nodes = tuple(
        ForecastNode(
            return_value=node.return_value,
            probability=node.probability
            * (
                sign
                if (
                    node.return_value < 0
                    if scenario == Scenario.LEFT_TAIL
                    else node.return_value > 0
                )
                else Decimal("1")
            ),
        )
        for node in distribution.nodes
    )
    return _replace_nodes(distribution, tail_nodes)


def _replace_nodes(
    distribution: ForecastDistribution, nodes: Sequence[ForecastNode]
) -> ForecastDistribution:
    total = sum((node.probability for node in nodes), Decimal("0"))
    normalized = tuple(
        ForecastNode(return_value=node.return_value, probability=node.probability / total)
        for node in nodes[:-1]
    )
    last_probability = Decimal("1") - sum((node.probability for node in normalized), Decimal("0"))
    return ForecastDistribution.model_validate(
        distribution.model_dump(mode="python")
        | {
            "nodes": normalized
            + (ForecastNode(return_value=nodes[-1].return_value, probability=last_probability),)
        }
    )


def _coerce_sample(item: HistoryItem) -> HistoricalSample:
    if isinstance(item, HistoricalSample):
        return item
    features, target = item
    return HistoricalSample(features=features, target_return=target)


def _quantile(values: Sequence[Decimal], probability: Decimal) -> Decimal:
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _std(values: Sequence[Decimal], mean: Decimal) -> Decimal:
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(len(values))
    return variance.sqrt()
