"""Credential-gated OpenAI schema smoke test with no broker capabilities."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from lexguard.adapters.openai_catalyst import CatalystInput, OpenAICatalystClient

_enabled = (
    bool(os.environ.get("OPENAI_API_KEY")) and os.environ.get("LEXGUARD_RUN_OPENAI_SMOKE") == "1"
)

pytestmark = [
    pytest.mark.openai_smoke,
    pytest.mark.skipif(
        not _enabled,
        reason="set LEXGUARD_RUN_OPENAI_SMOKE=1 with an OpenAI API key to run",
    ),
]


@pytest.mark.asyncio
async def test_openai_structured_output_smoke() -> None:
    from openai import AsyncOpenAI

    client = OpenAICatalystClient(AsyncOpenAI(), timeout_seconds=20)
    assessment = await client.assess(
        CatalystInput(
            observed_at=datetime(2026, 8, 24, 14, 5, tzinfo=UTC),
            underlying="SPY",
            features=(("last_return", "0.001"), ("realized_volatility", "0.01")),
            news=(),
        )
    )

    assert assessment.model == "gpt-4o-mini"
    assert assessment.scenario in {
        "BASE",
        "VOL_UP",
        "VOL_DOWN",
        "LEFT_TAIL",
        "RIGHT_TAIL",
        "VETO",
    }
