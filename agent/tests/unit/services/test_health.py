from datetime import UTC, datetime, timedelta

from lexguard.services.health import HealthHeartbeat, health_state_from_artifact

NOW = datetime(2026, 9, 3, 8, 10, tzinfo=UTC)


def test_fresh_complete_heartbeat_projects_verified_components() -> None:
    heartbeat = HealthHeartbeat(
        components={
            "alpaca": "healthy",
            "scheduler": "healthy",
            "reconciliation": "healthy",
        },
        checked_at=NOW,
    )

    components, checked_at = health_state_from_artifact(
        heartbeat.to_payload(), NOW, NOW, timedelta(minutes=2)
    )

    assert components == {
        "alpaca": "healthy",
        "scheduler": "healthy",
        "reconciliation": "healthy",
    }
    assert checked_at == NOW


def test_stale_heartbeat_never_projects_healthy() -> None:
    checked_at = NOW - timedelta(minutes=3)
    payload = HealthHeartbeat(
        components={
            "alpaca": "healthy",
            "scheduler": "healthy",
            "reconciliation": "healthy",
        },
        checked_at=checked_at,
    ).to_payload()

    components, projected_at = health_state_from_artifact(
        payload, checked_at, NOW, timedelta(minutes=2)
    )

    assert components == {
        "alpaca": "stale",
        "scheduler": "stale",
        "reconciliation": "stale",
    }
    assert projected_at == checked_at
