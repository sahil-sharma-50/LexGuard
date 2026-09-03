"""Evidence-contained catalyst deliberation with a deterministic VETO fallback."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from lexguard.adapters.openai_catalyst import CatalystInput, veto_assessment
from lexguard.domain.models import CatalystAssessment, MarketEvidence


class CatalystAssessor(Protocol):
    async def assess(self, input_data: CatalystInput) -> CatalystAssessment:
        """Assess only the supplied catalyst evidence."""


class DeliberationService:
    def __init__(self, client: CatalystAssessor) -> None:
        self.client = client

    async def deliberate(self, evidence: MarketEvidence) -> CatalystAssessment:
        try:
            latest = evidence.underlying_bars[-1]
            previous = evidence.underlying_bars[-2] if len(evidence.underlying_bars) > 1 else latest
            features = (
                ("last_close", str(latest.close)),
                ("last_return", str((latest.close / previous.close) - Decimal("1"))),
                ("range_fraction", str((latest.high - latest.low) / latest.close)),
                ("volume", str(latest.volume)),
            )
            input_data = CatalystInput(
                observed_at=evidence.observed_at,
                underlying=evidence.underlying,
                features=features,
                news=evidence.news,
            )
            assessment = await self.client.assess(input_data)
            allowed_ids = {item.evidence_id for item in evidence.news}
            if not set(assessment.evidence_ids).issubset(allowed_ids):
                return veto_assessment(evidence.observed_at, "unknown evidence citation")
            return assessment
        except Exception:  # noqa: BLE001 - deliberation cannot authorize a trade
            return veto_assessment(evidence.observed_at, "deliberation failed")
