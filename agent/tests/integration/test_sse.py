"""Resumable sanitized event-stream tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from lexguard.api.app import create_app
from lexguard.api.schemas import ApiEvent, InMemoryReadStore

NOW = datetime(2026, 8, 24, 14, 10, tzinfo=UTC)


def test_sse_supports_last_event_id_and_heartbeat() -> None:
    store = InMemoryReadStore(
        environment="development",
        as_of=NOW,
        events=(
            ApiEvent(id=1, event_type="OBSERVED", occurred_at=NOW, payload={"safe": True}),
            ApiEvent(
                id=2,
                event_type="ORDER",
                occurred_at=NOW,
                payload={"account_id": "private", "safe": "value"},
            ),
        ),
    )
    client = TestClient(create_app(store))

    response = client.get("/api/events", headers={"Last-Event-ID": "1"})
    body = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 1" not in body
    assert "id: 2" in body
    assert '"account_id":"[REDACTED]"' in body
    assert ": heartbeat" in body
    assert "event: stream-complete" in body
