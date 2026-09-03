"""Stop-only operator controls and live broker projections."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from lexguard.adapters.alpaca_trading import (
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
)
from lexguard.adapters.repository import CaseRepository
from lexguard.api.app import create_app
from lexguard.cli import _entry_enabled_with, _operator_stop_active

NOW = datetime(2026, 9, 1, 14, 5, tzinfo=UTC)
TOKEN = "operator-secret"


class FakeBroker:
    async def get_account(self) -> BrokerAccount:
        return BrokerAccount(
            status="ACTIVE",
            equity=Decimal("100250"),
            last_equity=Decimal("100000"),
            daily_pnl=Decimal("250"),
            competition_drawdown=Decimal("0"),
            buying_power=Decimal("200000"),
            options_level=3,
            base_url="https://paper-api.alpaca.markets",
        )

    async def get_positions(self) -> tuple[BrokerPosition, ...]:
        return (
            BrokerPosition(
                symbol="SPY260904P00640000",
                quantity=1,
                side="long",
                unrealized_pnl=Decimal("12.50"),
            ),
        )

    async def get_orders(self) -> tuple[BrokerOrder, ...]:
        return (BrokerOrder(order_id="order-1", status="NEW", client_order_id="lexguard-x"),)


@pytest.fixture()
def repository() -> CaseRepository:
    repo = CaseRepository("sqlite://")
    repo.create_schema()
    return repo


@pytest.fixture()
def client(
    repository: CaseRepository, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setenv("LEXGUARD_OPERATOR_TOKEN", TOKEN)
    app = create_app(repository=repository, broker_factory=FakeBroker)
    return TestClient(app)


def test_broker_projections_are_redacted_reads(client: TestClient) -> None:
    account = client.get("/api/account").json()
    assert account["equity"] == "100250"
    assert account["paper_endpoint"] is True
    assert "api_key" not in str(account).lower()

    positions = client.get("/api/positions").json()["positions"]
    assert positions[0]["symbol"] == "SPY260904P00640000"

    orders = client.get("/api/orders").json()["orders"]
    assert orders[0]["order_id"] == "order-1"


def test_controls_require_the_operator_token(client: TestClient) -> None:
    assert client.post("/api/controls/pause").status_code == 401
    assert (
        client.post(
            "/api/controls/pause", headers={"X-Operator-Token": "wrong"}
        ).status_code
        == 401
    )


def test_controls_are_disabled_without_a_configured_token(
    repository: CaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LEXGUARD_OPERATOR_TOKEN", raising=False)
    unconfigured = TestClient(create_app(repository=repository, broker_factory=FakeBroker))
    response = unconfigured.post(
        "/api/controls/pause", headers={"X-Operator-Token": TOKEN}
    )
    assert response.status_code == 503


def test_pause_and_resume_flow_through_the_ledger_gate(
    client: TestClient, repository: CaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEXGUARD_ENTRY_ENABLED", "true")
    monkeypatch.setenv("LEXGUARD_ENTRY_STATE_PATH", "/nonexistent/entry-state.json")
    gate = _entry_enabled_with(repository)
    assert gate() is True

    response = client.post("/api/controls/pause", headers={"X-Operator-Token": TOKEN})
    assert response.status_code == 200
    assert gate() is False
    assert _operator_stop_active(repository) is False

    response = client.post("/api/controls/resume", headers={"X-Operator-Token": TOKEN})
    assert response.status_code == 200
    assert gate() is True


def test_emergency_stop_disables_entries_and_flags_forced_exit(
    client: TestClient, repository: CaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEXGUARD_ENTRY_ENABLED", "true")
    monkeypatch.setenv("LEXGUARD_ENTRY_STATE_PATH", "/nonexistent/entry-state.json")
    response = client.post(
        "/api/controls/emergency-stop", headers={"X-Operator-Token": TOKEN}
    )
    assert response.status_code == 200
    assert _entry_enabled_with(repository)() is False
    assert _operator_stop_active(repository) is True

    client.post("/api/controls/resume", headers={"X-Operator-Token": TOKEN})
    assert _operator_stop_active(repository) is False


def test_veto_requires_a_real_case_with_a_certificate(
    client: TestClient, repository: CaseRepository
) -> None:
    assert (
        client.post(
            f"/api/cases/{uuid4()}/veto", headers={"X-Operator-Token": TOKEN}
        ).status_code
        == 404
    )

    case = repository.create_scheduled(date(2026, 9, 1), "10:05", underlying="SPY", now=NOW)
    response = client.post(
        f"/api/cases/{case.case_id}/veto", headers={"X-Operator-Token": TOKEN}
    )
    assert response.status_code == 409

    repository.save_artifact(
        case.case_id, "trade_certificate", {"proposal_hash": "abc"}, created_at=NOW
    )
    response = client.post(
        f"/api/cases/{case.case_id}/veto", headers={"X-Operator-Token": TOKEN}
    )
    assert response.status_code == 200
    assert repository.operator_veto_exists(case.case_id) is True


def test_performance_history_returns_snapshot_points(
    client: TestClient, repository: CaseRepository
) -> None:
    repository.save_runtime_artifact(
        NOW.date(),
        "performance_snapshot",
        {"recorded_at": NOW.isoformat(), "metrics": {"equity": "100250"}},
        now=NOW,
    )
    points = client.get("/api/performance/history").json()["points"]
    assert points == [
        {
            "recorded_at": NOW.isoformat(),
            "equity": "100250",
            "daily_pnl": None,
            "competition_drawdown": None,
        }
    ]
