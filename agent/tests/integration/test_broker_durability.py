"""Durability contracts for broker lifecycle, restart reconciliation, and exports."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from typer.testing import CliRunner

from lexguard import cli
from lexguard.adapters.alpaca_trading import (
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    PaperBroker,
)
from lexguard.adapters.repository import Base, CaseRepository, entry_client_order_id
from lexguard.domain.models import ExecutionRecord
from lexguard.domain.state_machine import CaseEventType, CaseState
from lexguard.services.reconciliation import ReconciliationService

NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)
CASE_ID = UUID("44444444-4444-4444-4444-444444444444")
CERTIFICATE_ID = UUID("22222222-2222-2222-2222-222222222222")


def _repository() -> CaseRepository:
    repository = CaseRepository("sqlite://")
    Base.metadata.drop_all(repository.engine)
    repository.create_schema()
    case = repository.create_scheduled(
        date(2026, 8, 24), "10:05", underlying="SPY", case_id=CASE_ID, now=NOW
    )
    for event in (
        CaseEventType.OBSERVED,
        CaseEventType.FORECASTED,
        CaseEventType.ARGUED,
        CaseEventType.CERTIFIED,
    ):
        case = repository.append_event(case.case_id, event, occurred_at=NOW)
    return repository


def _record(state: str, order_ids: tuple[str, ...] = ("order-1",)) -> ExecutionRecord:
    return ExecutionRecord(
        case_id=CASE_ID,
        certificate_id=CERTIFICATE_ID,
        alpaca_order_ids=order_ids,
        state=state,  # type: ignore[arg-type]
        submitted_at=NOW,
        updated_at=NOW,
        filled_quantity=1 if state == "FILLED" else 0,
        average_fill_price=Decimal("1.20") if state == "FILLED" else None,
    )


def test_record_execution_persists_outcome_and_legal_case_transitions() -> None:
    repository = _repository()

    submitted = repository.record_execution(_record("SUBMITTED"))
    replaced = repository.record_execution(_record("REPLACED", ("order-1", "order-2")))
    filled = repository.record_execution(_record("FILLED", ("order-1", "order-2")))

    assert submitted.state is CaseState.SUBMITTED
    assert replaced.state is CaseState.SUBMITTED
    assert filled.state is CaseState.MANAGING
    ledger = repository.ledger_case(CASE_ID)
    assert ledger is not None
    assert ledger.artifacts["execution_record"]["state"] == "FILLED"


def test_fallback_filled_chain_does_not_mark_every_order_filled() -> None:
    repository = _repository()

    repository.record_execution(_record("FILLED", ("old-order", "replacement-order")))

    rows = repository.order_events_for_cases((CASE_ID,))
    statuses = [str(row.payload["status"]) for row in rows]
    assert statuses == ["UNKNOWN", "UNKNOWN"]


def test_replaced_order_is_not_expected_as_active() -> None:
    repository = _repository()

    repository.record_execution(_record("REPLACED"))

    assert repository.expected_broker_state() == ((), ())


def test_legacy_null_order_metadata_is_read_as_entry_safely() -> None:
    repository = _repository()
    legacy = SimpleNamespace(
        payload_json={"status": "FILLED", "filled_quantity": 1},
        role=None,
        case_id=str(CASE_ID),
    )
    from sqlalchemy.orm import Session

    with Session(repository.engine) as session:
        assert CaseRepository._expected_position_state(session, {"legacy": legacy}) == {}


def test_restart_reconciliation_uses_durable_order_expectations() -> None:
    repository = _repository()
    repository.record_execution(_record("SUBMITTED"))

    class Broker:
        async def get_orders(self) -> tuple[BrokerOrder, ...]:
            return (BrokerOrder(order_id="order-1", status="NEW"),)

        async def get_positions(self) -> tuple[BrokerPosition, ...]:
            return ()

    report = __import__("asyncio").run(
        ReconciliationService(
            Broker(), expected_state_provider=repository.expected_broker_state
        ).reconcile()
    )

    assert report.state == "CONSISTENT"
    assert report.ledger_order_ids == ("order-1",)


def test_daily_report_reads_ledger_artifact_when_present(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Broker:
        async def get_account(self) -> BrokerAccount:
            return BrokerAccount(
                status="ACTIVE",
                equity=Decimal("100000"),
                base_url="https://paper-api.alpaca.markets",
            )

        async def get_orders(self) -> tuple[BrokerOrder, ...]:
            return ()

        async def get_positions(self) -> tuple[BrokerPosition, ...]:
            return ()

    class Repository:
        def database_health(self) -> str:
            return "healthy"

        def latest_artifact(self, artifact_type: str):  # type: ignore[no-untyped-def]
            assert artifact_type == "performance_snapshot"
            return (
                {"metrics": {"daily_pnl": "2.50"}, "provenance": "ledger-performance"},
                "artifact-hash",
                NOW,
            )

        def expected_broker_state(self):  # type: ignore[no-untyped-def]
            return (), ()

    monkeypatch.setattr(cli, "build_broker", lambda: Broker())
    monkeypatch.setattr(cli, "CaseRepository", lambda _: Repository())
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    result = CliRunner().invoke(cli.app, ["daily-report"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ledger"]["metrics"]["daily_pnl"] == "2.50"
    assert payload["provenance"] == "alpaca_broker_reconciled"


def test_export_evidence_is_ledger_backed_and_redacted(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    class Repository:
        def list_ledger_cases(self, offset: int, limit: int):  # type: ignore[no-untyped-def]
            from lexguard.adapters.repository import LedgerCaseRecord

            return (
                (
                    LedgerCaseRecord(
                        case_id=CASE_ID,
                        trading_date=date(2026, 8, 24),
                        decision_window="10:05",
                        state="MANAGING",
                        underlying="SPY",
                        updated_at=NOW,
                        environment="development",
                        artifacts={"execution_record": {"api_key": "secret", "state": "FILLED"}},
                    ),
                ),
                False,
            )

        def order_events_for_cases(self, case_ids):  # type: ignore[no-untyped-def]
            return ()

    monkeypatch.setattr(cli, "CaseRepository", lambda _: Repository())
    output = tmp_path / "evidence.json"
    result = CliRunner().invoke(cli.app, ["export-evidence", "--output", str(output)])

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["cases"][0]["artifacts"]["execution_record"]["api_key"] == "[REDACTED]"
    assert payload["cases"][0]["state"] == "MANAGING"


def test_export_evidence_excludes_cases_without_exact_environment(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    class Repository:
        def list_ledger_cases(self, offset: int, limit: int):  # type: ignore[no-untyped-def]
            from lexguard.adapters.repository import LedgerCaseRecord

            return (
                (
                    LedgerCaseRecord(
                        case_id=CASE_ID,
                        trading_date=date(2026, 8, 24),
                        decision_window="10:05",
                        state="MANAGING",
                        underlying="SPY",
                        updated_at=NOW,
                        environment=None,
                        artifacts={},
                    ),
                ),
                False,
            )

        def order_events_for_cases(self, case_ids):  # type: ignore[no-untyped-def]
            return ()

    monkeypatch.setattr(cli, "CaseRepository", lambda _: Repository())
    output = tmp_path / "evidence.json"
    result = CliRunner().invoke(cli.app, ["export-evidence", "--output", str(output)])

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["cases"] == []
    assert payload["provenance"] == "no_reconciled_ledger_artifact"


def test_verify_account_competition_requires_supported_options_level(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Broker:
        async def get_account(self) -> BrokerAccount:
            return BrokerAccount(
                status="ACTIVE",
                equity=Decimal("100000"),
                options_level=None,
                base_url="https://paper-api.alpaca.markets",
            )

        async def get_orders(self) -> tuple[BrokerOrder, ...]:
            return ()

        async def get_positions(self) -> tuple[BrokerPosition, ...]:
            return ()

    monkeypatch.setattr(cli, "build_broker", lambda: Broker())
    result = CliRunner().invoke(cli.app, ["verify-account", "--competition"])
    assert result.exit_code != 0
    assert "options" in result.output.lower()


def test_export_evidence_redacts_unavailable_exception_to_stable_code(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    class Repository:
        def list_ledger_cases(self, offset: int, limit: int):  # type: ignore[no-untyped-def]
            raise RuntimeError("secret credential path should not escape")

    monkeypatch.setattr(cli, "CaseRepository", lambda _: Repository())
    output = tmp_path / "evidence.json"
    result = CliRunner().invoke(cli.app, ["export-evidence", "--output", str(output)])

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["unavailable_reason"] == "LEDGER_UNAVAILABLE"
    assert "secret" not in output.read_text(encoding="utf-8")


def test_reconciliation_compares_signed_position_quantity_and_side() -> None:
    class Broker:
        async def get_orders(self) -> tuple[BrokerOrder, ...]:
            return ()

        async def get_positions(self) -> tuple[BrokerPosition, ...]:
            return (BrokerPosition(symbol="SPY260825P00580000", quantity=1, side="short"),)

    import asyncio

    report = asyncio.run(
        ReconciliationService(
            Broker(), expected_state_provider=lambda: ((), {"SPY260825P00580000": 2})
        ).reconcile()
    )
    assert report.state == "RECONCILE_REQUIRED"
    assert "POSITION_QUANTITY_MISMATCH" in report.reason_codes
    assert "POSITION_SIDE_MISMATCH" in report.reason_codes


def test_order_observations_are_append_only_across_repeated_lifecycle_updates() -> None:
    repository = _repository()
    repository.record_execution(_record("SUBMITTED"))
    repository.record_execution(_record("SUBMITTED"))

    rows = repository.order_events_for_cases((CASE_ID,))
    assert len(rows) == 2


def test_normalized_orders_preserve_deterministic_client_id_for_restart_lookup() -> None:
    order = PaperBroker._normalize_order(
        SimpleNamespace(
            id="order-1",
            status="new",
            filled_qty="0",
            filled_avg_price=None,
            client_order_id="lexguard-entry-certificate",
        )
    )

    assert order.client_order_id == "lexguard-entry-certificate"


def test_entry_client_id_is_stable_and_within_alpaca_limit() -> None:
    first = entry_client_order_id(CERTIFICATE_ID)
    second = entry_client_order_id(CERTIFICATE_ID)

    assert first == second
    assert len(first) <= 48


def test_verify_account_reports_partial_without_historical_activity_proof(monkeypatch) -> None:
    class Broker:
        async def get_account(self) -> BrokerAccount:
            return BrokerAccount(
                status="ACTIVE",
                equity=Decimal("100000"),
                options_level=3,
                opra_available=True,
                base_url="https://paper-api.alpaca.markets",
            )

        async def get_orders(self) -> tuple[BrokerOrder, ...]:
            return ()

        async def get_positions(self) -> tuple[BrokerPosition, ...]:
            return ()

    monkeypatch.setattr(cli, "build_broker", lambda: Broker())
    result = CliRunner().invoke(cli.app, ["verify-account", "--competition"])

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["verified"] is False
    assert payload["verification"] == "partial"
    assert "HISTORICAL_ACTIVITY_UNVERIFIED" in payload["unverified"]
