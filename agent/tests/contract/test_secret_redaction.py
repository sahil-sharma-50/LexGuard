"""Credential-shaped values never cross public projection boundaries."""

from datetime import UTC, datetime

from lexguard.adapters.repository import _redact
from lexguard.api.schemas import ApiEvent
from lexguard.api.sse import encode_events


def test_repository_redacts_provider_secrets() -> None:
    payload = _redact({"api_key": "PK123", "secret_key": "secret", "nested": {"token": "tok"}})
    assert payload == {
        "api_key": "[REDACTED]",
        "secret_key": "[REDACTED]",
        "nested": {"token": "[REDACTED]"},
    }


def test_sse_redacts_account_and_token_fields() -> None:
    event = ApiEvent(
        id=1,
        event_type="TEST",
        occurred_at=datetime(2026, 8, 24, 14, 10, tzinfo=UTC),
        payload={"account_id": "account-private", "access_token": "token-private"},
    )
    body = "".join(encode_events((event,)))
    assert "account-private" not in body
    assert "token-private" not in body
