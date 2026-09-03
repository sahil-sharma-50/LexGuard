"""New-York-time, Alpaca-calendar-aware decision-window scheduler."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from lexguard.adapters.alpaca_trading import BrokerClock, BrokerPosition
from lexguard.domain.enums import DecisionWindow
from lexguard.domain.models import ExecutionRecord, TradeCertificate
from lexguard.services.case_service import CaseOutcome
from lexguard.services.reconciliation import ReconciliationReport

if TYPE_CHECKING:
    from lexguard.services.position_manager import PositionEvidence, PositionManager

NEW_YORK = ZoneInfo("America/New_York")
WINDOW_TIMES: dict[DecisionWindow, time] = {
    DecisionWindow.MORNING: time(10, 5),
    DecisionWindow.MIDDAY: time(11, 35),
    DecisionWindow.AFTERNOON: time(13, 5),
    DecisionWindow.LATE: time(14, 20),
}
EXECUTION_TIMES: dict[DecisionWindow, time] = {
    DecisionWindow.MORNING: time(10, 10),
    DecisionWindow.MIDDAY: time(11, 40),
    DecisionWindow.AFTERNOON: time(13, 10),
    DecisionWindow.LATE: time(14, 25),
}
FORCED_EXIT_TIME = time(15, 30)
EARLY_CLOSE_BUFFER = timedelta(minutes=30)
MINIMUM_HOLD = timedelta(minutes=60)


@dataclass(frozen=True, slots=True)
class CalendarSession:
    trading_date: date
    open: datetime
    close: datetime

    def __post_init__(self) -> None:
        if self.open.tzinfo is None or self.open.utcoffset() is None:
            raise ValueError("calendar open must be timezone-aware")
        if self.close.tzinfo is None or self.close.utcoffset() is None:
            raise ValueError("calendar close must be timezone-aware")
        if self.close <= self.open:
            raise ValueError("calendar close must be after open")


class CalendarProvider(Protocol):
    async def get_clock(self) -> BrokerClock: ...

    async def get_calendar(self, start: date, end: date) -> tuple[CalendarSession, ...]: ...


class LeaseRepository(Protocol):
    def acquire_window_lease(
        self,
        trading_date: date,
        decision_window: str,
        owner: str,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> bool: ...

    def pending_certificate(
        self, trading_date: date, decision_window: str
    ) -> TradeCertificate | None: ...

    def record_execution(self, record: ExecutionRecord) -> object: ...


class Reconciler(Protocol):
    async def reconcile(self) -> ReconciliationReport: ...


class CaseEvaluator(Protocol):
    async def evaluate(self, window: DecisionWindow, now: datetime) -> CaseOutcome: ...


class CertificateExecutor(Protocol):
    async def execute(self, certificate: TradeCertificate, now: datetime) -> ExecutionRecord: ...


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """Broker positions plus the completed evidence used by exit policy."""

    positions: tuple[BrokerPosition, ...]
    evidence: PositionEvidence


class PositionSnapshotProvider(Protocol):
    async def snapshot(self, now: datetime) -> PositionSnapshot: ...


class PositionCloser(Protocol):
    async def close(
        self,
        positions: Sequence[BrokerPosition],
        reason: str,
        now: datetime,
        case_id: UUID | None = None,
    ) -> object: ...


ReadinessCheck = Callable[[], Awaitable[tuple[bool, tuple[str, ...]]]]


@dataclass(frozen=True, slots=True)
class TickResult:
    status: Literal["EVALUATED", "EXECUTED", "SKIPPED", "HALTED"]
    decision_window: str | None = None
    case_id: UUID | None = None
    state: str | None = None
    reason: str | None = None


class Scheduler:
    def __init__(
        self,
        *,
        calendar: CalendarProvider,
        reconciliation: Reconciler,
        repository: LeaseRepository,
        case_service: CaseEvaluator,
        execution_service: CertificateExecutor | None = None,
        entries_enabled: Callable[[], bool] | None = None,
        owner: str,
        lease_ttl: timedelta = timedelta(minutes=2),
        position_manager: PositionManager | None = None,
        position_snapshot_provider: PositionSnapshotProvider | None = None,
        # Kept as an alias for callers that already expose an evidence provider.
        position_evidence_provider: PositionSnapshotProvider | None = None,
        position_closer: PositionCloser | None = None,
        readiness_check: ReadinessCheck | None = None,
    ) -> None:
        if not owner:
            raise ValueError("scheduler owner must be non-empty")
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        self.calendar = calendar
        self.reconciliation = reconciliation
        self.repository = repository
        self.case_service = case_service
        self.execution_service = execution_service
        self.entries_enabled = entries_enabled or (lambda: True)
        self.owner = owner
        self.lease_ttl = lease_ttl
        self.position_manager = position_manager
        self.position_snapshot_provider = (
            position_snapshot_provider or position_evidence_provider
        )
        self.position_closer = position_closer
        self._readiness_check = readiness_check
        # Directly composed schedulers (for deterministic unit tests) are ready;
        # deployment-composed schedulers remain blocked until their async preflight.
        self.runtime_ready = readiness_check is None
        self.runtime_blockers: tuple[str, ...] = ()

    async def preflight(self) -> bool:
        """Prove live dependency boundaries before allowing a scheduler tick."""

        check = self._readiness_check
        if check is None:
            return self.runtime_ready
        try:
            ready, blockers = await check()
        except Exception:
            ready, blockers = False, ("RUNTIME_PREFLIGHT_FAILURE",)
        self.runtime_ready = bool(ready)
        self.runtime_blockers = tuple(sorted(set(blockers)))
        return self.runtime_ready

    async def tick(self, now: datetime) -> TickResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("scheduler time must be timezone-aware")
        if not self.runtime_ready:
            return TickResult("HALTED", reason="RUNTIME_NOT_READY")

        close_reconciliation = await self._reconcile_close_intents(now)
        if close_reconciliation is not None:
            return close_reconciliation

        # Poll durable entry chains before evaluating a new window.  This is
        # intentionally a capability seam: simple offline fakes need not
        # implement restart polling, while the production execution service
        # can observe orders submitted by a previous process.
        entry_reconciliation = await self._reconcile_entry_orders(now)
        if entry_reconciliation is not None:
            return entry_reconciliation
        local = now.astimezone(NEW_YORK)
        sessions = await self.calendar.get_calendar(local.date(), local.date())
        session = next((item for item in sessions if item.trading_date == local.date()), None)
        if session is None:
            return TickResult("SKIPPED", reason="MARKET_CLOSED")
        clock = await self.calendar.get_clock()
        if not clock.is_open:
            return TickResult("SKIPPED", reason="MARKET_CLOSED")
        if local < session.open.astimezone(NEW_YORK) or local >= session.close.astimezone(NEW_YORK):
            return TickResult("SKIPPED", reason="MARKET_CLOSED")

        position_result = await self._manage_position(now)
        if position_result is not None:
            return position_result

        evaluation_window = self._evaluation_window_due(local)
        execution_window = self._execution_window_due(local)
        if evaluation_window is None and execution_window is None:
            return TickResult("SKIPPED", reason="NO_WINDOW")
        window = evaluation_window or execution_window
        assert window is not None
        forced_exit = self._forced_exit(session, local.date())
        if local + MINIMUM_HOLD > forced_exit:
            return TickResult("SKIPPED", window.value, reason="EARLY_CLOSE_UNSAFE")

        try:
            reconciliation = await self.reconciliation.reconcile()
        except Exception:
            return TickResult("HALTED", window.value, reason="RECONCILIATION_FAILURE")
        if reconciliation.state != "CONSISTENT":
            return TickResult("HALTED", window.value, reason="RECONCILIATION_REQUIRED")
        if not self.entries_enabled():
            return TickResult("SKIPPED", window.value, reason="ENTRIES_DISABLED")
        if not self.repository.acquire_window_lease(
            local.date(),
            window.value,
            self.owner,
            now=now,
            ttl=self.lease_ttl,
        ):
            return TickResult("SKIPPED", window.value, reason="LEASE_HELD")
        if execution_window is not None:
            return await self._execute_pending(local.date(), execution_window, now)
        try:
            outcome = await self.case_service.evaluate(window, now)
        except Exception:
            return TickResult("HALTED", window.value, reason="CASE_EVALUATION_FAILURE")
        return TickResult(
            "EVALUATED",
            decision_window=window.value,
            case_id=outcome.case_id,
            state=outcome.state.value,
        )

    async def _reconcile_close_intents(self, now: datetime) -> TickResult | None:
        service = self.execution_service or self.position_closer
        poller = getattr(service, "reconcile_close_intents", None)
        if not callable(poller):
            return None
        try:
            results = tuple(await poller(now))
        except Exception:
            return TickResult("HALTED", reason="CLOSE_RECONCILIATION_FAILURE")
        unresolved: list[str] = []
        for result in results:
            state = getattr(result, "state", "RECONCILE_REQUIRED")
            if state == "PENDING_OWNER":
                continue
            recorder = getattr(self.repository, "record_close_result", None)
            if callable(recorder):
                try:
                    recorder(result)
                except Exception:
                    return TickResult("HALTED", reason="CLOSE_LEDGER_FAILURE")
            if state != "CLOSED":
                unresolved.append(str(state))
        if unresolved:
            return TickResult(
                "HALTED", state="RECONCILE_REQUIRED", reason="CLOSE_RECONCILIATION_REQUIRED"
            )
        return None

    async def _reconcile_entry_orders(self, now: datetime) -> TickResult | None:
        service = self.execution_service
        poller = getattr(service, "reconcile_entry_orders", None)
        if not callable(poller):
            return None
        try:
            records = tuple(await poller(now))
        except Exception:
            return TickResult(
                "HALTED", state="RECONCILE_REQUIRED", reason="ENTRY_RECONCILIATION_FAILURE"
            )
        for record in records:
            recorder = getattr(self.repository, "record_entry_observation", None)
            if not callable(recorder):
                recorder = getattr(self.repository, "record_execution", None)
            if callable(recorder):
                try:
                    recorder(record)
                except Exception:
                    return TickResult(
                        "HALTED", state="RECONCILE_REQUIRED", reason="ENTRY_LEDGER_FAILURE"
                    )
            state = getattr(record, "state", None)
            if state == "RECONCILE_REQUIRED":
                return TickResult(
                    "HALTED", state="RECONCILE_REQUIRED", reason="ENTRY_RECONCILIATION_REQUIRED"
                )
            if state in {"CANCELED", "REJECTED"}:
                return TickResult(
                    "HALTED", state=str(state), reason="ENTRY_ORDER_TERMINAL"
                )
        return None

    async def _manage_position(self, now: datetime) -> TickResult | None:
        """Drive exits independently of entry enablement and fixed entry windows."""

        manager = self.position_manager
        provider = self.position_snapshot_provider
        if manager is None and provider is None:
            return None
        if manager is None or provider is None:
            return TickResult("HALTED", reason="POSITION_DEPENDENCY_UNAVAILABLE")
        try:
            snapshot = await self._position_snapshot(provider, now)
        except Exception:
            return TickResult("HALTED", reason="POSITION_EVIDENCE_FAILURE")
        if not snapshot.positions:
            return None
        try:
            decision = await manager.evaluate(now, snapshot.evidence)
        except Exception:
            return TickResult("HALTED", reason="POSITION_POLICY_FAILURE")
        # Import lazily because position_manager uses this module's frozen time constants.
        from lexguard.services.position_manager import Close

        if not isinstance(decision, Close):
            return None
        closer = self.position_closer
        if closer is None:
            return TickResult(
                "HALTED", state="CLOSE_REQUIRED", reason="POSITION_CLOSER_UNAVAILABLE"
            )
        try:
            position_case_id = None
            resolver = getattr(self.repository, "resolve_position_case_id", None)
            if callable(resolver):
                position_case_id = resolver(tuple(item.symbol for item in snapshot.positions))
            try:
                close_result = await closer.close(
                    snapshot.positions, decision.reason, now, position_case_id
                )
            except TypeError:
                close_result = await closer.close(snapshot.positions, decision.reason, now)
        except Exception:
            return TickResult("HALTED", state="CLOSE_REQUIRED", reason="POSITION_CLOSE_FAILURE")
        close_state = getattr(close_result, "state", None)
        recorder = getattr(self.repository, "record_close_result", None)
        if callable(recorder):
            try:
                recorder(close_result)
            except Exception:
                return TickResult("HALTED", state="CLOSE_REQUIRED", reason="CLOSE_LEDGER_FAILURE")
        if close_state == "PENDING_OWNER":
            return TickResult("SKIPPED", state="PENDING_OWNER", reason="CLOSE_OWNER_PENDING")
        if close_state == "CLOSED":
            return TickResult("EXECUTED", state="CLOSED", reason=decision.reason)
        if close_state == "REJECTED":
            return TickResult("HALTED", state="REJECTED", reason="POSITION_CLOSE_REJECTED")
        return TickResult(
            "HALTED",
            state=(close_state if isinstance(close_state, str) else "RECONCILE_REQUIRED"),
            reason="POSITION_CLOSE_RECONCILIATION_REQUIRED",
        )

    @staticmethod
    async def _position_snapshot(
        provider: PositionSnapshotProvider, now: datetime
    ) -> PositionSnapshot:
        """Accept the named protocol and simple callable fakes at the seam."""

        snapshot_method = getattr(provider, "snapshot", None)
        if callable(snapshot_method):
            result = await snapshot_method(now)
        else:
            result = await provider(now)  # type: ignore[operator]
        if isinstance(result, PositionSnapshot):
            return result
        if isinstance(result, tuple) and len(result) == 2:
            positions, evidence = result
            return PositionSnapshot(tuple(positions), evidence)
        raise TypeError("position provider must return PositionSnapshot")

    @staticmethod
    def _evaluation_window_due(local: datetime) -> DecisionWindow | None:
        current = local.time().replace(second=0, microsecond=0)
        for window, target in WINDOW_TIMES.items():
            if current == target:
                return window
        return None

    @staticmethod
    def _execution_window_due(local: datetime) -> DecisionWindow | None:
        current = local.time().replace(second=0, microsecond=0)
        for window, target in EXECUTION_TIMES.items():
            if current == target:
                return window
        return None

    async def _execute_pending(
        self,
        trading_date: date,
        window: DecisionWindow,
        now: datetime,
    ) -> TickResult:
        if self.execution_service is None:
            return TickResult("HALTED", window.value, reason="EXECUTION_SERVICE_UNAVAILABLE")
        try:
            certificate = self.repository.pending_certificate(trading_date, window.value)
        except Exception:
            return TickResult("HALTED", window.value, reason="PENDING_CERTIFICATE_FAILURE")
        if certificate is None:
            return TickResult("SKIPPED", window.value, reason="NO_PENDING_CERTIFICATE")
        veto_checker = getattr(self.repository, "operator_veto_exists", None)
        if callable(veto_checker):
            try:
                vetoed = bool(veto_checker(certificate.case_id))
            except Exception:
                return TickResult("HALTED", window.value, reason="VETO_CHECK_FAILURE")
            if vetoed:
                # A human can stop a pending certificate, never initiate one.
                return TickResult(
                    "SKIPPED",
                    window.value,
                    certificate.case_id,
                    "VETOED",
                    "OPERATOR_VETO",
                )
        try:
            record = await self.execution_service.execute(certificate, now)
            self.repository.record_execution(record)
        except Exception:
            return TickResult("HALTED", window.value, reason="EXECUTION_FAILURE")
        if record.state in {"RECONCILE_REQUIRED", "REJECTED", "CANCELED"}:
            if record.state == "RECONCILE_REQUIRED":
                reason = "RECONCILIATION_REQUIRED"
            else:
                reason = "ENTRY_ORDER_TERMINAL"
            return TickResult(
                "HALTED",
                window.value,
                certificate.case_id,
                record.state,
                reason,
            )
        return TickResult("EXECUTED", window.value, certificate.case_id, record.state)

    @staticmethod
    def _forced_exit(session: CalendarSession, trading_date: date) -> datetime:
        normal = datetime.combine(trading_date, FORCED_EXIT_TIME, tzinfo=NEW_YORK)
        early = session.close.astimezone(NEW_YORK) - EARLY_CLOSE_BUFFER
        return min(normal, early)
