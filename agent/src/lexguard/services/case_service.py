"""Transactional case lifecycle through certification, without order submission."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from lexguard.adapters.repository import CaseRead, CaseRepository
from lexguard.domain.enums import DecisionWindow, Scenario
from lexguard.domain.models import (
    AllowedUnderlying,
    CandidateStructure,
    CatalystAssessment,
    ForecastDistribution,
    MarketEvidence,
    RefusalRecord,
    TradeCertificate,
)
from lexguard.domain.policy import RiskContext
from lexguard.domain.state_machine import CaseEventType, CaseState
from lexguard.research.forecast import apply_scenario
from lexguard.services.candidates import BOTH
from lexguard.services.deliberation import DeliberationService
from lexguard.services.judge import Judge

_NEW_YORK = ZoneInfo("America/New_York")


class EvidenceCollector(Protocol):
    async def collect(self, window: DecisionWindow, observed_at: datetime) -> MarketEvidence:
        """Collect one evidence snapshot."""


class CandidateGenerator(Protocol):
    def generate(
        self,
        evidence: MarketEvidence,
        distribution: ForecastDistribution,
        allowed_sides: Iterable[str] | str,
    ) -> tuple[CandidateStructure, ...]:
        """Generate bounded candidates."""


class ForecastProvider(Protocol):
    def __call__(self, evidence: MarketEvidence) -> ForecastDistribution:
        """Produce a forecast from point-in-time evidence."""


class EvidenceFactory(Protocol):
    def __call__(self, case_id: UUID) -> EvidenceCollector:
        """Create an evidence collector bound to a case ID."""


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    case_id: UUID
    state: CaseState
    certificate: TradeCertificate | None = None
    refusal: RefusalRecord | None = None


class CaseService:
    """Persist each decision stage before progressing to the next stage."""

    def __init__(
        self,
        *,
        repository: CaseRepository,
        evidence_factory: EvidenceFactory,
        forecast_provider: ForecastProvider,
        deliberation: DeliberationService,
        candidate_service: CandidateGenerator,
        judge: Judge,
        underlying: AllowedUnderlying,
        allowed_sides: Iterable[str] | str = BOTH,
        owner: str = "case-service",
    ) -> None:
        self.repository = repository
        self.evidence_factory = evidence_factory
        self.forecast_provider = forecast_provider
        self.deliberation = deliberation
        self.candidate_service = candidate_service
        self.judge = judge
        self.underlying = underlying
        self.allowed_sides = allowed_sides
        self.owner = owner

    async def evaluate(self, window: DecisionWindow, now: datetime) -> CaseOutcome:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("case evaluation time must be timezone-aware")
        trading_date = now.astimezone(_NEW_YORK).date()
        case = self.repository.create_scheduled(
            trading_date,
            window.value,
            underlying=self.underlying,
            now=now,
        )
        try:
            evidence = await self.evidence_factory(case.case_id).collect(window, now)
            self.repository.save_artifact(
                case.case_id,
                "market_evidence",
                evidence.model_dump(mode="json"),
                content_hash=evidence.content_hash,
                created_at=now,
            )
            case = self.repository.append_event(
                case.case_id,
                CaseEventType.OBSERVED,
                {"content_hash": evidence.content_hash},
                occurred_at=now,
            )

            distribution = self.forecast_provider(evidence)
            self.repository.save_artifact(
                case.case_id,
                "forecast_distribution",
                distribution.model_dump(mode="json"),
                content_hash=distribution.artifact_hash,
                created_at=now,
            )
            case = self.repository.append_event(
                case.case_id,
                CaseEventType.FORECASTED,
                {"artifact_hash": distribution.artifact_hash},
                occurred_at=now,
            )

            assessment = CatalystAssessment.model_validate(
                await self.deliberation.deliberate(evidence)
            )
            self.repository.save_artifact(
                case.case_id,
                "catalyst_assessment",
                assessment.model_dump(mode="json"),
                created_at=now,
            )
            case = self.repository.append_event(
                case.case_id,
                CaseEventType.ARGUED,
                {"scenario": assessment.scenario},
                occurred_at=now,
            )

            scenario = Scenario(assessment.scenario)
            candidates = (
                ()
                if scenario == Scenario.VETO
                else self.candidate_service.generate(
                    evidence,
                    apply_scenario(distribution, scenario),
                    self.allowed_sides,
                )
            )
            self.repository.save_artifact(
                case.case_id,
                "candidate_structures",
                {
                    "scenario": scenario.value,
                    "forecast_artifact_hash": distribution.artifact_hash,
                    "candidates": [
                        candidate.model_dump(mode="json") for candidate in candidates
                    ],
                },
                created_at=now,
            )
            judgment = self.judge.certify(
                case,
                candidates,
                self._risk_context(evidence, window, now),
                catalyst=assessment,
            )
            if isinstance(judgment, TradeCertificate):
                self.repository.save_artifact(
                    case.case_id,
                    "trade_certificate",
                    judgment.model_dump(mode="json"),
                    content_hash=judgment.proposal_hash,
                    created_at=now,
                )
                self.repository.append_event(
                    case.case_id,
                    CaseEventType.CERTIFIED,
                    {"proposal_hash": judgment.proposal_hash},
                    occurred_at=now,
                )
                return CaseOutcome(case.case_id, CaseState.CERTIFIED, certificate=judgment)

            self.repository.save_artifact(
                case.case_id,
                "refusal_record",
                judgment.model_dump(mode="json"),
                created_at=now,
            )
            self.repository.append_event(
                case.case_id,
                CaseEventType.REFUSED,
                {"reason_codes": judgment.reason_codes},
                occurred_at=now,
            )
            return CaseOutcome(case.case_id, CaseState.REFUSED, refusal=judgment)
        except Exception:
            return self._halt(case, now, "CASE_DEPENDENCY_FAILURE")

    def _risk_context(
        self, evidence: MarketEvidence, window: DecisionWindow, now: datetime
    ) -> RiskContext:
        account = evidence.account_snapshot
        daily_state = self.repository.daily_entry_state(now.astimezone(_NEW_YORK).date())
        return RiskContext(
            now=now,
            decision_window=window.value,
            evidence_observed_at=evidence.observed_at,
            daily_pnl=account.daily_pnl,
            competition_drawdown=account.competition_drawdown,
            account_equity=account.equity,
            entries_today=daily_state.entries_today,
            traded_symbols_today=daily_state.traded_symbols_today,
            open_structure_count=account.open_structure_count,
            open_order_count=account.open_order_count,
            open_position_count=account.open_position_count,
            account_status=account.status,
            options_level=account.options_level,
            opra_available=account.opra_available,
            base_url=account.base_url,
            entry_attempt=False,
        )

    def _halt(self, case: CaseRead, now: datetime, reason: str) -> CaseOutcome:
        refusal = RefusalRecord(
            case_id=case.case_id,
            refused_at=now,
            reason_codes=(reason,),
            details={},
        )
        self.repository.save_artifact(
            case.case_id,
            "halt_record",
            refusal.model_dump(mode="json"),
            created_at=now,
        )
        self.repository.append_event(
            case.case_id,
            CaseEventType.HALTED,
            {"reason": reason},
            occurred_at=now,
        )
        return CaseOutcome(case.case_id, CaseState.HALTED, refusal=refusal)
