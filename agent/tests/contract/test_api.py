"""Read-only public API contract tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from lexguard.adapters.repository import CaseRepository
from lexguard.api.app import create_app
from lexguard.api.projections import RepositoryReadStore
from lexguard.api.schemas import (
    ApiEvent,
    CaseProjection,
    InMemoryReadStore,
    PerformanceProjection,
    ResearchProjection,
)

NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)
CASE_ID = UUID("44444444-4444-4444-4444-444444444444")


@pytest.fixture
def client() -> TestClient:
    store = InMemoryReadStore(
        environment="development",
        as_of=NOW,
        cases=(
            CaseProjection(
                case_id=CASE_ID,
                trading_date=date(2026, 8, 24),
                decision_window="10:05",
                state="REFUSED",
                underlying="SPY",
                reason_codes=("CATALYST_VETO",),
            ),
        ),
        performance=PerformanceProjection(
            environment="development",
            as_of=NOW,
            provenance="ledger",
            mode="DEVELOPMENT_PAPER",
            metrics={"net_return": "0"},
        ),
        research=ResearchProjection(
            environment="development",
            as_of=NOW,
            provenance="artifacts",
            gate="NOT_RUN",
            metrics={},
        ),
        events=(
            ApiEvent(id=1, event_type="REFUSED", occurred_at=NOW, payload={"reason": "veto"}),
            ApiEvent(id=2, event_type="HEARTBEAT", occurred_at=NOW, payload={}),
        ),
    )
    return TestClient(create_app(store))


@pytest.mark.parametrize(
    "path",
    ["/api/status", "/api/cases", "/api/performance", "/api/research/summary"],
)
def test_public_reads_are_json(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_status_projects_a_fresh_verified_heartbeat() -> None:
    repository = CaseRepository("sqlite://")
    repository.create_schema()
    repository.save_runtime_artifact(
        NOW.date(),
        "health_heartbeat",
        {
            "checked_at": NOW.isoformat(),
            "components": {
                "alpaca": "healthy",
                "scheduler": "healthy",
                "reconciliation": "healthy",
            },
        },
        now=NOW,
    )

    store = RepositoryReadStore(repository, now=lambda: NOW)
    payload = TestClient(create_app(store, repository=repository)).get("/api/status").json()

    assert {
        key: payload["components"][key]
        for key in ("alpaca", "scheduler", "reconciliation")
    } == {
        "alpaca": "healthy",
        "scheduler": "healthy",
        "reconciliation": "healthy",
    }
    assert payload["checked_at"] == NOW.isoformat().replace("+00:00", "Z")


def test_status_downgrades_a_stale_heartbeat() -> None:
    repository = CaseRepository("sqlite://")
    repository.create_schema()
    checked_at = NOW - timedelta(minutes=3)
    repository.save_runtime_artifact(
        checked_at.date(),
        "health_heartbeat",
        {
            "checked_at": checked_at.isoformat(),
            "components": {
                "alpaca": "healthy",
                "scheduler": "healthy",
                "reconciliation": "healthy",
            },
        },
        now=checked_at,
    )

    store = RepositoryReadStore(repository, now=lambda: NOW)
    payload = TestClient(create_app(store, repository=repository)).get("/api/status").json()

    assert payload["components"]["scheduler"] == "stale"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_no_public_trade_mutation(client: TestClient, method: str) -> None:
    response = getattr(client, method)("/api/cases")
    assert response.status_code in {404, 405}


def test_performance_is_explicitly_labeled_and_account_id_is_not_public(client: TestClient) -> None:
    payload = client.get("/api/performance").json()
    assert payload["environment"] == "development"
    assert payload["mode"] == "DEVELOPMENT_PAPER"
    assert payload["provenance"] == "ledger"
    assert "account_id" not in str(payload).lower()


def test_openapi_route_allowlist_is_reads_plus_stop_only_controls(
    client: TestClient,
) -> None:
    paths = client.app.openapi()["paths"]
    assert set(paths) == {
        "/api/status",
        "/api/cases",
        "/api/cases/{case_id}",
        "/api/performance",
        "/api/performance/history",
        "/api/research/summary",
        "/api/events",
        "/api/account",
        "/api/positions",
        "/api/orders",
        "/api/controls/pause",
        "/api/controls/resume",
        "/api/controls/emergency-stop",
        "/api/cases/{case_id}/veto",
    }
    # POST exists only on the stop-only operator controls; every projection
    # route stays GET-only and no route can submit a broker order.
    post_paths = {path for path, item in paths.items() if "post" in item}
    assert post_paths == {
        "/api/controls/pause",
        "/api/controls/resume",
        "/api/controls/emergency-stop",
        "/api/cases/{case_id}/veto",
    }
    assert all(set(item) <= {"get"} for path, item in paths.items() if path not in post_paths)
    assert all(set(item) == {"post"} for path, item in paths.items() if path in post_paths)
