"""Canonical content hashes for immutable domain artifacts."""

import hashlib
import json

from pydantic import BaseModel


def canonical_sha256(model: BaseModel) -> str:
    payload = model.model_dump(mode="json", exclude_none=False)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
