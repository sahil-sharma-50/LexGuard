import pytest

from lexguard.domain.state_machine import (
    CaseEventType,
    CaseState,
    InvalidTransition,
    transition,
)


def test_submitted_cannot_transition_back_to_certified() -> None:
    with pytest.raises(InvalidTransition):
        transition(CaseState.SUBMITTED, CaseEventType.CERTIFIED)


def test_valid_case_lifecycle_is_explicit() -> None:
    state = CaseState.SCHEDULED
    for event, expected in (
        (CaseEventType.OBSERVED, CaseState.OBSERVED),
        (CaseEventType.FORECASTED, CaseState.FORECASTED),
        (CaseEventType.ARGUED, CaseState.ARGUED),
        (CaseEventType.CERTIFIED, CaseState.CERTIFIED),
        (CaseEventType.SUBMITTED, CaseState.SUBMITTED),
        (CaseEventType.MANAGING, CaseState.MANAGING),
        (CaseEventType.CLOSED, CaseState.CLOSED),
    ):
        state = transition(state, event)
        assert state is expected


def test_any_active_state_can_halt() -> None:
    for state in CaseState:
        if state not in {CaseState.CLOSED, CaseState.REFUSED, CaseState.HALTED}:
            assert transition(state, CaseEventType.HALTED) is CaseState.HALTED
