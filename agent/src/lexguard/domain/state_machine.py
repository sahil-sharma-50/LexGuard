"""Append-only case state transitions."""

from enum import StrEnum


class CaseState(StrEnum):
    SCHEDULED = "SCHEDULED"
    OBSERVED = "OBSERVED"
    FORECASTED = "FORECASTED"
    ARGUED = "ARGUED"
    CERTIFIED = "CERTIFIED"
    REFUSED = "REFUSED"
    SUBMITTED = "SUBMITTED"
    MANAGING = "MANAGING"
    CLOSED = "CLOSED"
    HALTED = "HALTED"


class CaseEventType(StrEnum):
    OBSERVED = "OBSERVED"
    FORECASTED = "FORECASTED"
    ARGUED = "ARGUED"
    CERTIFIED = "CERTIFIED"
    REFUSED = "REFUSED"
    SUBMITTED = "SUBMITTED"
    MANAGING = "MANAGING"
    CLOSED = "CLOSED"
    HALTED = "HALTED"


class InvalidTransition(ValueError):
    """Raised when an event is not legal for the current case state."""


_TRANSITIONS: dict[tuple[CaseState, CaseEventType], CaseState] = {
    (CaseState.SCHEDULED, CaseEventType.OBSERVED): CaseState.OBSERVED,
    (CaseState.OBSERVED, CaseEventType.FORECASTED): CaseState.FORECASTED,
    (CaseState.FORECASTED, CaseEventType.ARGUED): CaseState.ARGUED,
    (CaseState.ARGUED, CaseEventType.CERTIFIED): CaseState.CERTIFIED,
    (CaseState.ARGUED, CaseEventType.REFUSED): CaseState.REFUSED,
    (CaseState.CERTIFIED, CaseEventType.SUBMITTED): CaseState.SUBMITTED,
    (CaseState.SUBMITTED, CaseEventType.MANAGING): CaseState.MANAGING,
    (CaseState.MANAGING, CaseEventType.CLOSED): CaseState.CLOSED,
}


def transition(current: CaseState, event: CaseEventType) -> CaseState:
    if event is CaseEventType.HALTED and current not in {
        CaseState.CLOSED,
        CaseState.HALTED,
    }:
        return CaseState.HALTED
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError as exc:
        raise InvalidTransition(f"cannot apply {event} to {current}") from exc
