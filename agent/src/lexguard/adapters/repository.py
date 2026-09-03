"""SQLAlchemy persistence for the append-only case ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from lexguard.adapters.alpaca_trading import (
    BROKER_ACTIVE_ORDER_STATES,
    BROKER_FILLED_ORDER_STATES,
)
from lexguard.domain.state_machine import CaseEventType, CaseState, transition

if TYPE_CHECKING:
    from lexguard.domain.models import TradeCertificate

UTC = UTC
ALEMBIC_HEAD = "0003_system_decision_window"
LEGACY_ORDER_DEADLINE = timedelta(seconds=90)
REQUIRED_SCHEMA_COLUMNS: dict[str, frozenset[str]] = {
    "cases": frozenset(
        {
            "case_id",
            "trading_date",
            "decision_window",
            "state",
            "underlying",
            "certificate_id",
            "created_at",
            "updated_at",
        }
    ),
    "case_events": frozenset(
        {
            "event_id",
            "case_id",
            "event_type",
            "from_state",
            "to_state",
            "occurred_at",
            "payload_hash",
            "payload_json",
        }
    ),
    "case_artifacts": frozenset(
        {"artifact_id", "case_id", "artifact_type", "content_hash", "payload_json", "created_at"}
    ),
    "scheduler_leases": frozenset(
        {"lease_id", "trading_date", "decision_window", "owner", "acquired_at", "lease_until"}
    ),
    "order_events": frozenset(
        {
            "order_event_id",
            "case_id",
            "alpaca_order_id",
            "payload_hash",
            "payload_json",
            "occurred_at",
            "role",
            "signed_quantities_json",
            "deadline_at",
            "client_order_id",
        }
    ),
    "close_intents": frozenset(
        {
            "intent_key",
            "case_id",
            "symbols_json",
            "signed_quantities_json",
            "reason",
            "order_id",
            "state",
            "role",
            "deadline_at",
            "client_order_id",
            "lease_owner",
            "lease_until",
            "claim_token",
            "created_at",
            "updated_at",
        }
    ),
    "entry_intents": frozenset(
        {
            "intent_key",
            "case_id",
            "certificate_id",
            "client_order_id",
            "state",
            "order_ids_json",
            "deadline_at",
            "lease_owner",
            "lease_until",
            "claim_token",
            "created_at",
            "updated_at",
        }
    ),
}


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("trading_date", "decision_window", name="uq_case_window"),)

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    decision_window: Mapped[str] = mapped_column(String(6), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    underlying: Mapped[str | None] = mapped_column(String(8), nullable=True)
    certificate_id: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CaseEventRow(Base):
    __tablename__ = "case_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ArtifactRow(Base):
    __tablename__ = "case_artifacts"

    artifact_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeaseRow(Base):
    __tablename__ = "scheduler_leases"
    __table_args__ = (UniqueConstraint("trading_date", "decision_window", name="uq_lease_window"),)

    lease_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    decision_window: Mapped[str] = mapped_column(String(5), nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrderEventRow(Base):
    __tablename__ = "order_events"

    order_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False)
    # A broker order can be observed repeatedly while it moves through its
    # lifecycle.  Keep every observation so restart reconciliation can use the
    # latest state without losing the audit trail.
    alpaca_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="entry")
    signed_quantities_json: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class EntryIntentRow(Base):
    """Durable claim created before an entry submit is attempted."""

    __tablename__ = "entry_intents"

    intent_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), nullable=False)
    certificate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    order_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CloseIntentRow(Base):
    """Durable idempotency record for one inverse-position close intent."""

    __tablename__ = "close_intents"

    intent_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(
        ForeignKey("cases.case_id"), nullable=True
    )
    symbols_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    signed_quantities_json: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="close")
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class CaseRead:
    case_id: UUID
    trading_date: date
    decision_window: str
    state: CaseState
    underlying: str | None


@dataclass(frozen=True)
class DailyEntryState:
    """Durable daily entry facts derived from submitted case-ledger state."""

    entries_today: int
    traded_symbols_today: tuple[str, ...]


@dataclass(frozen=True)
class LedgerCaseRecord:
    """Read-only case record with its immutable, persisted artifacts."""

    case_id: UUID
    trading_date: date
    decision_window: str
    state: str
    underlying: str | None
    updated_at: datetime
    artifacts: dict[str, dict[str, Any]]
    # Older ledgers did not have a dedicated environment column.  Keep this
    # optional and derive it from persisted artifacts when available so export
    # code can filter without changing the required migration contract.
    environment: str | None = None


@dataclass(frozen=True)
class LedgerEventRecord:
    """One append-only ledger event suitable for a projection adapter."""

    event_id: int
    case_id: UUID
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class LedgerOrderEventRecord:
    """One normalized broker-order observation from the append-only ledger."""

    order_event_id: int
    case_id: UUID
    alpaca_order_id: str
    occurred_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class CloseIntentRecord:
    intent_key: str
    case_id: UUID | None
    symbols: tuple[str, ...]
    reason: str
    order_id: str | None
    state: str
    created_at: datetime
    updated_at: datetime
    lease_owner: str | None = None
    lease_until: datetime | None = None
    claim_token: str | None = None
    signed_quantities: dict[str, int] | None = None
    deadline_at: datetime | None = None
    client_order_id: str | None = None


@dataclass(frozen=True)
class EntryIntentRecord:
    intent_key: str
    case_id: UUID
    certificate_id: UUID
    client_order_id: str
    state: str
    order_ids: tuple[str, ...]
    deadline_at: datetime
    created_at: datetime
    updated_at: datetime
    lease_owner: str | None = None
    lease_until: datetime | None = None
    claim_token: str | None = None


@dataclass(frozen=True)
class EntryIntentClaim:
    record: EntryIntentRecord
    claimed: bool
    created: bool

    @property
    def claim_token(self) -> str | None:
        return self.record.claim_token

    def __getattr__(self, name: str) -> Any:
        return getattr(self.record, name)


@dataclass(frozen=True)
class CloseIntentClaim:
    record: CloseIntentRecord
    claimed: bool
    created: bool

    @property
    def claim_token(self) -> str | None:
        return self.record.claim_token

    def __getattr__(self, name: str) -> Any:
        return getattr(self.record, name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CloseIntentClaim):
            return self.record == other.record
        if isinstance(other, CloseIntentRecord):
            return self.record == other
        return NotImplemented


def entry_intent_key(certificate_id: UUID) -> str:
    """Return the stable idempotency key for one certified entry."""

    return f"entry:{certificate_id}"


def entry_client_order_id(certificate_id: UUID) -> str:
    """Return a deterministic Alpaca client order id for one certificate."""

    # Alpaca limits client_order_id to 48 characters.  UUID.hex retains the
    # full 128-bit certificate identity while avoiding the UUID separators.
    return f"lexguard-entry-{certificate_id.hex}"


class DuplicateDecisionWindow(RuntimeError):
    """Raised when a second case attempts to claim a decision window."""


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if any(
                token in str(key).lower()
                for token in (
                    "secret",
                    "authorization",
                    "token",
                    "password",
                    "api_key",
                    "access_key",
                    "private_key",
                )
            )
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def _payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _redact(payload), sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Normalize drivers that drop timezone metadata on timestamp reads."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _observation_field(observation: Any, key: str, default: Any = None) -> Any:
    if isinstance(observation, Mapping):
        return observation.get(key, default)
    return getattr(observation, key, default)


class CaseRepository:
    def __init__(self, database_url: str) -> None:
        # A shared in-memory connection keeps offline API tests deterministic across
        # FastAPI's request worker thread; production URLs retain normal pooling.
        options: dict[str, Any] = {"future": True}
        if database_url == "sqlite://":
            options.update(
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        self.engine = create_engine(database_url, **options)

    def clock(self) -> datetime:
        return datetime.now(UTC)

    def database_health(self) -> str:
        """Return truthful Alembic/schema readiness without creating or altering tables."""

        try:
            with self.engine.connect() as connection:
                tables = set(inspect(connection).get_table_names())
                required_tables = set(REQUIRED_SCHEMA_COLUMNS) | {"alembic_version"}
                if required_tables - tables:
                    return "migration_required"
                for table, required_columns in REQUIRED_SCHEMA_COLUMNS.items():
                    columns = {
                        str(column["name"])
                        for column in inspect(connection).get_columns(table)
                    }
                    if required_columns - columns:
                        return "migration_required"
                revisions = tuple(
                    str(value)
                    for value in connection.execute(text("SELECT version_num FROM alembic_version"))
                    for value in value
                )
                if revisions != (ALEMBIC_HEAD,):
                    return "migration_required"
                connection.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - health probes must never leak driver details
            return "unavailable"
        return "healthy"

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def create_scheduled(
        self,
        trading_date: date,
        decision_window: str,
        *,
        underlying: str | None = None,
        case_id: UUID | None = None,
        now: datetime | None = None,
    ) -> CaseRead:
        case_uuid = case_id or uuid4()
        timestamp = now or self.clock()
        row = CaseRow(
            case_id=str(case_uuid),
            trading_date=trading_date,
            decision_window=decision_window,
            state=CaseState.SCHEDULED.value,
            underlying=underlying,
            created_at=timestamp,
            updated_at=timestamp,
        )
        try:
            with Session(self.engine) as session, session.begin():
                session.add(row)
                session.flush()
        except IntegrityError as exc:
            raise DuplicateDecisionWindow(
                f"case already exists for {trading_date.isoformat()} {decision_window}"
            ) from exc
        return CaseRead(case_uuid, trading_date, decision_window, CaseState.SCHEDULED, underlying)

    @staticmethod
    def _append_event_in_session(
        session: Session,
        case_id: UUID,
        event: CaseEventType,
        payload: Mapping[str, Any] | None,
        occurred_at: datetime,
    ) -> CaseRead:
        event_payload = _redact(payload or {})
        row = session.get(CaseRow, str(case_id))
        if row is None:
            raise KeyError(f"unknown case {case_id}")
        current = CaseState(row.state)
        next_state = transition(current, event)
        session.add(
            CaseEventRow(
                case_id=str(case_id),
                event_type=event.value,
                from_state=current.value,
                to_state=next_state.value,
                occurred_at=occurred_at,
                payload_hash=_payload_hash(event_payload),
                payload_json=event_payload,
            )
        )
        row.state = next_state.value
        row.updated_at = occurred_at
        session.flush()
        return CaseRead(
            UUID(row.case_id), row.trading_date, row.decision_window, next_state, row.underlying
        )

    def append_event(
        self,
        case_id: UUID,
        event: CaseEventType,
        payload: Mapping[str, Any] | None = None,
        *,
        occurred_at: datetime | None = None,
    ) -> CaseRead:
        timestamp = occurred_at or self.clock()
        with Session(self.engine) as session, session.begin():
            return self._append_event_in_session(session, case_id, event, payload, timestamp)

    @staticmethod
    def _save_artifact_in_session(
        session: Session,
        case_id: UUID,
        artifact_type: str,
        payload: Mapping[str, Any],
        content_hash: str | None,
        created_at: datetime,
    ) -> str:
        safe_payload = _redact(payload)
        artifact_hash = content_hash or _payload_hash(safe_payload)
        if session.get(CaseRow, str(case_id)) is None:
            raise KeyError(f"unknown case {case_id}")
        session.add(
            ArtifactRow(
                case_id=str(case_id),
                artifact_type=artifact_type,
                content_hash=artifact_hash,
                payload_json=safe_payload,
                created_at=created_at,
            )
        )
        return artifact_hash

    def save_artifact(
        self,
        case_id: UUID,
        artifact_type: str,
        payload: Mapping[str, Any],
        *,
        content_hash: str | None = None,
        created_at: datetime | None = None,
    ) -> str:
        with Session(self.engine) as session, session.begin():
            return self._save_artifact_in_session(
                session,
                case_id,
                artifact_type,
                payload,
                content_hash,
                created_at or self.clock(),
            )

    def acquire_window_lease(
        self,
        trading_date: date,
        decision_window: str,
        owner: str,
        *,
        now: datetime | None = None,
        ttl: timedelta = timedelta(minutes=2),
    ) -> bool:
        timestamp = now or self.clock()
        try:
            with Session(self.engine) as session, session.begin():
                row = session.scalar(
                    select(LeaseRow)
                    .where(
                        LeaseRow.trading_date == trading_date,
                        LeaseRow.decision_window == decision_window,
                    )
                    .with_for_update(skip_locked=True)
                )
                if row is not None and _as_utc(row.lease_until) > timestamp:
                    return False
                if row is None:
                    session.add(
                        LeaseRow(
                            trading_date=trading_date,
                            decision_window=decision_window,
                            owner=owner,
                            acquired_at=timestamp,
                            lease_until=timestamp + ttl,
                        )
                    )
                else:
                    row.owner = owner
                    row.acquired_at = timestamp
                    row.lease_until = timestamp + ttl
                session.flush()
                return True
        except IntegrityError:
            return False

    def get_case(self, case_id: UUID) -> CaseRead:
        with Session(self.engine) as session:
            row = session.get(CaseRow, str(case_id))
            if row is None:
                raise KeyError(f"unknown case {case_id}")
            return CaseRead(
                UUID(row.case_id),
                row.trading_date,
                row.decision_window,
                CaseState(row.state),
                row.underlying,
            )

    def list_ledger_cases(
        self, offset: int, limit: int
    ) -> tuple[tuple[LedgerCaseRecord, ...], bool]:
        """Read a stable, newest-first page from the durable ledger without mutation."""

        with Session(self.engine) as session:
            rows = session.scalars(
                select(CaseRow)
                .order_by(
                    CaseRow.trading_date.desc(),
                    CaseRow.decision_window.desc(),
                    CaseRow.created_at.desc(),
                )
                .offset(offset)
                .limit(limit + 1)
            ).all()
            page, has_more = rows[:limit], len(rows) > limit
            return tuple(self._ledger_case_record(session, row) for row in page), has_more

    def ledger_case(self, case_id: UUID) -> LedgerCaseRecord | None:
        """Read one durable case and all of its immutable artifacts."""

        with Session(self.engine) as session:
            row = session.get(CaseRow, str(case_id))
            return self._ledger_case_record(session, row) if row is not None else None

    def latest_artifact(self, artifact_type: str) -> tuple[dict[str, Any], str, datetime] | None:
        """Return the latest persisted artifact of a public projection type."""

        with Session(self.engine) as session:
            row = session.scalar(
                select(ArtifactRow)
                .where(ArtifactRow.artifact_type == artifact_type)
                .order_by(ArtifactRow.created_at.desc(), ArtifactRow.artifact_id.desc())
            )
            if row is None:
                return None
            return dict(row.payload_json), row.content_hash, _as_utc(row.created_at)

    def artifacts_by_type(
        self, artifact_type: str, *, limit: int = 500
    ) -> tuple[tuple[dict[str, Any], str, datetime], ...]:
        """Return the newest artifacts of one type in ascending time order."""

        with Session(self.engine) as session:
            rows = session.scalars(
                select(ArtifactRow)
                .where(ArtifactRow.artifact_type == artifact_type)
                .order_by(ArtifactRow.created_at.desc(), ArtifactRow.artifact_id.desc())
                .limit(limit)
            ).all()
            return tuple(
                (dict(row.payload_json), row.content_hash, _as_utc(row.created_at))
                for row in reversed(rows)
            )

    def operator_veto_exists(self, case_id: UUID) -> bool:
        """True when an operator vetoed this case's pending certificate."""

        with Session(self.engine) as session:
            row = session.scalar(
                select(ArtifactRow).where(
                    ArtifactRow.case_id == str(case_id),
                    ArtifactRow.artifact_type == "operator_veto",
                )
            )
            return row is not None

    SYSTEM_DECISION_WINDOW = "SYSTEM"

    def get_or_create_system_case(
        self, trading_date: date, *, now: datetime | None = None
    ) -> CaseRead:
        """Return the per-day SYSTEM case that anchors runtime artifacts.

        Runtime state (risk state, performance snapshots) is ledger data, and
        every artifact row requires an owning case; SYSTEM cases never leave
        the SCHEDULED state and are filtered out of public case projections.
        """

        try:
            return self.create_scheduled(
                trading_date, self.SYSTEM_DECISION_WINDOW, now=now
            )
        except DuplicateDecisionWindow:
            with Session(self.engine) as session:
                row = session.scalar(
                    select(CaseRow).where(
                        CaseRow.trading_date == trading_date,
                        CaseRow.decision_window == self.SYSTEM_DECISION_WINDOW,
                    )
                )
                if row is None:  # pragma: no cover - duplicate implies existence
                    raise
                return CaseRead(
                    UUID(row.case_id),
                    row.trading_date,
                    row.decision_window,
                    CaseState(row.state),
                    row.underlying,
                )

    def save_runtime_artifact(
        self,
        trading_date: date,
        artifact_type: str,
        payload: Mapping[str, Any],
        *,
        content_hash: str | None = None,
        now: datetime | None = None,
    ) -> str:
        """Persist a runtime artifact under the day's SYSTEM case."""

        case = self.get_or_create_system_case(trading_date, now=now)
        return self.save_artifact(
            case.case_id,
            artifact_type,
            payload,
            content_hash=content_hash,
            created_at=now,
        )

    def ledger_events_since(self, last_event_id: int) -> tuple[LedgerEventRecord, ...]:
        """Return strictly increasing append-only events after an SSE cursor."""

        with Session(self.engine) as session:
            rows = session.scalars(
                select(CaseEventRow)
                .where(CaseEventRow.event_id > last_event_id)
                .order_by(CaseEventRow.event_id.asc())
            ).all()
            return tuple(
                LedgerEventRecord(
                    event_id=row.event_id,
                    case_id=UUID(row.case_id),
                    event_type=row.event_type,
                    occurred_at=_as_utc(row.occurred_at),
                    payload=dict(row.payload_json),
                )
                for row in rows
            )

    def order_events_for_cases(
        self, case_ids: Sequence[UUID]
    ) -> tuple[LedgerOrderEventRecord, ...]:
        """Return broker observations for the requested cases in ledger order."""

        if not case_ids:
            return ()
        with Session(self.engine) as session:
            rows = session.scalars(
                select(OrderEventRow)
                .where(OrderEventRow.case_id.in_([str(case_id) for case_id in case_ids]))
                .order_by(OrderEventRow.order_event_id.asc())
            ).all()
            return tuple(
                LedgerOrderEventRecord(
                    order_event_id=row.order_event_id,
                    case_id=UUID(row.case_id),
                    alpaca_order_id=row.alpaca_order_id,
                    occurred_at=_as_utc(row.occurred_at),
                    payload=dict(row.payload_json),
                )
                for row in rows
            )

    def latest_ledger_time(self) -> datetime | None:
        """Return the latest case update time for an honest projection timestamp."""

        with Session(self.engine) as session:
            row = session.scalar(select(CaseRow.updated_at).order_by(CaseRow.updated_at.desc()))
            return _as_utc(row) if row is not None else None

    @staticmethod
    def _ledger_case_record(session: Session, row: CaseRow) -> LedgerCaseRecord:
        artifacts = session.scalars(
            select(ArtifactRow)
            .where(ArtifactRow.case_id == row.case_id)
            .order_by(ArtifactRow.artifact_id.asc())
        ).all()
        by_type: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            # The newest entry of a type is the authoritative immutable artifact.
            by_type[artifact.artifact_type] = {
                **dict(artifact.payload_json),
                "content_hash": artifact.content_hash,
                "created_at": _as_utc(artifact.created_at).isoformat(),
            }
        return LedgerCaseRecord(
            case_id=UUID(row.case_id),
            trading_date=row.trading_date,
            decision_window=row.decision_window,
            state=row.state,
            underlying=row.underlying,
            updated_at=_as_utc(row.updated_at),
            artifacts=by_type,
            environment=next(
                (
                    str(payload["environment"])
                    for payload in by_type.values()
                    if isinstance(payload, Mapping) and payload.get("environment")
                ),
                None,
            ),
        )

    def daily_entry_state(self, trading_date: date) -> DailyEntryState:
        """Return the executed-entry count and symbols from the durable ledger."""

        entry_states = (
            CaseState.SUBMITTED.value,
            CaseState.MANAGING.value,
            CaseState.CLOSED.value,
        )
        with Session(self.engine) as session:
            rows = session.scalars(
                select(CaseRow).where(
                    CaseRow.trading_date == trading_date,
                    CaseRow.state.in_(entry_states),
                )
            ).all()
        symbols = tuple(sorted({row.underlying for row in rows if row.underlying is not None}))
        return DailyEntryState(entries_today=len(rows), traded_symbols_today=symbols)

    def expected_broker_state(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Load expected working orders and positions from persisted observations.

        A scheduler restart must compare broker truth with the last durable
        observation, rather than treating an empty in-memory process as an
        empty account.  The newest observation for each broker order ID is
        authoritative.  Filled/partially-filled entry observations bind the
        expected position symbols to the case's persisted certificate.
        """

        active_statuses = BROKER_ACTIVE_ORDER_STATES
        with Session(self.engine) as session:
            rows = session.scalars(
                select(OrderEventRow).order_by(OrderEventRow.order_event_id.asc())
            ).all()
            latest: dict[str, OrderEventRow] = {}
            for row in rows:
                latest[row.alpaca_order_id] = row
            expected_orders = tuple(
                sorted(
                    order_id
                    for order_id, row in latest.items()
                    if str(row.payload_json.get("status", "")).upper() in active_statuses
                )
            )
            for intent in session.scalars(
                select(CloseIntentRow).where(
                    CloseIntentRow.state.not_in(("CLOSED", "REJECTED", "CANCELED"))
                )
            ):
                if intent.order_id:
                    expected_orders = tuple(sorted(set(expected_orders) | {intent.order_id}))
            position_state = self._expected_position_state(session, latest)
        return expected_orders, tuple(sorted(position_state))

    def expected_broker_position_state(self) -> dict[str, int]:
        """Return signed expected option quantities reconstructed from the ledger."""

        with Session(self.engine) as session:
            rows = session.scalars(
                select(OrderEventRow).order_by(OrderEventRow.order_event_id.asc())
            ).all()
            latest: dict[str, OrderEventRow] = {}
            for row in rows:
                latest[row.alpaca_order_id] = row
            return self._expected_position_state(session, latest)

    @staticmethod
    def _expected_position_state(
        session: Session, latest: Mapping[str, OrderEventRow]
    ) -> dict[str, int]:
        state: dict[str, int] = {}
        fill_statuses = set(BROKER_FILLED_ORDER_STATES) | {
            "PARTIALLY_FILLED",
            "PARTIAL_FILLED",
        }
        for row in latest.values():
            payload = row.payload_json
            if str(payload.get("status", "")).upper() not in fill_statuses and not int(
                payload.get("filled_quantity", 0) or 0
            ):
                continue
            quantities = payload.get("signed_quantities", {})
            if isinstance(quantities, Mapping) and quantities:
                for symbol, quantity in quantities.items():
                    try:
                        state[str(symbol)] = state.get(str(symbol), 0) + int(quantity)
                    except (TypeError, ValueError):
                        continue
            elif (row.role or str(payload.get("role", "entry"))) == "entry":
                for symbol, quantity in CaseRepository._entry_signed_quantities(
                    session, row.case_id, payload
                ).items():
                    state[symbol] = state.get(symbol, 0) + quantity
        return {symbol: quantity for symbol, quantity in state.items() if quantity}

    @staticmethod
    def _entry_signed_quantities(
        session: Session, case_id: str, payload: Mapping[str, Any]
    ) -> dict[str, int]:
        certificate = session.scalar(
            select(ArtifactRow)
            .where(
                ArtifactRow.case_id == case_id,
                ArtifactRow.artifact_type == "trade_certificate",
            )
            .order_by(ArtifactRow.artifact_id.desc())
        )
        if certificate is None:
            return {}
        candidate = certificate.payload_json.get("candidate", {})
        legs = candidate.get("legs", ()) if isinstance(candidate, Mapping) else ()
        quantity = int(payload.get("filled_quantity", 0) or 0)
        return {
            str(leg["symbol"]): quantity * (1 if str(leg.get("side", "")).upper() == "BUY" else -1)
            for leg in legs
            if isinstance(leg, Mapping) and leg.get("symbol")
        }

    def get_entry_intent(self, intent_key: str) -> EntryIntentRecord | None:
        with Session(self.engine) as session:
            row = session.get(EntryIntentRow, intent_key)
            return self._entry_intent_record(row) if row is not None else None

    def create_or_claim_entry_intent(
        self,
        intent_key: str,
        case_id: UUID,
        certificate_id: UUID,
        deadline_at: datetime,
        *,
        owner: str,
        client_order_id: str | None = None,
        now: datetime | None = None,
        lease_ttl: timedelta = timedelta(minutes=2),
        claim_token: str | None = None,
    ) -> EntryIntentClaim:
        """Claim the pre-submit entry intent in one transaction."""

        if not intent_key or not owner:
            raise ValueError("entry intent key and owner are required")
        timestamp = now or self.clock()
        token = claim_token or f"{owner}:{uuid4().hex}"
        order_client_id = client_order_id or entry_client_order_id(certificate_id)
        with Session(self.engine) as session, session.begin():
            row = session.get(EntryIntentRow, intent_key, with_for_update=True)
            if row is None:
                row = EntryIntentRow(
                    intent_key=intent_key,
                    case_id=str(case_id),
                    certificate_id=str(certificate_id),
                    client_order_id=order_client_id,
                    state="INTENT",
                    order_ids_json=[],
                    deadline_at=deadline_at,
                    lease_owner=owner,
                    lease_until=timestamp + lease_ttl,
                    claim_token=token,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                session.flush()
                return EntryIntentClaim(self._entry_intent_record(row), True, True)
            active = row.state not in {"FILLED", "CANCELED", "REJECTED"}
            expired = row.lease_until is None or _as_utc(row.lease_until) <= timestamp
            owns = row.lease_owner == owner and row.claim_token == claim_token
            if active and (owns or expired):
                row.lease_owner = owner
                row.lease_until = timestamp + lease_ttl
                row.claim_token = token
                row.updated_at = timestamp
                return EntryIntentClaim(self._entry_intent_record(row), True, False)
            return EntryIntentClaim(self._entry_intent_record(row), False, False)

    def update_entry_intent(
        self,
        intent_key: str,
        *,
        state: str,
        order_ids: Sequence[str] = (),
        now: datetime | None = None,
        deadline_at: datetime | None = None,
        claim_token: str | None = None,
    ) -> EntryIntentRecord:
        timestamp = now or self.clock()
        with Session(self.engine) as session, session.begin():
            row = session.get(EntryIntentRow, intent_key, with_for_update=True)
            if row is None:
                raise KeyError(f"unknown entry intent {intent_key}")
            if row.claim_token is not None and row.claim_token != claim_token:
                raise RuntimeError("entry intent compare-and-swap failed")
            row.state = state
            if order_ids:
                row.order_ids_json = list(dict.fromkeys(str(item) for item in order_ids))
            if deadline_at is not None:
                row.deadline_at = deadline_at
            row.updated_at = timestamp
            row.lease_owner = None
            row.lease_until = None
            return self._entry_intent_record(row)

    @staticmethod
    def _entry_intent_record(row: EntryIntentRow) -> EntryIntentRecord:
        return EntryIntentRecord(
            intent_key=row.intent_key,
            case_id=UUID(row.case_id),
            certificate_id=UUID(row.certificate_id),
            client_order_id=row.client_order_id,
            state=row.state,
            order_ids=tuple(str(value) for value in (row.order_ids_json or [])),
            deadline_at=_as_utc(row.deadline_at),
            created_at=_as_utc(row.created_at),
            updated_at=_as_utc(row.updated_at),
            lease_owner=row.lease_owner,
            lease_until=_as_utc(row.lease_until) if row.lease_until is not None else None,
            claim_token=row.claim_token,
        )

    def get_close_intent(self, intent_key: str) -> CloseIntentRecord | None:
        with Session(self.engine) as session:
            row = session.get(CloseIntentRow, intent_key)
            return self._close_intent_record(row) if row is not None else None

    def create_or_claim_close_intent(
        self,
        intent_key: str,
        symbols: tuple[str, ...],
        reason: str,
        *,
        owner: str,
        now: datetime | None = None,
        lease_ttl: timedelta = timedelta(minutes=2),
        case_id: UUID | None = None,
        claim_token: str | None = None,
        signed_quantities: Mapping[str, int] | None = None,
        deadline_at: datetime | None = None,
        client_order_id: str | None = None,
    ) -> CloseIntentClaim:
        """Atomically claim one close intent so restarts cannot duplicate it."""

        if not intent_key or not owner:
            raise ValueError("close intent key and owner are required")
        timestamp = now or self.clock()
        token = claim_token or f"{owner}:{uuid4().hex}"
        with Session(self.engine) as session, session.begin():
            row = session.get(CloseIntentRow, intent_key, with_for_update=True)
            if row is None:
                row = CloseIntentRow(
                    intent_key=intent_key,
                    case_id=str(case_id) if case_id is not None else None,
                    symbols_json=list(symbols),
                    signed_quantities_json=dict(signed_quantities or {}),
                    reason=reason,
                    order_id=None,
                    state="INTENT",
                    role="close",
                    deadline_at=deadline_at,
                    client_order_id=client_order_id,
                    lease_owner=owner,
                    lease_until=timestamp + lease_ttl,
                    claim_token=token,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                session.flush()
                return CloseIntentClaim(self._close_intent_record(row), True, True)
            active = row.state not in {"CLOSED", "REJECTED", "CANCELED"}
            expired = row.lease_until is None or _as_utc(row.lease_until) <= timestamp
            owns = row.lease_owner == owner and row.claim_token == claim_token
            if active and (owns or expired):
                row.lease_owner = owner
                row.lease_until = timestamp + lease_ttl
                row.claim_token = token
                row.updated_at = timestamp
                if row.case_id is None and case_id is not None:
                    row.case_id = str(case_id)
                if deadline_at is not None and row.deadline_at is None:
                    row.deadline_at = deadline_at
                if client_order_id is not None and row.client_order_id is None:
                    row.client_order_id = client_order_id
                return CloseIntentClaim(self._close_intent_record(row), True, False)
            return CloseIntentClaim(self._close_intent_record(row), False, False)

    def create_close_intent(
        self,
        intent_key: str,
        symbols: tuple[str, ...],
        reason: str,
        *,
        now: datetime | None = None,
        case_id: UUID | None = None,
        signed_quantities: Mapping[str, int] | None = None,
        deadline_at: datetime | None = None,
        client_order_id: str | None = None,
    ) -> CloseIntentRecord:
        """Compatibility wrapper for callers that do not require leasing."""

        timestamp = now or self.clock()
        with Session(self.engine) as session, session.begin():
            row = session.get(CloseIntentRow, intent_key)
            if row is None:
                row = CloseIntentRow(
                    intent_key=intent_key,
                    case_id=str(case_id) if case_id is not None else None,
                    symbols_json=list(symbols),
                    signed_quantities_json=dict(signed_quantities or {}),
                    reason=reason,
                    order_id=None,
                    state="INTENT",
                    role="close",
                    deadline_at=deadline_at,
                    client_order_id=client_order_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                session.flush()
            return self._close_intent_record(row)

    def update_close_intent(
        self,
        intent_key: str,
        *,
        state: str,
        now: datetime | None = None,
        order_id: str | None = None,
        claim_token: str | None = None,
    ) -> CloseIntentRecord:
        timestamp = now or self.clock()
        with Session(self.engine) as session, session.begin():
            row = session.get(CloseIntentRow, intent_key, with_for_update=True)
            if row is None:
                raise KeyError(f"unknown close intent {intent_key}")
            if row.claim_token is not None and row.claim_token != claim_token:
                raise RuntimeError("close intent compare-and-swap failed")
            row.state = state
            if order_id is not None:
                row.order_id = order_id
            row.updated_at = timestamp
            row.lease_owner = None
            row.lease_until = None
            return self._close_intent_record(row)

    def active_close_intents(self) -> tuple[CloseIntentRecord, ...]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(CloseIntentRow)
                .where(CloseIntentRow.state.not_in(("CLOSED", "REJECTED", "CANCELED")))
                .order_by(CloseIntentRow.created_at.asc())
            ).all()
            return tuple(self._close_intent_record(row) for row in rows)

    def resolve_position_case_id(self, symbols: Sequence[str]) -> UUID | None:
        """Resolve an open position structure to its uniquely filled case."""

        wanted = {str(symbol) for symbol in symbols}
        if not wanted:
            return None
        with Session(self.engine) as session:
            rows = session.scalars(
                select(OrderEventRow).order_by(OrderEventRow.order_event_id.asc())
            ).all()
            latest: dict[str, OrderEventRow] = {}
            for row in rows:
                latest[row.alpaca_order_id] = row
            candidates = {
                row.case_id
                for row in latest.values()
                if str(row.payload_json.get("status", "")).upper()
                in {"FILLED", "PARTIALLY_FILLED", "PARTIAL_FILLED"}
                or int(row.payload_json.get("filled_quantity", 0) or 0) > 0
            }
            matches: set[str] = set()
            for case_id in candidates:
                artifact = session.scalar(
                    select(ArtifactRow)
                    .where(
                        ArtifactRow.case_id == case_id,
                        ArtifactRow.artifact_type == "trade_certificate",
                    )
                    .order_by(ArtifactRow.artifact_id.desc())
                )
                if artifact is None:
                    continue
                candidate = artifact.payload_json.get("candidate", {})
                legs = candidate.get("legs", ()) if isinstance(candidate, Mapping) else ()
                projected = {
                    str(leg["symbol"])
                    for leg in legs
                    if isinstance(leg, Mapping) and leg.get("symbol")
                }
                if projected == wanted:
                    matches.add(case_id)
            return UUID(next(iter(matches))) if len(matches) == 1 else None

    def record_close_result(self, result: Any) -> CaseRead | None:
        """Persist a close observation and advance the owning case safely."""

        if str(getattr(result, "state", "")) == "PENDING_OWNER":
            return None
        case_id = getattr(result, "case_id", None)
        if case_id is None:
            return None
        current = self.get_case(case_id)
        state = str(getattr(result, "state", "RECONCILE_REQUIRED"))
        timestamp = self.clock()
        if state == "CLOSED":
            if current.state is CaseState.SUBMITTED:
                current = self.append_event(
                    case_id,
                    CaseEventType.MANAGING,
                    {"reason": getattr(result, "reason", "")},
                    occurred_at=timestamp,
                )
            if current.state is CaseState.MANAGING:
                current = self.append_event(
                    case_id,
                    CaseEventType.CLOSED,
                    {
                        "reason": getattr(result, "reason", ""),
                        "alpaca_order_id": getattr(result, "order_id", None),
                    },
                    occurred_at=timestamp,
                )
        elif state == "MANAGING" and current.state is CaseState.SUBMITTED:
            current = self.append_event(
                case_id,
                CaseEventType.MANAGING,
                {"reason": getattr(result, "reason", "")},
                occurred_at=timestamp,
            )
        elif state in {"RECONCILE_REQUIRED", "REJECTED"} and current.state not in {
            CaseState.CLOSED,
            CaseState.HALTED,
            CaseState.REFUSED,
        }:
            current = self.append_event(
                case_id,
                CaseEventType.HALTED,
                {
                    "reason": f"CLOSE_{state}",
                    "alpaca_order_id": getattr(result, "order_id", None),
                },
                occurred_at=timestamp,
            )
        observation = getattr(result, "order_observation", None)
        order_id = str(getattr(result, "order_id", "") or "")
        if order_id:
            average_fill_price = getattr(observation, "average_fill_price", None)
            payload = {
                "state": state,
                "status": str(getattr(observation, "status", state)),
                "filled_quantity": int(getattr(observation, "filled_quantity", 0)),
                "average_fill_price": (
                    str(average_fill_price)
                    if average_fill_price is not None
                    else None
                ),
                "role": "close",
                "signed_quantities": dict(
                    getattr(result, "signed_quantities", {}) or {}
                ),
                "deadline_at": str(getattr(result, "deadline_at", "")) or None,
                "client_order_id": getattr(result, "client_order_id", None),
            }
            with Session(self.engine) as session, session.begin():
                session.add(
                    OrderEventRow(
                        case_id=str(case_id),
                        alpaca_order_id=order_id,
                        payload_hash=_payload_hash(payload),
                        payload_json=_redact(payload),
                        occurred_at=timestamp,
                        role="close",
                        signed_quantities_json={
                            str(key): int(value)
                            for key, value in (
                                getattr(result, "signed_quantities", {}) or {}
                            ).items()
                        },
                        deadline_at=getattr(result, "deadline_at", None),
                        client_order_id=getattr(result, "client_order_id", None),
                    )
                )
        return current

    @staticmethod
    def _close_intent_record(row: CloseIntentRow) -> CloseIntentRecord:
        return CloseIntentRecord(
            intent_key=row.intent_key,
            case_id=UUID(row.case_id) if row.case_id is not None else None,
            symbols=tuple(str(value) for value in row.symbols_json),
            reason=row.reason,
            order_id=row.order_id,
            state=row.state,
            created_at=_as_utc(row.created_at),
            updated_at=_as_utc(row.updated_at),
            lease_owner=row.lease_owner,
            lease_until=_as_utc(row.lease_until) if row.lease_until is not None else None,
            claim_token=row.claim_token,
            signed_quantities={
                str(symbol): int(quantity)
                for symbol, quantity in (row.signed_quantities_json or {}).items()
            },
            deadline_at=_as_utc(row.deadline_at) if row.deadline_at is not None else None,
            client_order_id=row.client_order_id,
        )

    def active_entry_order_chains(self) -> tuple[dict[str, Any], ...]:
        """Return persisted order chains that may need polling after restart."""

        with Session(self.engine) as session:
            rows = session.scalars(
                select(OrderEventRow).order_by(OrderEventRow.order_event_id.asc())
            ).all()
            latest: dict[str, OrderEventRow] = {}
            for row in rows:
                latest[row.alpaca_order_id] = row
            by_certificate: dict[str, list[str]] = {}
            for order_id, row in latest.items():
                if (row.role or str(row.payload_json.get("role", "entry"))) != "entry":
                    continue
                certificate_id = row.payload_json.get("certificate_id")
                if certificate_id:
                    by_certificate.setdefault(str(certificate_id), []).append(order_id)
            certificates = session.scalars(
                select(ArtifactRow).where(ArtifactRow.artifact_type == "trade_certificate")
            ).all()
            chains: dict[str, dict[str, Any]] = {}
            for intent in session.scalars(
                select(EntryIntentRow).where(
                    EntryIntentRow.state.not_in(("FILLED", "CANCELED", "REJECTED"))
                )
            ):
                artifact = next(
                    (
                        item
                        for item in reversed(certificates)
                        if str(item.payload_json.get("certificate_id")) == intent.certificate_id
                    ),
                    None,
                )
                case = session.get(CaseRow, intent.case_id)
                if artifact is None or case is None or case.state not in {
                    CaseState.CERTIFIED.value,
                    CaseState.SUBMITTED.value,
                }:
                    continue
                chains[intent.certificate_id] = {
                    "case_id": UUID(case.case_id),
                    "certificate_id": UUID(intent.certificate_id),
                    "order_ids": tuple(dict.fromkeys(intent.order_ids_json or [])),
                    "client_order_id": intent.client_order_id,
                    "deadline_at": (
                        _as_utc(intent.deadline_at)
                        if intent.deadline_at is not None
                        else _as_utc(intent.created_at) + LEGACY_ORDER_DEADLINE
                    ),
                    "certificate": dict(artifact.payload_json),
                }
            for certificate_id, order_ids in by_certificate.items():
                chain = chains.get(certificate_id)
                artifact = next(
                    (
                        item
                        for item in reversed(certificates)
                        if str(item.payload_json.get("certificate_id")) == certificate_id
                    ),
                    None,
                )
                if artifact is None:
                    continue
                case = session.get(CaseRow, artifact.case_id)
                if case is None or case.state not in {
                    CaseState.CERTIFIED.value,
                    CaseState.SUBMITTED.value,
                }:
                    continue
                latest_deadline = next(
                    (
                        row.deadline_at
                        for order_id in reversed(order_ids)
                        if (row := latest[order_id]).deadline_at is not None
                    ),
                    None,
                )
                if latest_deadline is None:
                    # Legacy order rows have no deadline column.  Derive one
                    # from the earliest durable observation so repeated
                    # restart polls cannot extend an order indefinitely.
                    latest_deadline = min(
                        _as_utc(latest[order_id].occurred_at) for order_id in order_ids
                    ) + LEGACY_ORDER_DEADLINE
                if chain is None:
                    chains[certificate_id] = {
                        "case_id": UUID(case.case_id),
                        "certificate_id": UUID(certificate_id),
                        "order_ids": tuple(sorted(order_ids)),
                        "client_order_id": next(
                            (
                                latest[order_id].client_order_id
                                for order_id in order_ids
                                if latest[order_id].client_order_id
                            ),
                            None,
                        ),
                        "deadline_at": latest_deadline,
                        "certificate": dict(artifact.payload_json),
                    }
                else:
                    chain["order_ids"] = tuple(
                        dict.fromkeys((*chain["order_ids"], *order_ids))
                    )
            return tuple(chains.values())

    def pending_certificate(
        self, trading_date: date, decision_window: str
    ) -> TradeCertificate | None:
        """Load one persisted, not-yet-submitted certificate for scheduler execution."""

        from lexguard.domain.models import TradeCertificate

        with Session(self.engine) as session:
            case = session.scalar(
                select(CaseRow).where(
                    CaseRow.trading_date == trading_date,
                    CaseRow.decision_window == decision_window,
                    CaseRow.state == CaseState.CERTIFIED.value,
                )
            )
            if case is None:
                return None
            artifact = session.scalar(
                select(ArtifactRow)
                .where(
                    ArtifactRow.case_id == case.case_id,
                    ArtifactRow.artifact_type == "trade_certificate",
                )
                .order_by(ArtifactRow.artifact_id.desc())
            )
            if artifact is None:
                return None
            return TradeCertificate.model_validate(artifact.payload_json)

    def record_execution(self, record: Any) -> CaseRead:
        """Persist an execution outcome and project only legal case events.

        Polling a replacement or fill is not a second submission event.  The
        case is advanced to ``SUBMITTED`` once, then to ``MANAGING`` only when
        a filled order has been observed.  Rejected, canceled, and ambiguous
        outcomes halt the case and remain safe across repeated retries.
        """

        with Session(self.engine) as session, session.begin():
            row = session.get(CaseRow, str(record.case_id), with_for_update=True)
            if row is None:
                raise KeyError(f"unknown case {record.case_id}")
            self._save_order_events(record, session=session)
            self._save_artifact_in_session(
                session,
                record.case_id,
                "execution_record",
                self._record_payload(record),
                None,
                record.updated_at,
            )
            state = str(record.state)
            intent = session.scalar(
                select(EntryIntentRow).where(
                    EntryIntentRow.case_id == str(record.case_id),
                    EntryIntentRow.certificate_id == str(record.certificate_id),
                )
            )
            if intent is not None:
                intent.order_ids_json = list(
                    dict.fromkeys(str(value) for value in record.alpaca_order_ids)
                ) or intent.order_ids_json
                intent.state = {
                    "FILLED": "FILLED",
                    "CANCELED": "CANCELED",
                    "REJECTED": "REJECTED",
                }.get(state, "SUBMITTED")
                intent.updated_at = record.updated_at
                intent.lease_owner = None
                intent.lease_until = None
            current = CaseState(row.state)
            if state in {"SUBMITTED", "REPLACED"}:
                if current is CaseState.CERTIFIED:
                    return self._append_event_in_session(
                        session,
                        record.case_id,
                        CaseEventType.SUBMITTED,
                        {"alpaca_order_ids": record.alpaca_order_ids, "state": state},
                        record.updated_at,
                    )
                return CaseRead(
                    UUID(row.case_id),
                    row.trading_date,
                    row.decision_window,
                    current,
                    row.underlying,
                )
            if state == "FILLED":
                if current is CaseState.CERTIFIED:
                    current_read = self._append_event_in_session(
                        session,
                        record.case_id,
                        CaseEventType.SUBMITTED,
                        {"alpaca_order_ids": record.alpaca_order_ids, "state": state},
                        record.updated_at,
                    )
                    current = current_read.state
                if current is CaseState.SUBMITTED:
                    return self._append_event_in_session(
                        session,
                        record.case_id,
                        CaseEventType.MANAGING,
                        {"alpaca_order_ids": record.alpaca_order_ids, "state": state},
                        record.updated_at,
                    )
                return CaseRead(
                    UUID(row.case_id),
                    row.trading_date,
                    row.decision_window,
                    current,
                    row.underlying,
                )
            if state in {"RECONCILE_REQUIRED", "REJECTED", "CANCELED"}:
                if current not in {CaseState.CLOSED, CaseState.HALTED, CaseState.REFUSED}:
                    return self._append_event_in_session(
                        session,
                        record.case_id,
                        CaseEventType.HALTED,
                        {
                            "reason": f"EXECUTION_{state}",
                            "alpaca_order_ids": record.alpaca_order_ids,
                        },
                        record.updated_at,
                    )
            return CaseRead(
                UUID(row.case_id),
                row.trading_date,
                row.decision_window,
                current,
                row.underlying,
            )

    def record_entry_observation(self, record: Any) -> CaseRead:
        """Persist a restart poll without replaying a submission transition."""

        return self.record_execution(record)

    @staticmethod
    def _record_payload(record: Any) -> dict[str, Any]:
        dump = getattr(record, "model_dump", None)
        if callable(dump):
            payload = dump(mode="json")
            return dict(payload) if isinstance(payload, Mapping) else {}
        return {
            "case_id": str(record.case_id),
            "certificate_id": str(record.certificate_id),
            "alpaca_order_ids": list(record.alpaca_order_ids),
            "state": str(record.state),
            "submitted_at": str(record.submitted_at),
            "updated_at": str(record.updated_at),
            "filled_quantity": int(record.filled_quantity),
        }

    def _save_order_events(self, record: Any, *, session: Session | None = None) -> None:
        """Append every normalized broker observation to the lifecycle ledger."""

        order_ids = tuple(str(value) for value in getattr(record, "alpaca_order_ids", ()))
        observations = tuple(getattr(record, "order_observations", ()))
        normalized: list[tuple[str, dict[str, Any]]] = []
        if observations:
            for observation in observations:
                signed = _observation_field(observation, "signed_quantities", {})
                normalized.append(
                    (
                        str(_observation_field(observation, "order_id", "")),
                        {
                            "certificate_id": str(record.certificate_id),
                            "state": str(record.state),
                            "status": str(_observation_field(observation, "status", "")),
                            "filled_quantity": int(
                                _observation_field(observation, "filled_quantity", 0) or 0
                            ),
                            "average_fill_price": (
                                str(_observation_field(observation, "average_fill_price"))
                                if _observation_field(observation, "average_fill_price") is not None
                                else None
                            ),
                            "role": str(
                                _observation_field(
                                    observation, "role", getattr(record, "role", "entry")
                                )
                            ),
                            "signed_quantities": (
                                dict(signed) if isinstance(signed, Mapping) else {}
                            ),
                            "deadline_at": str(_observation_field(observation, "deadline_at"))
                            if _observation_field(observation, "deadline_at") is not None
                            else str(getattr(record, "deadline_at", "")) or None,
                            "client_order_id": _observation_field(
                                observation,
                                "client_order_id",
                                getattr(record, "client_order_id", None),
                            ),
                        },
                    )
                )
        else:
            status = {
                "SUBMITTED": "NEW",
                "REPLACED": "REPLACED",
                "FILLED": "FILLED",
                "CANCELED": "CANCELED",
                "REJECTED": "REJECTED",
                "RECONCILE_REQUIRED": "UNKNOWN",
            }.get(str(record.state), str(record.state))
            # Aggregate records cannot identify which order in a replacement
            # chain carried a terminal state.  Keep ambiguous rows unknown so
            # a chain is never projected as entirely filled.
            aggregate_state = str(record.state)
            if len(order_ids) > 1 and aggregate_state in {
                "FILLED",
                "REPLACED",
                "CANCELED",
                "REJECTED",
                "RECONCILE_REQUIRED",
            }:
                status = "UNKNOWN"
                filled_quantity = 0
            else:
                filled_quantity = int(getattr(record, "filled_quantity", 0))
            normalized = [
                (
                    order_id,
                    {
                        "certificate_id": str(record.certificate_id),
                        "state": str(record.state),
                        "status": status,
                        "filled_quantity": filled_quantity,
                        "role": str(getattr(record, "role", "entry") or "entry"),
                        "signed_quantities": dict(
                            getattr(record, "signed_quantities", {}) or {}
                        ),
                        "deadline_at": str(getattr(record, "deadline_at", "")) or None,
                        "client_order_id": getattr(record, "client_order_id", None),
                    },
                )
                for order_id in order_ids
            ]
        if not normalized:
            return
        owns_session = session is None
        if owns_session:
            session = Session(self.engine)
            transaction = session.begin()
            transaction.__enter__()
        assert session is not None
        try:
            if session.get(CaseRow, str(record.case_id)) is None:
                raise KeyError(f"unknown case {record.case_id}")
            for order_id, payload in normalized:
                role = str(payload.get("role", "entry"))
                signed = payload.get("signed_quantities", {})
                if role == "entry" and not signed:
                    signed = self._entry_signed_quantities(session, str(record.case_id), payload)
                    payload["signed_quantities"] = signed
                deadline_raw = payload.get("deadline_at")
                deadline = None
                if deadline_raw:
                    deadline = (
                        deadline_raw
                        if isinstance(deadline_raw, datetime)
                        else datetime.fromisoformat(str(deadline_raw))
                    )
                session.add(
                    OrderEventRow(
                        case_id=str(record.case_id),
                        alpaca_order_id=order_id,
                        payload_hash=_payload_hash(payload),
                        payload_json=_redact(payload),
                        occurred_at=record.updated_at,
                        role=role,
                        signed_quantities_json={
                            str(key): int(value) for key, value in (signed or {}).items()
                        },
                        deadline_at=deadline,
                        client_order_id=(
                            str(payload["client_order_id"])
                            if payload.get("client_order_id")
                            else None
                        ),
                    )
                )
            if owns_session:
                transaction.__exit__(None, None, None)
        except BaseException as exc:
            if owns_session:
                transaction.__exit__(type(exc), exc, exc.__traceback__)
            raise
        finally:
            if owns_session:
                session.close()
