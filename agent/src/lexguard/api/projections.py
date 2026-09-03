"""Repository-backed, sanitized projections for the public read API."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID

from lexguard.adapters.repository import CaseRepository, LedgerCaseRecord
from lexguard.api.schemas import (
    ApiEvent,
    CaseListResponse,
    CaseProjection,
    PerformanceProjection,
    ResearchProjection,
    StatusResponse,
)
from lexguard.services.health import health_state_from_artifact

Environment = Literal["development", "competition"]
_HEALTH_HEARTBEAT_FRESHNESS = timedelta(minutes=2)
_SENSITIVE_TOKENS = (
    "account",
    "secret",
    "authorization",
    "token",
    "password",
    "api_key",
    "access_key",
    "private_key",
    "broker_id",
    "private_export",
)


def _public_redact(value: Any) -> Any:
    """Remove account and credential-shaped values from every public projection."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if any(token in str(key).lower() for token in _SENSITIVE_TOKENS)
            else _public_redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_public_redact(item) for item in value]
    return value


class RepositoryReadStore:
    """Derive public views solely from persisted ledger rows and artifacts."""

    def __init__(
        self,
        repository: CaseRepository,
        *,
        environment: Environment = "development",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.environment = environment
        self._now = now or (lambda: datetime.now(UTC))

    def status(self) -> StatusResponse:
        database_health = self.repository.database_health()
        try:
            heartbeat = self.repository.latest_artifact("health_heartbeat")
        except Exception:  # noqa: BLE001 - status must survive an uninitialized schema
            heartbeat = None
        if heartbeat is None:
            components, checked_at = health_state_from_artifact(
                {}, self._now(), self._now(), _HEALTH_HEARTBEAT_FRESHNESS
            )
        else:
            payload, _, created_at = heartbeat
            components, checked_at = health_state_from_artifact(
                payload, created_at, self._now(), _HEALTH_HEARTBEAT_FRESHNESS
            )
        return StatusResponse(
            environment=self.environment,
            as_of=self._as_of(),
            mode=self._paper_mode(),
            components={
                "database": database_health,
                **components,
            },
            checked_at=checked_at,
        )

    def is_ready(self) -> bool:
        """Readiness used by Railway's health probe; migrations are not implicit."""

        return self.repository.database_health() == "healthy"

    def list_cases(self, offset: int, limit: int) -> CaseListResponse:
        records, has_more = self.repository.list_ledger_cases(offset, limit)
        return CaseListResponse(
            items=tuple(
                self._case_projection(record)
                for record in records
                # SYSTEM cases only anchor runtime artifacts; they are not
                # public decision cases.
                if record.decision_window != "SYSTEM"
            ),
            next_offset=offset + limit if has_more else None,
        )

    def get_case(self, case_id: UUID) -> CaseProjection | None:
        record = self.repository.ledger_case(case_id)
        if record is None or record.decision_window == "SYSTEM":
            return None
        return self._case_projection(record)

    def get_performance(self) -> PerformanceProjection:
        artifact = self.repository.latest_artifact("performance_snapshot")
        if artifact is None:
            return PerformanceProjection(
                environment=self.environment,
                as_of=self._as_of(),
                provenance="no_recorded_performance_artifact",
                mode=self._paper_mode(),
                metrics={},
            )
        payload, content_hash, created_at = artifact
        mode = payload.get("mode", self._paper_mode())
        return PerformanceProjection(
            environment=self.environment,
            as_of=created_at,
            provenance=str(payload.get("provenance", f"ledger_artifact:{content_hash}")),
            mode=(
                mode
                if mode in {"BACKTEST", "DEVELOPMENT_PAPER", "COMPETITION_PAPER"}
                else self._paper_mode()
            ),
            metrics=_mapping(_public_redact(payload.get("metrics", {}))),
        )

    def get_research(self) -> ResearchProjection:
        artifact = self.repository.latest_artifact("research_summary")
        if artifact is None:
            return ResearchProjection(
                environment=self.environment,
                as_of=self._as_of(),
                provenance="no_recorded_research_artifact",
                gate="NOT_RUN",
                metrics={},
            )
        payload, content_hash, created_at = artifact
        return ResearchProjection(
            environment=self.environment,
            as_of=created_at,
            provenance=str(payload.get("provenance", f"ledger_artifact:{content_hash}")),
            gate=str(payload.get("gate", "NOT_RUN")),
            metrics=_mapping(_public_redact(payload.get("metrics", {}))),
        )

    def get_events(self, last_event_id: int) -> tuple[ApiEvent, ...]:
        return tuple(
            ApiEvent(
                id=event.event_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                payload=_mapping(_public_redact(event.payload)),
            )
            for event in self.repository.ledger_events_since(last_event_id)
        )

    def _case_projection(self, record: LedgerCaseRecord) -> CaseProjection:
        artifacts = _mapping(_public_redact(record.artifacts))
        refusal = artifacts.get("refusal_record", artifacts.get("halt_record", {}))
        reason_codes = refusal.get("reason_codes", ()) if isinstance(refusal, Mapping) else ()
        if not reason_codes:
            reason_codes = self._event_reason_codes(record.case_id)
        return CaseProjection(
            case_id=record.case_id,
            trading_date=record.trading_date,
            decision_window=cast(
                Literal["10:05", "11:35", "13:05", "14:20"], record.decision_window
            ),
            state=record.state,
            underlying=record.underlying,
            reason_codes=tuple(str(item) for item in reason_codes),
            artifacts=artifacts,
            as_of=record.updated_at,
            environment=self.environment,
            mode=self._paper_mode(),
        )

    def _event_reason_codes(self, case_id: UUID) -> tuple[object, ...]:
        for event in reversed(self.repository.ledger_events_since(0)):
            payload = event.payload
            if event.case_id == case_id and isinstance(payload.get("reason_codes"), list):
                return tuple(payload["reason_codes"])
        return ()

    def _as_of(self) -> datetime:
        try:
            return self.repository.latest_ledger_time() or self._now()
        except Exception:  # noqa: BLE001 - status remains useful while DB is bootstrapping
            return self._now()

    def _paper_mode(self) -> Literal["DEVELOPMENT_PAPER", "COMPETITION_PAPER"]:
        return "DEVELOPMENT_PAPER" if self.environment == "development" else "COMPETITION_PAPER"


def _mapping(value: Any) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}
