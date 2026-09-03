"""Transactional case-orchestration tests with fake external adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from lexguard.adapters.repository import Base, CaseRepository
from lexguard.domain.enums import DecisionWindow
from lexguard.domain.models import (
    AccountSnapshot,
    CandidateStructure,
    CatalystAssessment,
    ForecastDistribution,
    ForecastNode,
    MarketEvidence,
    NewsEvidence,
    OptionLeg,
    UnderlyingBar,
)
from lexguard.services.case_service import CaseOutcome, CaseService
from lexguard.services.judge import Judge

NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)


def _evidence() -> MarketEvidence:
    return MarketEvidence(
        case_id=UUID("55555555-5555-5555-5555-555555555555"),
        observed_at=NOW,
        decision_window="10:05",
        underlying="SPY",
        underlying_bars=(
            UnderlyingBar(
                symbol="SPY",
                timestamp=NOW,
                open=Decimal("590"),
                high=Decimal("591"),
                low=Decimal("589"),
                close=Decimal("590"),
                volume=1000,
            ),
        ),
        option_quotes=(),
        news=(
            NewsEvidence(
                evidence_id="n1",
                headline="SPY catalyst",
                published_at=NOW,
                source="fixture",
            ),
        ),
        account_snapshot=AccountSnapshot(
            observed_at=NOW,
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


def _distribution() -> ForecastDistribution:
    return ForecastDistribution(
        nodes=(
            ForecastNode(return_value=Decimal("-0.01"), probability=Decimal("0.5")),
            ForecastNode(return_value=Decimal("0.01"), probability=Decimal("0.5")),
        ),
        calibrated_at=NOW,
        training_end=datetime(2026, 8, 23, 20, tzinfo=UTC),
        artifact_hash="forecast",
    )


class Collector:
    def __init__(self, evidence: MarketEvidence) -> None:
        self.evidence = evidence

    async def collect(self, window: DecisionWindow, observed_at: datetime) -> MarketEvidence:
        return self.evidence


class StubDeliberation:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario

    async def deliberate(self, evidence: MarketEvidence) -> CatalystAssessment:
        return CatalystAssessment(
            scenario=self.scenario,
            confidence=Decimal("0.6"),
            evidence_ids=(),
            rationale="fixture",
            model="gpt-4o-mini",
            prompt_version="catalyst.v1",
            assessed_at=evidence.observed_at,
        )


class EmptyCandidates:
    def generate(
        self,
        evidence: MarketEvidence,
        distribution: ForecastDistribution,
        allowed_sides: Any,
    ):
        raise AssertionError("candidate generation must not run after a VETO")


class RecordingCandidates:
    def __init__(self, candidate: CandidateStructure) -> None:
        self.candidate = candidate
        self.distributions: list[ForecastDistribution] = []

    def generate(
        self,
        evidence: MarketEvidence,
        distribution: ForecastDistribution,
        allowed_sides: Any,
    ) -> tuple[CandidateStructure, ...]:
        self.distributions.append(distribution)
        return (self.candidate,)


def _candidate() -> CandidateStructure:
    expiration = datetime(2026, 8, 25, tzinfo=UTC).date()
    return CandidateStructure(
        candidate_id=UUID("66666666-6666-6666-6666-666666666666"),
        strategy="LONG_VOL",
        underlying="SPY",
        expiration=expiration,
        legs=(
            OptionLeg(
                symbol="SPY260825P00575000",
                underlying="SPY",
                expiration=expiration,
                strike=Decimal("575"),
                right="P",
                side="SELL",
            ),
            OptionLeg(
                symbol="SPY260825P00580000",
                underlying="SPY",
                expiration=expiration,
                strike=Decimal("580"),
                right="P",
                side="BUY",
            ),
            OptionLeg(
                symbol="SPY260825C00590000",
                underlying="SPY",
                expiration=expiration,
                strike=Decimal("590"),
                right="C",
                side="BUY",
            ),
            OptionLeg(
                symbol="SPY260825C00595000",
                underlying="SPY",
                expiration=expiration,
                strike=Decimal("595"),
                right="C",
                side="SELL",
            ),
        ),
        quantity=1,
        entry_limit=Decimal("1"),
        max_loss=Decimal("500"),
        modeled_friction=Decimal("2"),
        modeled_fees=Decimal("1"),
        robust_ev=Decimal("20"),
    )


@pytest.fixture
def repository() -> CaseRepository:
    repository = CaseRepository("sqlite://")
    Base.metadata.drop_all(repository.engine)
    repository.create_schema()
    return repository


@pytest.mark.asyncio
async def test_veto_persists_refusal_and_never_calls_broker(repository: CaseRepository) -> None:
    evidence = _evidence()
    system = CaseService(
        repository=repository,
        evidence_factory=lambda case_id: Collector(evidence),
        forecast_provider=lambda item: _distribution(),
        deliberation=StubDeliberation("VETO"),
        candidate_service=EmptyCandidates(),
        judge=Judge(),
        underlying="SPY",
    )

    outcome = await system.evaluate(DecisionWindow.MORNING, NOW)

    assert isinstance(outcome, CaseOutcome)
    assert outcome.refusal is not None
    assert outcome.refusal.reason_codes == ("CATALYST_VETO",)
    assert repository.get_case(outcome.case_id).state.value == "REFUSED"


@pytest.mark.asyncio
async def test_non_veto_scenario_is_applied_and_candidates_are_persisted(
    repository: CaseRepository,
) -> None:
    candidate_service = RecordingCandidates(_candidate())
    system = CaseService(
        repository=repository,
        evidence_factory=lambda case_id: Collector(_evidence()),
        forecast_provider=lambda item: _distribution(),
        deliberation=StubDeliberation("VOL_DOWN"),
        candidate_service=candidate_service,
        judge=Judge(),
        underlying="SPY",
    )

    outcome = await system.evaluate(DecisionWindow.MORNING, NOW)

    assert outcome.certificate is not None
    assert candidate_service.distributions
    assert candidate_service.distributions[0] != _distribution()
    record = repository.ledger_case(outcome.case_id)
    assert record is not None
    artifact = record.artifacts["candidate_structures"]
    assert artifact["scenario"] == "VOL_DOWN"
    assert artifact["candidates"] == [_candidate().model_dump(mode="json")]
