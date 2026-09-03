"""Durable public read projections derived from the append-only ledger."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from lexguard.adapters.repository import Base, CaseRepository
from lexguard.api.app import create_app
from lexguard.domain.state_machine import CaseEventType

NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)


def test_default_api_store_projects_sanitized_ledger_artifacts_and_events() -> None:
    """Removing the projection layer must make this public ledger replay fail."""

    database_url = "sqlite://"
    repository = CaseRepository(database_url)
    Base.metadata.drop_all(repository.engine)
    repository.create_schema()
    case = repository.create_scheduled(date(2026, 8, 24), "10:05", underlying="SPY", now=NOW)
    repository.save_artifact(
        case.case_id,
        "market_evidence",
        {
            "source": "alpaca_mcp",
            "broker_id": "SENTINEL_BROKER_ID_DO_NOT_RENDER",
            "private_export": "SENTINEL_PRIVATE_EXPORT_DO_NOT_RENDER",
            "account_snapshot": {
                "account_id": "private-account",
                "api_key": "SENTINEL_API_KEY_DO_NOT_RENDER",
                "private_account": "SENTINEL_PRIVATE_ACCOUNT_DO_NOT_RENDER",
                "broker_id": "SENTINEL_BROKER_ID_DO_NOT_RENDER",
                "private_export": "SENTINEL_PRIVATE_EXPORT_DO_NOT_RENDER",
            },
        },
        content_hash="market-proof",
        created_at=NOW,
    )
    repository.save_artifact(
        case.case_id,
        "performance_snapshot",
        {
            "provenance": "reconciled paper ledger",
            "mode": "DEVELOPMENT_PAPER",
            "metrics": {"realized_pnl": "12.50", "account_id": "private-account"},
        },
        created_at=NOW,
    )
    repository.save_artifact(
        case.case_id,
        "research_summary",
        {
            "gate": "NOT_RUN",
            "provenance": "sealed research contract",
            "metrics": {"dataset": "frozen", "access_token": "private-token"},
        },
        created_at=NOW,
    )
    for event in (CaseEventType.OBSERVED, CaseEventType.FORECASTED, CaseEventType.ARGUED):
        repository.append_event(
            case.case_id,
            event,
            {
                "account_id": "private-account",
                "broker_id": "SENTINEL_BROKER_ID_DO_NOT_RENDER",
                "private_export": "SENTINEL_PRIVATE_EXPORT_DO_NOT_RENDER",
            },
            occurred_at=NOW,
        )
    repository.append_event(
        case.case_id,
        CaseEventType.REFUSED,
        {"reason_codes": ["CATALYST_VETO"], "account_id": "private-account"},
        occurred_at=NOW,
    )

    client = TestClient(create_app(database_url=database_url, repository=repository))

    listed = client.get("/api/cases").json()
    detail = client.get(f"/api/cases/{case.case_id}").json()
    performance = client.get("/api/performance").json()
    research = client.get("/api/research/summary").json()
    event_stream = client.get("/api/events", headers={"Last-Event-ID": "1"}).text

    assert listed["items"][0]["case_id"] == str(case.case_id)
    assert detail["state"] == "REFUSED"
    assert detail["reason_codes"] == ["CATALYST_VETO"]
    assert detail["artifacts"]["market_evidence"]["content_hash"] == "market-proof"
    assert performance["metrics"]["realized_pnl"] == "12.50"
    assert research["gate"] == "NOT_RUN"
    assert "private-account" not in str((detail, performance, research, event_stream))
    assert "private-key" not in str((detail, performance, research, event_stream))
    assert "private-token" not in str((detail, performance, research, event_stream))
    for sentinel in (
        "SENTINEL_API_KEY_DO_NOT_RENDER",
        "SENTINEL_PRIVATE_ACCOUNT_DO_NOT_RENDER",
        "SENTINEL_BROKER_ID_DO_NOT_RENDER",
        "SENTINEL_PRIVATE_EXPORT_DO_NOT_RENDER",
    ):
        assert sentinel not in str((listed, detail, performance, research, event_stream))
    assert "id: 1" not in event_stream
    assert "id: 2" in event_stream
    assert event_stream.index("id: 2") < event_stream.index("id: 3") < event_stream.index("id: 4")
