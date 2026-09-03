"""Resumable, sanitized SSE encoding."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from lexguard.api.schemas import ApiEvent


def encode_events(events: Iterable[ApiEvent]) -> Iterator[str]:
    for event in events:
        yield (
            f"id: {event.id}\n"
            f"event: {event.event_type}\n"
            f"data: {json.dumps(_redact(event.payload), sort_keys=True, separators=(',', ':'))}\n\n"
        )
    yield ": heartbeat\n\n"
    yield 'event: stream-complete\ndata: {"reason":"finite"}\n\n'


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if "account" in str(key).lower()
            or "secret" in str(key).lower()
            or "token" in str(key).lower()
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value
