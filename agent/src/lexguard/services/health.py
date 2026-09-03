"""Sanitized, fail-closed runtime health heartbeat helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_COMPONENTS = ("alpaca", "scheduler", "reconciliation")
_WRITER_STATES = {"healthy", "unavailable"}


@dataclass(frozen=True, slots=True)
class HealthHeartbeat:
    components: Mapping[str, str]
    checked_at: datetime

    def to_payload(self) -> dict[str, object]:
        return {
            "components": {
                name: state
                for name, state in self.components.items()
                if name in _COMPONENTS and state in _WRITER_STATES
            },
            "checked_at": self.checked_at.astimezone(UTC).isoformat(),
        }


def record_health_heartbeat(
    repository: object,
    components: Mapping[str, str],
    now: datetime,
) -> None:
    writer = getattr(repository, "save_runtime_artifact", None)
    if not callable(writer):
        return
    writer(
        now.date(),
        "health_heartbeat",
        HealthHeartbeat(components=components, checked_at=now).to_payload(),
        now=now,
    )


def health_state_from_artifact(
    payload: Mapping[str, object],
    created_at: datetime,
    now: datetime,
    freshness: timedelta,
) -> tuple[dict[str, str], datetime | None]:
    raw_checked_at = payload.get("checked_at")
    checked_at = _timestamp(raw_checked_at)
    if checked_at is None or checked_at > now or now - checked_at > freshness:
        return _stale_components(), checked_at

    raw_components = payload.get("components")
    if not isinstance(raw_components, Mapping):
        return _stale_components(), checked_at

    components = {
        name: str(raw_components.get(name, "stale"))
        for name in _COMPONENTS
    }
    if any(state not in _WRITER_STATES for state in components.values()):
        return _stale_components(), checked_at
    return components, checked_at


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _stale_components() -> dict[str, str]:
    return {name: "stale" for name in _COMPONENTS}
