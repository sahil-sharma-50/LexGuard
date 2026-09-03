"""Constrained OpenAI Responses adapter for catalyst classification only."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from lexguard.domain.models import (
    CatalystAssessment,
    ImmutableModel,
    NewsEvidence,
    Scenario,
)

MODEL_NAME: Literal["gpt-4o-mini"] = "gpt-4o-mini"
PROMPT_VERSION = "catalyst.v1"
SYSTEM_PROMPT = """You are the Lexguard catalyst advocate.
Classify only one scenario: BASE, VOL_UP, VOL_DOWN, LEFT_TAIL, RIGHT_TAIL, or VETO.
Use only the supplied timestamp, symbol, compact regime features, and Alpaca news evidence.
Cite only supplied evidence IDs. Do not select a symbol, expiration, strike, side, quantity,
limit price, risk limit, order, or broker action. Return only the requested structured output.
"""


class CatalystInput(ImmutableModel):
    observed_at: datetime
    underlying: str
    features: tuple[tuple[str, str], ...]
    news: tuple[NewsEvidence, ...]


class CatalystResponse(ImmutableModel):
    scenario: Scenario
    confidence: Decimal
    evidence_ids: tuple[str, ...]
    rationale: str

    @classmethod
    def validate_strict(cls, value: Any) -> CatalystResponse:
        response = cls.model_validate(value)
        if response.scenario not in {
            "BASE",
            "VOL_UP",
            "VOL_DOWN",
            "LEFT_TAIL",
            "RIGHT_TAIL",
            "VETO",
        }:
            raise ValueError("unknown catalyst scenario")
        if not Decimal("0") <= response.confidence <= Decimal("1"):
            raise ValueError("catalyst confidence must be between 0 and 1")
        if len(response.rationale) > 800:
            raise ValueError("catalyst rationale is too long")
        return response


@dataclass(frozen=True, slots=True)
class CatalystCallMetrics:
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None


class ResponsesParser(Protocol):
    async def parse(self, **kwargs: Any) -> Any:
        """Call the Responses structured-output parser."""


class OpenAIResponsesClient(Protocol):
    responses: ResponsesParser


class OpenAICatalystClient:
    """Use Responses structured outputs with no trading tools or order fields."""

    def __init__(
        self,
        client: OpenAIResponsesClient,
        *,
        model: str = MODEL_NAME,
        prompt_version: str = PROMPT_VERSION,
        timeout_seconds: float = 10.0,
    ) -> None:
        if model != MODEL_NAME:
            raise ValueError("the catalyst model is frozen to gpt-4o-mini")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._client = client
        self.model = model
        self.prompt_version = prompt_version
        self.timeout_seconds = timeout_seconds
        self.last_metrics: CatalystCallMetrics | None = None
        self.last_call_succeeded = False

    async def assess(self, input_data: CatalystInput) -> CatalystAssessment:
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self._client.responses.parse(
                    model=self.model,
                    instructions=SYSTEM_PROMPT,
                    input=_serialize_input(input_data),
                    text_format=CatalystResponse,
                    store=False,
                    max_output_tokens=400,
                ),
                timeout=self.timeout_seconds,
            )
            parsed = _parse_response(response)
            supplied_ids = {item.evidence_id for item in input_data.news}
            if any(evidence_id not in supplied_ids for evidence_id in parsed.evidence_ids):
                raise ValueError("model cited an unknown evidence ID")
            assessment = CatalystAssessment(
                scenario=parsed.scenario,
                confidence=parsed.confidence,
                evidence_ids=parsed.evidence_ids,
                rationale=parsed.rationale,
                model=MODEL_NAME,
                prompt_version=self.prompt_version,
                assessed_at=input_data.observed_at,
            )
            self._record_metrics(response, started)
            self.last_call_succeeded = True
            return assessment
        except Exception:  # noqa: BLE001 - every provider failure is a veto
            self._record_metrics(None, started)
            self.last_call_succeeded = False
            return veto_assessment(input_data.observed_at, "catalyst output unavailable or invalid")

    async def health_check(self) -> bool:
        """Verify the constrained structured-output boundary with a no-op input."""

        observed_at = datetime.now(UTC)
        assessment = await self.assess(
            CatalystInput(observed_at=observed_at, underlying="SPY", features=(), news=())
        )
        return (
            self.last_call_succeeded
            and assessment.model == MODEL_NAME
            and assessment.prompt_version == self.prompt_version
        )

    def _record_metrics(self, response: Any, started: float) -> None:
        usage = getattr(response, "usage", None)
        self.last_metrics = CatalystCallMetrics(
            model=self.model,
            prompt_version=self.prompt_version,
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )


def veto_assessment(observed_at: datetime, reason: str) -> CatalystAssessment:
    return CatalystAssessment(
        scenario="VETO",
        confidence=Decimal("0"),
        evidence_ids=(),
        rationale=f"VETO: {reason}"[:800],
        model=MODEL_NAME,
        prompt_version=PROMPT_VERSION,
        assessed_at=observed_at,
    )


def _serialize_input(input_data: CatalystInput) -> list[dict[str, str]]:
    payload = {
        "observed_at": input_data.observed_at.isoformat(),
        "symbol": input_data.underlying,
        "features": dict(input_data.features),
        "news": [
            {
                "evidence_id": item.evidence_id,
                "headline": item.headline,
                "published_at": item.published_at.isoformat(),
                "source": item.source,
                "url": item.url,
            }
            for item in input_data.news
        ],
    }
    return [{"role": "user", "content": json.dumps(payload, sort_keys=True)}]


def _parse_response(response: Any) -> CatalystResponse:
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        return CatalystResponse.validate_strict(parsed)
    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        raise ValueError("structured response did not contain parsed output")
    try:
        decoded = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError("structured response was not JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("structured response was not an object")
    return CatalystResponse.validate_strict(decoded)
