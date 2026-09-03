"""No-lookahead and deterministic feature-engineering tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from lexguard.domain.models import UnderlyingBar
from lexguard.research.features import build_features

AS_OF = datetime(2026, 8, 24, 14, 5, tzinfo=UTC)


def _bars() -> tuple[UnderlyingBar, ...]:
    closes = (Decimal("590"), Decimal("591"), Decimal("589"), Decimal("592"), Decimal("593"))
    result: list[UnderlyingBar] = []
    for index, close in enumerate(closes):
        timestamp = AS_OF - timedelta(minutes=(4 - index) * 5)
        result.append(
            UnderlyingBar(
                symbol="SPY",
                timestamp=timestamp,
                open=close - Decimal("0.50"),
                high=close + Decimal("0.50"),
                low=close - Decimal("0.50"),
                close=close,
                volume=1000 + index * 100,
            )
        )
    return tuple(result)


def test_features_ignore_rows_after_as_of() -> None:
    bars = _bars()
    future = UnderlyingBar(
        symbol="SPY",
        timestamp=AS_OF + timedelta(minutes=5),
        open=Decimal("593"),
        high=Decimal("700"),
        low=Decimal("592"),
        close=Decimal("699"),
        volume=999999,
    )

    baseline = build_features(bars, AS_OF)
    with_future = build_features((*bars, future), AS_OF)

    assert with_future == baseline
    assert baseline.as_of == AS_OF
    assert baseline.sample_count == 5


def test_features_are_stable_and_reject_insufficient_history() -> None:
    bars = _bars()
    assert build_features(bars, AS_OF) == build_features(tuple(reversed(bars)), AS_OF)
    with pytest.raises(ValueError, match="at least two"):
        build_features(bars[:1], AS_OF)


def test_features_require_timezone_aware_as_of() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_features(_bars(), datetime(2026, 8, 24, 14, 5))
