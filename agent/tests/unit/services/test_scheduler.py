"""Calendar-aware scheduler tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from lexguard.adapters.alpaca_trading import BrokerClock
from lexguard.domain.enums import DecisionWindow
from lexguard.domain.state_machine import CaseState
from lexguard.services.case_service import CaseOutcome
from lexguard.services.reconciliation import ReconciliationReport
from lexguard.services.scheduler import CalendarSession, Scheduler

NY = ZoneInfo("America/New_York")


def et(yyyy: int, mm: int, dd: int, hh: int, minute: int) -> datetime:
    return datetime(yyyy, mm, dd, hh, minute, tzinfo=NY).astimezone(UTC)


class CalendarSpy:
    def __init__(self, session: CalendarSession | None) -> None:
        self.session = session
        self.clock_calls = 0

    async def get_clock(self) -> BrokerClock:
        self.clock_calls += 1
        return BrokerClock(timestamp=datetime.now(UTC), is_open=True)

    async def get_calendar(self, start: date, end: date) -> tuple[CalendarSession, ...]:
        if self.session is None:
            return ()
        return (self.session,)


class ReconSpy:
    def __init__(self, state: str = "CONSISTENT") -> None:
        self.state = state
        self.calls = 0

    async def reconcile(self) -> ReconciliationReport:
        self.calls += 1
        return ReconciliationReport(
            state=self.state,
            reason_codes=() if self.state == "CONSISTENT" else ("UNKNOWN_BROKER_ORDER",),
            broker_order_ids=(),
            broker_position_symbols=(),
            ledger_order_ids=(),
            ledger_position_symbols=(),
        )


class LeaseSpy:
    def __init__(self) -> None:
        self.keys: set[tuple[date, str]] = set()
        self.calls = 0

    def acquire_window_lease(
        self,
        trading_date: date,
        decision_window: str,
        owner: str,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> bool:
        self.calls += 1
        key = (trading_date, decision_window)
        if key in self.keys:
            return False
        self.keys.add(key)
        return True


class CaseSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[DecisionWindow, datetime]] = []

    async def evaluate(self, window: DecisionWindow, now: datetime) -> CaseOutcome:
        self.calls.append((window, now))
        return CaseOutcome(
            case_id=UUID("33333333-3333-3333-3333-333333333333"),
            state=CaseState.REFUSED,
        )


def session_for(day: date, close: time = time(16, 0)) -> CalendarSession:
    return CalendarSession(
        trading_date=day,
        open=datetime.combine(day, time(9, 30), tzinfo=NY),
        close=datetime.combine(day, close, tzinfo=NY),
    )


def make_scheduler(
    instant: datetime,
    *,
    session: CalendarSession | None = None,
    recon_state: str = "CONSISTENT",
    use_default_session: bool = True,
) -> tuple[Scheduler, CalendarSpy, ReconSpy, LeaseSpy, CaseSpy]:
    calendar = CalendarSpy(
        session
        if session is not None or not use_default_session
        else session_for(instant.astimezone(NY).date())
    )
    reconciliation = ReconSpy(recon_state)
    lease = LeaseSpy()
    case = CaseSpy()
    scheduler = Scheduler(
        calendar=calendar,
        reconciliation=reconciliation,
        repository=lease,
        case_service=case,
        owner="test-scheduler",
    )
    return scheduler, calendar, reconciliation, lease, case


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "instant",
    [et(2026, 3, 9, 10, 5), et(2026, 11, 2, 10, 5)],
)
async def test_scheduler_uses_alpaca_calendar_and_new_york_time(instant: datetime) -> None:
    scheduler, _, _, _, case = make_scheduler(instant)

    result = await scheduler.tick(instant)

    assert result.status == "EVALUATED"
    assert result.decision_window == "10:05"
    assert case.calls[0][0] == DecisionWindow.MORNING


@pytest.mark.asyncio
async def test_duplicate_tick_is_lease_skipped() -> None:
    instant = et(2026, 8, 24, 10, 5)
    scheduler, _, _, lease, case = make_scheduler(instant)

    first = await scheduler.tick(instant)
    second = await scheduler.tick(instant + timedelta(seconds=20))

    assert first.status == "EVALUATED"
    assert second.status == "SKIPPED"
    assert second.reason == "LEASE_HELD"
    assert lease.calls == 2
    assert len(case.calls) == 1


@pytest.mark.asyncio
async def test_reconciliation_halts_before_accepting_lease() -> None:
    instant = et(2026, 8, 24, 10, 5)
    scheduler, _, reconciliation, lease, case = make_scheduler(
        instant, recon_state="RECONCILE_REQUIRED"
    )

    result = await scheduler.tick(instant)

    assert result.status == "HALTED"
    assert result.reason == "RECONCILIATION_REQUIRED"
    assert reconciliation.calls == 1
    assert lease.calls == 0
    assert case.calls == []


@pytest.mark.asyncio
async def test_holiday_and_unsafe_early_close_skip_entry() -> None:
    holiday = et(2026, 12, 25, 10, 5)
    scheduler, _, _, lease, _ = make_scheduler(holiday, session=None, use_default_session=False)
    assert (await scheduler.tick(holiday)).reason == "MARKET_CLOSED"
    assert lease.calls == 0

    early = et(2026, 8, 24, 13, 5)
    scheduler, _, _, lease, _ = make_scheduler(
        early,
        session=session_for(date(2026, 8, 24), close=time(14, 0)),
    )
    result = await scheduler.tick(early)
    assert result.status == "SKIPPED"
    assert result.reason == "EARLY_CLOSE_UNSAFE"
    assert lease.calls == 0
