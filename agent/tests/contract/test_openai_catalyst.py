"""Contract tests for the constrained OpenAI catalyst advocate."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from lexguard.adapters.openai_catalyst import (
    CatalystInput,
    CatalystResponse,
    OpenAICatalystClient,
)
from lexguard.domain.models import NewsEvidence

OBSERVED = datetime(2026, 8, 24, 14, 5, tzinfo=UTC)


def _input() -> CatalystInput:
    return CatalystInput(
        observed_at=OBSERVED,
        underlying="SPY",
        features=(
            ("last_return", "0.004"),
            ("realized_volatility", "0.012"),
        ),
        news=(
            NewsEvidence(
                evidence_id="n1",
                headline="SPY volatility rises",
                published_at=OBSERVED,
                source="fixture",
                url="https://example.test/n1",
            ),
        ),
    )


class FakeResponse:
    def __init__(self, *, output_text: str | None = None, output_parsed: Any = None) -> None:
        self.output_text = output_text
        self.output_parsed = output_parsed


class FakeResponses:
    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.kwargs: dict[str, Any] = {}
        self.timeout = False

    async def parse(self, **kwargs: Any) -> FakeResponse:
        self.kwargs = kwargs
        if self.timeout:
            await asyncio.sleep(0.02)
        if isinstance(self.reply, str):
            return FakeResponse(output_text=self.reply)
        return FakeResponse(output_text=json.dumps(self.reply))


class FakeOpenAI:
    def __init__(self, reply: Any) -> None:
        self.responses = FakeResponses(reply)


def _valid_reply() -> dict[str, Any]:
    return {
        "scenario": "VOL_UP",
        "confidence": 0.72,
        "evidence_ids": ["n1"],
        "rationale": "The supplied headline is consistent with a higher-volatility scenario.",
    }


def test_catalyst_response_schema_uses_json_number_for_confidence() -> None:
    confidence_schema = CatalystResponse.model_json_schema()["properties"]["confidence"]

    assert confidence_schema["type"] == "number"
    assert "anyOf" not in confidence_schema


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        "{malformed",
        {"scenario": "VOL_UP", "confidence": 0.7, "evidence_ids": ["unknown"], "rationale": "x"},
        {"scenario": "BASE", "confidence": 0.7, "evidence_ids": [], "rationale": "x" * 801},
        {
            "scenario": "BASE",
            "confidence": 0.7,
            "evidence_ids": [],
            "rationale": "x",
            "order_instruction": "buy SPY calls",
        },
    ],
)
async def test_invalid_model_output_becomes_veto(reply: Any) -> None:
    client = FakeOpenAI(reply)
    assessment = await OpenAICatalystClient(client, timeout_seconds=0.1).assess(_input())

    assert assessment.scenario == "VETO"
    assert assessment.evidence_ids == ()
    assert assessment.confidence == 0


@pytest.mark.asyncio
async def test_valid_structured_reply_is_contained_and_parsed() -> None:
    client = FakeOpenAI(_valid_reply())
    assessment = await OpenAICatalystClient(client, timeout_seconds=0.1).assess(_input())

    assert assessment.scenario == "VOL_UP"
    assert assessment.evidence_ids == ("n1",)
    assert assessment.model == "gpt-4o-mini"
    assert client.responses.kwargs["model"] == "gpt-4o-mini"
    # gpt-4o-mini is not a reasoning model; the Responses API rejects `reasoning`.
    assert "reasoning" not in client.responses.kwargs
    serialized_input = json.dumps(client.responses.kwargs["input"])
    assert "place_option_order" not in serialized_input
    assert "order_instruction" not in serialized_input


@pytest.mark.asyncio
async def test_timeout_becomes_veto() -> None:
    client = FakeOpenAI(_valid_reply())
    client.responses.timeout = True
    assessment = await OpenAICatalystClient(client, timeout_seconds=0.001).assess(_input())

    assert assessment.scenario == "VETO"
