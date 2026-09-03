"""Sanitized public API schemas and an in-memory projection for tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from lexguard.domain.models import ImmutableModel


class ApiEvent(ImmutableModel):
    id: int = Field(gt=0)
    event_type: str
    occurred_at: datetime
    payload: dict[str, object]


class CaseProjection(ImmutableModel):
    case_id: UUID
    trading_date: date
    decision_window: Literal["10:05", "11:35", "13:05", "14:20"]
    state: str
    underlying: str | None
    reason_codes: tuple[str, ...] = ()
    artifacts: dict[str, object] = Field(default_factory=dict)
    as_of: datetime | None = None
    environment: Literal["development", "competition"] = "development"
    mode: Literal["BACKTEST", "DEVELOPMENT_PAPER", "COMPETITION_PAPER"] = "DEVELOPMENT_PAPER"


class PerformanceProjection(ImmutableModel):
    environment: Literal["development", "competition"]
    as_of: datetime
    provenance: str
    mode: Literal["BACKTEST", "DEVELOPMENT_PAPER", "COMPETITION_PAPER"]
    metrics: dict[str, object]


class ResearchProjection(ImmutableModel):
    environment: Literal["development", "competition"]
    as_of: datetime
    provenance: str
    gate: str
    metrics: dict[str, object]


class StatusResponse(ImmutableModel):
    environment: Literal["development", "competition"]
    as_of: datetime
    mode: Literal["BACKTEST", "DEVELOPMENT_PAPER", "COMPETITION_PAPER"]
    components: dict[str, str]
    checked_at: datetime | None = None


class CaseListResponse(ImmutableModel):
    items: tuple[CaseProjection, ...]
    next_offset: int | None


class ReadStore(Protocol):
    """The narrow public-read boundary; tests may inject an in-memory implementation."""

    def status(self) -> StatusResponse: ...

    def list_cases(self, offset: int, limit: int) -> CaseListResponse: ...

    def get_case(self, case_id: UUID) -> CaseProjection | None: ...

    def get_performance(self) -> PerformanceProjection: ...

    def get_research(self) -> ResearchProjection: ...

    def get_events(self, last_event_id: int) -> tuple[ApiEvent, ...]: ...


class InMemoryReadStore:
    """Small projection source; production wiring can replace it with a DB reader."""

    def __init__(
        self,
        *,
        environment: Literal["development", "competition"] = "development",
        as_of: datetime | None = None,
        cases: tuple[CaseProjection, ...] = (),
        performance: PerformanceProjection | None = None,
        research: ResearchProjection | None = None,
        events: tuple[ApiEvent, ...] = (),
    ) -> None:
        self.environment = environment
        self.as_of = as_of or datetime.now(UTC)
        self.cases = cases
        self.performance = performance
        self.research = research
        self.events = events

    def status(self) -> StatusResponse:
        mode: Literal["DEVELOPMENT_PAPER", "COMPETITION_PAPER"] = (
            "DEVELOPMENT_PAPER" if self.environment == "development" else "COMPETITION_PAPER"
        )
        return StatusResponse(
            environment=self.environment,
            as_of=self.as_of,
            mode=mode,
            components={
                "database": "unknown",
                "alpaca": "paper_only",
                "scheduler": "unknown",
                "reconciliation": "unknown",
            },
        )

    def list_cases(self, offset: int, limit: int) -> CaseListResponse:
        selected = self.cases[offset : offset + limit]
        next_offset = offset + limit if offset + limit < len(self.cases) else None
        return CaseListResponse(items=tuple(selected), next_offset=next_offset)

    def get_case(self, case_id: UUID) -> CaseProjection | None:
        return next((case for case in self.cases if case.case_id == case_id), None)

    def get_performance(self) -> PerformanceProjection:
        return self.performance or PerformanceProjection(
            environment=self.environment,
            as_of=self.as_of,
            provenance="no_artifact",
            mode="DEVELOPMENT_PAPER" if self.environment == "development" else "COMPETITION_PAPER",
            metrics={},
        )

    def get_research(self) -> ResearchProjection:
        return self.research or ResearchProjection(
            environment=self.environment,
            as_of=self.as_of,
            provenance="no_artifact",
            gate="NOT_RUN",
            metrics={},
        )

    def get_events(self, last_event_id: int) -> tuple[ApiEvent, ...]:
        return tuple(event for event in self.events if event.id > last_event_id)
