"""Four fixed decision windows and the rotation dispatcher."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from lexguard.cli import _decision_window_for, _RotatingCaseEvaluator
from lexguard.domain.enums import DecisionWindow
from lexguard.services.scheduler import (
    EXECUTION_TIMES,
    MINIMUM_HOLD,
    WINDOW_TIMES,
    Scheduler,
)

NEW_YORK = ZoneInfo("America/New_York")


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 2, hour, minute, 12, tzinfo=NEW_YORK)


def test_every_window_has_an_execution_slot_five_minutes_later() -> None:
    assert set(WINDOW_TIMES) == set(EXECUTION_TIMES) == set(DecisionWindow)
    for window, evaluation in WINDOW_TIMES.items():
        execution = EXECUTION_TIMES[window]
        assert (execution.hour * 60 + execution.minute) - (
            evaluation.hour * 60 + evaluation.minute
        ) == 5


def test_late_window_execution_respects_minimum_hold_before_forced_exit() -> None:
    late_execution = EXECUTION_TIMES[DecisionWindow.LATE]
    execution_minutes = late_execution.hour * 60 + late_execution.minute
    forced_exit_minutes = 15 * 60 + 30
    assert execution_minutes + int(MINIMUM_HOLD.total_seconds() // 60) <= forced_exit_minutes


def test_window_due_detection_for_all_windows() -> None:
    assert Scheduler._evaluation_window_due(_at(10, 5)) is DecisionWindow.MORNING
    assert Scheduler._evaluation_window_due(_at(11, 35)) is DecisionWindow.MIDDAY
    assert Scheduler._evaluation_window_due(_at(13, 5)) is DecisionWindow.AFTERNOON
    assert Scheduler._evaluation_window_due(_at(14, 20)) is DecisionWindow.LATE
    assert Scheduler._execution_window_due(_at(11, 40)) is DecisionWindow.MIDDAY
    assert Scheduler._execution_window_due(_at(14, 25)) is DecisionWindow.LATE
    assert Scheduler._evaluation_window_due(_at(12, 0)) is None


def test_decision_window_for_maps_to_most_recent_window() -> None:
    assert _decision_window_for(_at(10, 30).astimezone(UTC)) == "10:05"
    assert _decision_window_for(_at(11, 50).astimezone(UTC)) == "11:35"
    assert _decision_window_for(_at(13, 30).astimezone(UTC)) == "13:05"
    assert _decision_window_for(_at(14, 45).astimezone(UTC)) == "14:20"


@pytest.mark.asyncio
async def test_rotating_evaluator_dispatches_by_window_value() -> None:
    class Recorder:
        def __init__(self, name: str) -> None:
            self.name = name
            self.calls: list[str] = []

        async def evaluate(self, window: DecisionWindow, now: datetime) -> str:
            self.calls.append(window.value)
            return self.name

    spy_service = Recorder("SPY")
    qqq_service = Recorder("QQQ")
    evaluator = _RotatingCaseEvaluator({"10:05": spy_service, "11:35": qqq_service})

    now = _at(10, 5).astimezone(UTC)
    assert await evaluator.evaluate(DecisionWindow.MORNING, now) == "SPY"
    assert await evaluator.evaluate(DecisionWindow.MIDDAY, now) == "QQQ"
    with pytest.raises(RuntimeError):
        await evaluator.evaluate(DecisionWindow.LATE, now)
