"""Bearer gate for the host draft server (AF-07 / WO-1076)."""
from __future__ import annotations

import hmac


def is_authorized(secret: str, authorization: str) -> bool:
    """Fail closed: a missing secret must not authorize anyone."""
    secret = (secret or "").strip()
    authorization = authorization or ""
    if not secret:
        return False
    expected = f"Bearer {secret}"
    if len(authorization) != len(expected):
        return False
    return hmac.compare_digest(authorization, expected)
