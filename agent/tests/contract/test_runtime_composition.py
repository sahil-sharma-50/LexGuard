"""Offline contract tests for the complete scheduler dependency graph."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from lexguard import cli
from lexguard.adapters.alpaca_mcp import AlpacaMcpGateway
from lexguard.adapters.alpaca_trading import BrokerAccount, BrokerClock
from lexguard.adapters.repository import Base, CaseRepository
from lexguard.services.case_service import CaseService


class ReadOnlyMcp:
    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        now = datetime(2026, 8, 24, 14, 10, tzinfo=UTC).isoformat()
        if name == "get_clock":
            return {
                "timestamp": now,
                "is_open": True,
                "next_open": now,
                "next_close": "2026-08-24T20:00:00Z",
            }
        if name == "get_account_info":
            return {
                "observed_at": now,
                "status": "ACTIVE",
                "equity": "100000",
                "buying_power": "100000",
                "daily_pnl": "0",
                "competition_drawdown": "0",
                "options_trading_level": 3,
                "opra_available": True,
            }
        if name == "get_option_chain":
            return {
                "feed": "opra",
                "snapshots": {
                    "SPY260825P00575000": {
                        "feed": "opra",
                        "latestQuote": {"bp": "1", "ap": "1.1", "t": now},
                    }
                },
            }
        raise AssertionError(f"unexpected MCP tool: {name}")


class Responses:
    async def parse(self, **kwargs: object) -> object:
        return SimpleNamespace(
            output_parsed={
                "scenario": "VETO",
                "confidence": "0",
                "evidence_ids": [],
                "rationale": "health check",
            },
            usage=None,
        )


class OpenAIStub:
    responses = Responses()


class BrokerStub:
    base_url = "https://paper-api.alpaca.markets"

    async def get_account(self) -> BrokerAccount:
        return BrokerAccount(
            status="ACTIVE",
            equity=Decimal("100000"),
            last_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            competition_drawdown=Decimal("0"),
            options_level=3,
            base_url=self.base_url,
        )

    async def get_positions(self) -> tuple[object, ...]:
        return ()

    async def get_orders(self) -> tuple[object, ...]:
        return ()

    async def get_clock(self) -> BrokerClock:
        return BrokerClock(timestamp=datetime(2026, 8, 24, 14, 10, tzinfo=UTC), is_open=True)


class VerifiedForecast:
    forecast_artifact_verified = True
    artifact_hash = "0" * 64

    def __call__(self, evidence):  # type: ignore[no-untyped-def]
        return SimpleNamespace()


def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "fake")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "fake")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("LEXGUARD_ENVIRONMENT", "development")


def test_scheduler_composition_wires_case_and_execution_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    repository = CaseRepository("sqlite://")
    Base.metadata.create_all(repository.engine)
    with repository.engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version(version_num) VALUES ('0003_system_decision_window')")
        )
    case = repository.create_scheduled(date(2026, 8, 24), "10:05", underlying="SPY")
    repository.save_artifact(
        case.case_id,
        "risk_state",
        {
            "daily_pnl": "0",
            "competition_drawdown": "0",
            "competition_peak_equity": "100000",
            "competition_counter": 0,
        },
    )
    scheduler = cli.build_scheduler(
        broker=BrokerStub(),
        repository=repository,
        mcp_client=ReadOnlyMcp(),
        openai_client=OpenAIStub(),
        forecast_provider=VerifiedForecast(),
    )

    assert scheduler.runtime_ready is False
    assert asyncio.run(scheduler.preflight()) is True
    assert scheduler.runtime_ready is True
    assert scheduler.runtime_blockers == ()
    assert isinstance(scheduler.case_service, cli._RotatingCaseEvaluator)
    assert set(scheduler.case_service.services) == {"10:05", "11:35", "13:05", "14:20"}
    assert all(
        isinstance(service, CaseService)
        for service in scheduler.case_service.services.values()
    )
    assert scheduler.execution_service is not None
    assert isinstance(scheduler.execution_service.quote_checker, AlpacaMcpGateway)
    assert scheduler.position_manager is not None
    assert scheduler.position_snapshot_provider is not None


def test_scheduler_composition_reports_missing_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    scheduler = cli.build_scheduler(broker=BrokerStub(), repository=CaseRepository("sqlite://"))

    assert scheduler.runtime_ready is False
    assert "MCP_RUNTIME_UNCONFIGURED" in scheduler.runtime_blockers
    assert "OPENAI_RUNTIME_UNCONFIGURED" in scheduler.runtime_blockers
    assert "FORECAST_RUNTIME_UNCONFIGURED" in scheduler.runtime_blockers


def test_scheduler_preflight_rejects_throwing_boundaries_and_missing_risk_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)

    class ThrowingMcp(ReadOnlyMcp):
        async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
            raise AssertionError("MCP boundary failed")

    class ThrowingResponses:
        async def parse(self, **kwargs: object) -> object:
            raise AssertionError("OpenAI boundary failed")

    repository = CaseRepository("sqlite://")
    Base.metadata.create_all(repository.engine)
    with repository.engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version(version_num) VALUES ('0003_system_decision_window')")
        )
    scheduler = cli.build_scheduler(
        broker=BrokerStub(),
        repository=repository,
        mcp_client=ThrowingMcp(),
        openai_client=type("OpenAI", (), {"responses": ThrowingResponses()})(),
        forecast_provider=VerifiedForecast(),
    )

    assert asyncio.run(scheduler.preflight()) is False
    assert "MCP_PREFLIGHT_FAILURE" in scheduler.runtime_blockers
    assert "OPENAI_PREFLIGHT_FAILURE" in scheduler.runtime_blockers
    assert "RISK_STATE_UNAVAILABLE" in scheduler.runtime_blockers
