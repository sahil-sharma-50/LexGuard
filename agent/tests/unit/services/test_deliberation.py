"""Deliberation service containment and fail-closed tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from lexguard.domain.models import (
    AccountSnapshot,
    MarketEvidence,
    NewsEvidence,
    UnderlyingBar,
)
from lexguard.services.deliberation import DeliberationService

OBSERVED = datetime(2026, 8, 24, 14, 5, tzinfo=UTC)


def _evidence() -> MarketEvidence:
    return MarketEvidence(
        case_id=UUID("33333333-3333-3333-3333-333333333333"),
        observed_at=OBSERVED,
        decision_window="10:05",
        underlying="SPY",
        underlying_bars=(
            UnderlyingBar(
                symbol="SPY",
                timestamp=OBSERVED,
                open=Decimal("590"),
                high=Decimal("591"),
                low=Decimal("589"),
                close=Decimal("590.50"),
                volume=1000,
            ),
        ),
        option_quotes=(),
        news=(
            NewsEvidence(
                evidence_id="n1",
                headline="SPY volatility rises",
                published_at=OBSERVED,
                source="fixture",
            ),
        ),
        account_snapshot=AccountSnapshot(
            observed_at=OBSERVED,
            status="ACTIVE",
            equity=Decimal("100000"),
            buying_power=Decimal("100000"),
            daily_pnl=Decimal("0"),
            competition_drawdown=Decimal("0"),
            options_level=3,
            opra_available=True,
            base_url="https://paper-api.alpaca.markets",
        ),
        source="alpaca_mcp",
        content_hash="evidence",
    )


class StubCatalyst:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.input: Any = None

    async def assess(self, input_data: Any) -> Any:
        self.input = input_data
        if self.error is not None:
            raise self.error
        return self.response


def _assessment(evidence_id: str = "n1") -> Any:
    from lexguard.domain.models import CatalystAssessment

    return CatalystAssessment(
        scenario="BASE",
        confidence=Decimal("0.6"),
        evidence_ids=(evidence_id,),
        rationale="The evidence supports a base scenario.",
        model="gpt-4o-mini",
        prompt_version="catalyst.v1",
        assessed_at=OBSERVED,
    )


@pytest.mark.asyncio
async def test_deliberation_passes_only_sanitized_evidence() -> None:
    stub = StubCatalyst(_assessment())
    result = await DeliberationService(stub).deliberate(_evidence())

    assert result.scenario == "BASE"
    assert stub.input.news[0].evidence_id == "n1"
    assert not hasattr(stub.input, "order_instruction")


@pytest.mark.asyncio
async def test_unknown_evidence_id_becomes_veto() -> None:
    result = await DeliberationService(StubCatalyst(_assessment("unknown"))).deliberate(_evidence())

    assert result.scenario == "VETO"
    assert result.evidence_ids == ()


@pytest.mark.asyncio
async def test_deliberation_failure_becomes_veto() -> None:
    result = await DeliberationService(StubCatalyst(error=TimeoutError())).deliberate(_evidence())

    assert result.scenario == "VETO"
    assert result.evidence_ids == ()
