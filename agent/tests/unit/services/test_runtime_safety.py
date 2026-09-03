"""Regression tests for the scheduler-to-execution safety boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from lexguard.adapters.alpaca_trading import BrokerAccount, BrokerClock, BrokerOrder
from lexguard.domain.enums import DecisionWindow
from lexguard.domain.hashing import canonical_sha256
from lexguard.domain.models import (
    CandidateStructure,
    OptionLeg,
    TradeCertificate,
)
from lexguard.domain.policy import RiskContext, RiskPolicy
from lexguard.domain.state_machine import CaseState
from lexguard.services.case_service import CaseOutcome
from lexguard.services.execution import ExecutionService
from lexguard.services.reconciliation import ReconciliationReport
from lexguard.services.scheduler import CalendarSession, Scheduler

NY = ZoneInfo("America/New_York")


def et(yyyy: int, mm: int, dd: int, hh: int, minute: int) -> datetime:
    return datetime(yyyy, mm, dd, hh, minute, tzinfo=NY).astimezone(UTC)


def certificate() -> TradeCertificate:
    expiration = date(2026, 8, 25)
    def leg(symbol: str, strike: str, right: str, side: str) -> OptionLeg:
        return OptionLeg(
            symbol=symbol,
            underlying="SPY",
            expiration=expiration,
            strike=Decimal(strike),
            right=right,
            side=side,
        )

    candidate = CandidateStructure(
        candidate_id=UUID("11111111-1111-1111-1111-111111111111"),
        strategy="LONG_VOL",
        underlying="SPY",
        expiration=expiration,
        legs=(
            leg("SPY260825P00575000", "575", "P", "SELL"),
            leg("SPY260825P00580000", "580", "P", "BUY"),
            leg("SPY260825C00590000", "590", "C", "BUY"),
            leg("SPY260825C00595000", "595", "C", "SELL"),
        ),
        quantity=1,
        entry_limit=Decimal("1.25"),
        max_loss=Decimal("125"),
        modeled_friction=Decimal("0"),
        modeled_fees=Decimal("0"),
        robust_ev=Decimal("25"),
    )
    issued_at = et(2026, 8, 24, 10, 5)
    return TradeCertificate(
        certificate_id=UUID("22222222-2222-2222-2222-222222222222"),
        case_id=UUID("33333333-3333-3333-3333-333333333333"),
        candidate=candidate,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=10),
        policy_version="risk.v1",
        proposal_hash=canonical_sha256(candidate),
        account_equity=Decimal("100000"),
        daily_pnl=Decimal("0"),
        competition_drawdown=Decimal("0"),
    )


class CalendarSpy:
    async def get_clock(self) -> BrokerClock:
        return BrokerClock(timestamp=et(2026, 8, 24, 10, 5), is_open=True)

    async def get_calendar(self, start: date, end: date) -> tuple[CalendarSession, ...]:
        return (session_for(start),)


class ReconSpy:
    def __init__(self) -> None:
        self.calls = 0

    async def reconcile(self) -> ReconciliationReport:
        self.calls += 1
        return ReconciliationReport("CONSISTENT", (), (), (), (), ())


class LeaseSpy:
    def acquire_window_lease(
        self,
        trading_date: date,
        decision_window: str,
        owner: str,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> bool:
        return True


class CaseSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[DecisionWindow, datetime]] = []

    async def evaluate(self, window: DecisionWindow, now: datetime) -> CaseOutcome:
        self.calls.append((window, now))
        return CaseOutcome(certificate().case_id, CaseState.CERTIFIED, certificate=certificate())


def session_for(day: date) -> CalendarSession:
    return CalendarSession(
        day,
        datetime.combine(day, time(9, 30), tzinfo=NY),
        datetime.combine(day, time(16), tzinfo=NY),
    )


class ScriptedBroker:
    base_url = "https://paper-api.alpaca.markets"

    def __init__(self) -> None:
        self.submit_count = 0

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

    async def get_orders(self) -> tuple[BrokerOrder, ...]:
        return ()

    async def get_clock(self) -> BrokerClock:
        return BrokerClock(timestamp=et(2026, 8, 24, 10, 10), is_open=True)

    async def submit_mleg(
        self, trade_certificate: TradeCertificate, limit_price: Decimal | None = None
    ) -> BrokerOrder:
        self.submit_count += 1
        return BrokerOrder(order_id="order-1", status="new")

    async def get_order(self, order_id: str) -> BrokerOrder:
        return BrokerOrder(order_id=order_id, status="new")

    async def replace_order(self, order_id: str, limit_price: Decimal) -> BrokerOrder:
        return BrokerOrder(order_id="order-2", status="new")

    async def cancel_order(self, order_id: str) -> None:
        return None


def _context(*, now: datetime, entry_attempt: bool) -> RiskContext:
    return RiskContext(
        now=now,
        decision_window="10:05",
        evidence_observed_at=now,
        daily_pnl=Decimal("0"),
        competition_drawdown=Decimal("0"),
        entries_today=0,
        traded_symbols_today=(),
        open_structure_count=0,
        open_order_count=0,
        open_position_count=0,
        account_status="ACTIVE",
        options_level=3,
        opra_available=True,
        base_url="https://paper-api.alpaca.markets",
        certificate_expires_at=now + timedelta(minutes=5),
        entry_attempt=entry_attempt,
    )


def test_evaluation_can_certify_before_execution_window_but_entry_cannot() -> None:
    candidate = certificate().candidate
    at_evaluation = et(2026, 8, 24, 10, 5)

    evaluation = RiskPolicy().evaluate(candidate, _context(now=at_evaluation, entry_attempt=False))
    assert evaluation.allowed
    decision = RiskPolicy().evaluate(candidate, _context(now=at_evaluation, entry_attempt=True))
    assert "ENTRY_WINDOW_CLOSED" in decision.reason_codes


class PendingLease(LeaseSpy):
    def __init__(self) -> None:
        super().__init__()
        self.pending = certificate()
        self.executions: list[str] = []

    def pending_certificate(self, trading_date: date, decision_window: str):  # type: ignore[no-untyped-def]
        if decision_window == "10:05":
            return self.pending
        return None

    def record_execution(self, record):  # type: ignore[no-untyped-def]
        self.executions.append(record.state)


class ExecutionSpy:
    def __init__(self, state: str = "SUBMITTED") -> None:
        self.calls: list[datetime] = []
        self.state = state

    async def execute(self, trade_certificate, now):  # type: ignore[no-untyped-def]
        self.calls.append(now)
        from lexguard.domain.models import ExecutionRecord

        return ExecutionRecord(
            case_id=trade_certificate.case_id,
            certificate_id=trade_certificate.certificate_id,
            alpaca_order_ids=("order-1",),
            state=self.state,  # type: ignore[arg-type]
            submitted_at=now,
            updated_at=now,
            filled_quantity=0,
        )


@pytest.mark.asyncio
async def test_scheduler_evaluates_at_1005_and_executes_persisted_certificate_at_1010() -> None:
    calendar = CalendarSpy()
    reconciliation = ReconSpy()
    repository = PendingLease()
    case = CaseSpy()
    execution = ExecutionSpy()
    scheduler = Scheduler(
        calendar=calendar,
        reconciliation=reconciliation,
        repository=repository,
        case_service=case,
        execution_service=execution,
        owner="runtime-safety",
    )

    evaluation = await scheduler.tick(et(2026, 8, 24, 10, 5))
    before_entry = await scheduler.tick(et(2026, 8, 24, 10, 9))
    execution_result = await scheduler.tick(et(2026, 8, 24, 10, 10))

    assert evaluation.status == "EVALUATED"
    assert before_entry.reason == "NO_WINDOW"
    assert execution_result.status == "EXECUTED"
    assert len(case.calls) == 1
    assert len(execution.calls) == 1
    assert repository.executions == ["SUBMITTED"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["REJECTED", "CANCELED", "RECONCILE_REQUIRED"])
async def test_scheduler_halts_rejected_canceled_or_unresolved_execution(
    state: str,
) -> None:
    scheduler = Scheduler(
        calendar=CalendarSpy(),
        reconciliation=ReconSpy(),
        repository=PendingLease(),
        case_service=CaseSpy(),
        execution_service=ExecutionSpy(state),
        owner="runtime-safety",
    )

    result = await scheduler.tick(et(2026, 8, 24, 10, 10))

    assert result.status == "HALTED"
    assert result.state == state
    assert result.reason in {"ENTRY_ORDER_TERMINAL", "RECONCILIATION_REQUIRED"}


@pytest.mark.asyncio
async def test_disabled_entries_still_reconcile_but_never_evaluate_or_execute() -> None:
    reconciliation = ReconSpy()
    case = CaseSpy()
    execution = ExecutionSpy()
    scheduler = Scheduler(
        calendar=CalendarSpy(),
        reconciliation=reconciliation,
        repository=PendingLease(),
        case_service=case,
        execution_service=execution,
        entries_enabled=lambda: False,
        owner="runtime-safety",
    )

    result = await scheduler.tick(et(2026, 8, 24, 10, 10))

    assert result.reason == "ENTRIES_DISABLED"
    assert reconciliation.calls == 1
    assert case.calls == []
    assert execution.calls == []


class DenyingRiskProvider:
    async def build(self, trade_certificate, now, account, positions, orders, clock, quotes):  # type: ignore[no-untyped-def]
        return _context(now=now, entry_attempt=True).model_copy(
            update={"daily_pnl": Decimal("-1500")}
        )


class QuoteSpy:
    async def get_option_chain(self, underlying_symbol, *, expiration_date=None, limit=100):  # type: ignore[no-untyped-def]
        return tuple(
            __import__("lexguard.domain.models", fromlist=["OptionQuote"]).OptionQuote(
                symbol=leg.symbol,
                underlying="SPY",
                expiration=certificate().candidate.expiration,
                strike=leg.strike,
                right=leg.right,
                bid=Decimal("1.00"),
                ask=Decimal("1.10"),
                observed_at=certificate().issued_at,
                feed="opra",
            )
            for leg in certificate().candidate.legs
        )


@pytest.mark.asyncio
async def test_execution_revalidates_current_risk_before_order_submission() -> None:
    broker = ScriptedBroker()
    result = await ExecutionService(
        broker, quote_checker=QuoteSpy(), risk_context_provider=DenyingRiskProvider()
    ).execute(
        certificate(), certificate().issued_at
    )

    assert result.state == "REJECTED"
    assert broker.submit_count == 0
