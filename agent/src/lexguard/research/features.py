"""Point-in-time feature engineering for the remaining-session forecast."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from lexguard.domain.models import AllowedUnderlying, ImmutableModel, UnderlyingBar

FEATURE_SCHEMA_VERSION = "features.v1"
FEATURE_SCHEMA_HASH = hashlib.sha256(
    json.dumps(
        {
            "version": FEATURE_SCHEMA_VERSION,
            "fields": (
                "last_close",
                "last_return",
                "mean_return",
                "realized_volatility",
                "ewma_volatility",
                "trend",
                "range_fraction",
                "volume_zscore",
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


class FeatureVector(ImmutableModel):
    """Immutable features computed only from bars completed by ``as_of``."""

    symbol: AllowedUnderlying
    as_of: datetime
    sample_count: int
    last_close: Decimal
    last_return: Decimal
    mean_return: Decimal
    realized_volatility: Decimal
    ewma_volatility: Decimal
    trend: Decimal
    range_fraction: Decimal
    volume_zscore: Decimal
    schema_hash: str = FEATURE_SCHEMA_HASH


def build_features(bars: Sequence[UnderlyingBar], as_of: datetime) -> FeatureVector:
    """Build deterministic intraday features without using future rows."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    eligible = sorted(
        (bar for bar in bars if bar.timestamp <= as_of),
        key=lambda bar: bar.timestamp,
    )
    if len(eligible) < 2:
        raise ValueError("at least two completed bars are required")
    symbol = eligible[0].symbol
    if any(bar.symbol != symbol for bar in eligible):
        raise ValueError("feature bars must have one underlying symbol")

    closes = tuple(bar.close for bar in eligible)
    returns = tuple(
        (current / previous) - Decimal("1")
        for previous, current in zip(closes[:-1], closes[1:], strict=True)
    )
    mean_return = _mean(returns)
    realized_volatility = _std(returns, mean_return)
    ewma_variance = returns[0] ** 2
    alpha = Decimal("0.20")
    for value in returns[1:]:
        ewma_variance = alpha * (value**2) + (Decimal("1") - alpha) * ewma_variance
    ewma_volatility = ewma_variance.sqrt()
    volumes = tuple(Decimal(bar.volume) for bar in eligible)
    volume_mean = _mean(volumes)
    volume_std = _std(volumes, volume_mean)
    volume_zscore = Decimal("0") if volume_std == 0 else (volumes[-1] - volume_mean) / volume_std
    range_fraction = _mean(tuple((bar.high - bar.low) / bar.close for bar in eligible))

    return FeatureVector(
        symbol=symbol,
        as_of=as_of,
        sample_count=len(eligible),
        last_close=closes[-1],
        last_return=returns[-1],
        mean_return=mean_return,
        realized_volatility=realized_volatility,
        ewma_volatility=ewma_volatility,
        trend=(closes[-1] / closes[0]) - Decimal("1"),
        range_fraction=range_fraction,
        volume_zscore=volume_zscore,
    )


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _std(values: Sequence[Decimal], mean: Decimal) -> Decimal:
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(len(values))
    return variance.sqrt()
