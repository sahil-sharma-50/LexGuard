"""Fail-closed runtime readiness and deployment boundary contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from lexguard import cli
from lexguard.adapters.repository import Base, CaseRepository
from lexguard.api.app import create_app
from lexguard.research.features import FEATURE_SCHEMA_HASH
from lexguard.services.position_manager import Close, Hold, PositionManager
from lexguard.services.scheduler import Scheduler

NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)


def _forecast_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "training_end": "2026-08-20T20:00:00+00:00",
        "feature_schema_hash": FEATURE_SCHEMA_HASH,
        "sample_count": 10,
        "weights": ["0.40", "0.35", "0.25"],
        "quantile_center": "0.01",
        "quantile_scale": "0.02",
        "volatility_scale": "0.03",
        "regime_center": "0.01",
        "regime_scale": "0.02",
    }
    payload["artifact_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def test_forecast_loader_rejects_tampered_parameter_even_when_supplied_hash_is_unchanged(
    tmp_path: Path,
) -> None:
    payload = _forecast_payload()
    payload["quantile_center"] = "9.99"
    path = tmp_path / "forecast.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash"):
        cli._forecast_provider_from_file(str(path))


def _migrated_repository() -> CaseRepository:
    repository = CaseRepository("sqlite://")
    Base.metadata.create_all(repository.engine)
    with repository.engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version(version_num) VALUES ('0003_system_decision_window')")
        )
    return repository


def test_database_health_requires_alembic_head_and_required_columns() -> None:
    repository = _migrated_repository()
    assert repository.database_health() == "healthy"

    with repository.engine.begin() as connection:
        connection.execute(text("ALTER TABLE cases DROP COLUMN updated_at"))

    assert repository.database_health() == "migration_required"


def test_database_health_rejects_stale_alembic_revision() -> None:
    repository = _migrated_repository()
    with repository.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0000_stale'"))

    assert repository.database_health() == "migration_required"


def test_status_consumes_one_database_health_probe() -> None:
    repository = _migrated_repository()
    calls = 0
    original = repository.database_health

    def counted_health() -> str:
        nonlocal calls
        calls += 1
        return original()

    repository.database_health = counted_health  # type: ignore[method-assign]
    response = TestClient(create_app(repository=repository)).get("/api/status")

    assert response.status_code == 200
    assert calls == 1


def test_development_cors_allows_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEXGUARD_ALLOWED_ORIGIN", raising=False)
    client = TestClient(create_app(environment="development"))
    response = client.options(
        "/api/status",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_competition_cors_allows_exact_configured_origin_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = "https://competition.example"
    monkeypatch.setenv("LEXGUARD_ALLOWED_ORIGIN", configured)
    client = TestClient(create_app(environment="competition"))

    allowed = client.options(
        "/api/status",
        headers={
            "Origin": configured,
            "Access-Control-Request-Method": "GET",
        },
    )
    localhost = client.options(
        "/api/status",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == configured
    assert "access-control-allow-origin" not in localhost.headers


@pytest.mark.asyncio
async def test_scheduler_is_not_ready_until_async_preflight_passes() -> None:
    scheduler = Scheduler(
        calendar=object(),
        reconciliation=object(),
        repository=object(),
        case_service=object(),
        owner="readiness-test",
        readiness_check=lambda: _ready(),
    )

    assert scheduler.runtime_ready is False
    assert await scheduler.preflight() is True
    assert scheduler.runtime_blockers == ()


async def _ready() -> tuple[bool, tuple[str, ...]]:
    return True, ()


@pytest.mark.asyncio
async def test_real_position_snapshot_re_evaluates_edge_and_counts_consecutive_invalidations(
) -> None:
    class Broker:
        async def get_positions(self):  # type: ignore[no-untyped-def]
            from lexguard.adapters.alpaca_trading import BrokerPosition

            return (
                BrokerPosition(
                    symbol="SPY260825P00575000",
                    quantity=1,
                    side="long",
                    unrealized_pnl=Decimal("0"),
                ),
            )

    class Gateway:
        async def get_account_info(self):  # type: ignore[no-untyped-def]
            return type(
                "Account",
                (),
                {
                    "observed_at": datetime(2030, 1, 1, tzinfo=UTC),
                    "daily_pnl": Decimal("0"),
                    "competition_drawdown": Decimal("0"),
                },
            )()

    class Calendar:
        async def get_calendar(self, start, end):  # type: ignore[no-untyped-def]
            return ()

    from lexguard.cli import _BrokerPositionSnapshotProvider

    provider = _BrokerPositionSnapshotProvider(
        Broker(),
        Gateway(),
        Calendar(),
        type(
            "Settings",
            (),
            {"max_daily_loss": 1500, "max_competition_drawdown": 4000},
        )(),
        edge_evaluator=lambda positions, now: False,
    )
    manager = PositionManager(profit_target=Decimal("100"), stop_loss=Decimal("100"))

    first = await provider.snapshot(NOW)
    second = await provider.snapshot(NOW.replace(second=1))

    assert first.evidence.edge_valid is False
    assert first.evidence.evaluation_complete is True
    assert isinstance(await manager.evaluate(NOW, first.evidence), Hold)
    assert isinstance(await manager.evaluate(NOW.replace(second=1), second.evidence), Close)
