"""Safety contracts for the operator CLI."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from lexguard import cli
from lexguard.adapters.alpaca_trading import BrokerAccount, BrokerOrder, BrokerPosition
from lexguard.adapters.repository import CaseRepository
from lexguard.services.reconciliation import ReconciliationReport


class FakeBroker:
    def __init__(self, *, dirty: bool = False) -> None:
        self.mutation_calls: list[str] = []
        self.account = BrokerAccount(
            status="ACTIVE",
            equity=Decimal("100000"),
            last_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            competition_drawdown=Decimal("0"),
            options_level=3,
            base_url="https://paper-api.alpaca.markets",
        )
        self.orders = (
            BrokerOrder(order_id="working-1", status="NEW"),
        ) if dirty else ()
        self.positions = (
            BrokerPosition(symbol="SPY240101C00500000", quantity=1, side="long"),
        ) if dirty else ()

    async def get_account(self) -> BrokerAccount:
        return self.account

    async def get_orders(self) -> tuple[BrokerOrder, ...]:
        return self.orders

    async def get_positions(self) -> tuple[BrokerPosition, ...]:
        return self.positions

    async def get_clock(self) -> object:
        return {"is_open": False}


def test_verify_account_requires_fresh_empty_competition_account(monkeypatch) -> None:
    fake = FakeBroker(dirty=True)
    monkeypatch.setattr(cli, "build_broker", lambda: fake)
    result = CliRunner().invoke(cli.app, ["verify-account", "--competition"])
    assert result.exit_code != 0
    assert "account is not fresh" in result.output.lower()
    assert fake.mutation_calls == []


def test_disable_entries_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "entry-state.json"
    monkeypatch.setenv("LEXGUARD_ENTRY_STATE_PATH", str(state_path))
    runner = CliRunner()
    try:
        assert runner.invoke(cli.app, ["disable-entries"]).exit_code == 0
        assert runner.invoke(cli.app, ["disable-entries"]).exit_code == 0
        assert '"entry_enabled": false' in runner.invoke(cli.app, ["status"]).output
    finally:
        state_path.unlink(missing_ok=True)


def test_enable_entries_requires_explicit_environment_acknowledgement(monkeypatch) -> None:
    monkeypatch.setenv("LEXGUARD_ENVIRONMENT", "development")
    result = CliRunner().invoke(cli.app, ["enable-entries", "--environment", "development"])
    assert result.exit_code != 0
    assert "acknowledge-paper-only" in result.output


def test_status_and_preflight_are_read_only(monkeypatch) -> None:
    fake = FakeBroker()
    monkeypatch.setattr(cli, "build_broker", lambda: fake)
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    runner = CliRunner()
    assert runner.invoke(cli.app, ["status"]).exit_code == 0
    assert runner.invoke(cli.app, ["run-preflight"]).exit_code == 0
    assert runner.invoke(cli.app, ["reconcile"]).exit_code == 0
    assert fake.mutation_calls == []


def test_scheduler_command_runs_composed_scheduler_once(monkeypatch) -> None:
    class SchedulerSpy:
        runtime_ready = True

        async def tick(self, now: datetime):  # type: ignore[no-untyped-def]
            self.now = now
            return {"status": "SKIPPED", "reason": "NO_WINDOW"}

    scheduler = SchedulerSpy()
    monkeypatch.setattr(cli, "build_scheduler", lambda: scheduler)

    result = CliRunner().invoke(cli.app, ["scheduler", "--once"])

    assert result.exit_code == 0
    assert "NO_WINDOW" in result.output
    assert scheduler.now.tzinfo is not None


def test_scheduler_command_runs_async_preflight_before_tick(monkeypatch) -> None:
    class SchedulerSpy:
        runtime_ready = False

        def __init__(self) -> None:
            self.preflight_called = False
            self.tick_called = False

        async def preflight(self) -> bool:
            self.preflight_called = True
            return False

        async def tick(self, now: datetime):  # type: ignore[no-untyped-def]
            self.tick_called = True
            return {"status": "SKIPPED"}

    scheduler = SchedulerSpy()
    monkeypatch.setattr(cli, "build_scheduler", lambda: scheduler)

    result = CliRunner().invoke(cli.app, ["scheduler", "--once"])

    assert result.exit_code != 0
    assert scheduler.preflight_called is True
    assert scheduler.tick_called is False


def test_scheduler_records_a_verified_health_heartbeat(monkeypatch) -> None:
    class Reconciler:
        async def reconcile(self) -> ReconciliationReport:
            return ReconciliationReport("CONSISTENT", (), (), (), (), ())

    class SchedulerSpy:
        runtime_ready = True

        def __init__(self, repository: CaseRepository) -> None:
            self.repository = repository
            self.reconciliation = Reconciler()

        async def preflight(self) -> bool:
            return True

        async def tick(self, now: datetime):  # type: ignore[no-untyped-def]
            return {"status": "SKIPPED", "reason": "NO_WINDOW"}

    repository = CaseRepository("sqlite://")
    repository.create_schema()
    scheduler = SchedulerSpy(repository)
    monkeypatch.setattr(cli, "build_scheduler", lambda: scheduler)
    monkeypatch.setattr(cli, "_risk_state_service", lambda: None)

    result = CliRunner().invoke(cli.app, ["scheduler", "--once"])

    assert result.exit_code == 0
    artifact = repository.latest_artifact("health_heartbeat")
    assert artifact is not None
    assert artifact[0]["components"] == {
        "alpaca": "healthy",
        "scheduler": "healthy",
        "reconciliation": "healthy",
    }


def test_real_scheduler_composition_reports_not_ready_without_evidence_runtime(monkeypatch) -> None:
    class CalendarBroker(FakeBroker):
        async def get_calendar(self, start, end):  # type: ignore[no-untyped-def]
            return ()

    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setattr(cli, "build_broker", CalendarBroker)

    scheduler = cli.build_scheduler()

    assert scheduler.runtime_ready is False
    assert "MCP_RUNTIME_UNCONFIGURED" in scheduler.runtime_blockers


def test_scheduler_command_refuses_unready_runtime_even_when_entries_are_disabled(
    monkeypatch, tmp_path: Path
) -> None:
    class CalendarBroker(FakeBroker):
        async def get_calendar(self, start, end):  # type: ignore[no-untyped-def]
            return ()

    state_path = tmp_path / "entry-state.json"
    state_path.write_text('{"entry_enabled": false}\n', encoding="utf-8")
    monkeypatch.setenv("LEXGUARD_ENTRY_STATE_PATH", str(state_path))
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setattr(cli, "build_broker", CalendarBroker)
    try:
        result = CliRunner().invoke(cli.app, ["scheduler", "--once"])
    finally:
        state_path.unlink(missing_ok=True)

    assert result.exit_code != 0
    assert '"ready": false' in result.output
    assert "not_runnable" in result.output
