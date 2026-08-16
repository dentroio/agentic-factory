"""Dashboard authentication (AF-08 / WO-1059).

API_SECRET is a machine credential for scripts and the orchestrator — not a
human login. The operator opens http://127.0.0.1:8099 in a browser; they
never paste it.

Writes are allowed only if:
  * Authorization: Bearer <API_SECRET> (agents, curl, future Oryntra), or
  * Origin/Referer is the loopback dashboard (same-origin browser UI).

GET/HEAD/OPTIONS stay open on loopback. A missing API_SECRET still refuses
to boot so this process cannot proxy to the orchestrator unauthenticated.

Do not enable postponed annotations: FastAPI resolves endpoint types from
module globals, and Request is imported only inside install() so CI can
import the pure helpers without FastAPI installed.
"""
import hmac
from typing import Any
from urllib.parse import urlparse

ALLOWED_ORIGINS = frozenset(
    {
        "http://127.0.0.1:8099",
        "http://localhost:8099",
    }
)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_secret(secret: str) -> str:
    """Fail closed — a missing secret must not boot an open deputy."""
    if not (secret or "").strip():
        raise RuntimeError(
            "API_SECRET is not set. The dashboard refuses to start without it — "
            "generate one (e.g. `python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"`) "
            "and set API_SECRET in the factory environment."
        )
    return secret


def is_mutating(method: str) -> bool:
    return method.upper() not in _SAFE_METHODS


def _digest_equal(left: str, right: str) -> bool:
    if not left or not right or len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def origin_from_referer(referer: str) -> str:
    """Return scheme://host[:port] from a Referer, or empty if unusable."""
    parsed = urlparse(referer or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc or "@" in parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def browser_origin(origin_header: str, referer_header: str = "") -> str:
    origin = (origin_header or "").strip()
    if origin and origin != "null":
        return origin
    return origin_from_referer(referer_header)


def is_authorized(secret: str, authorization: str, origin: str) -> bool:
    if secret and _digest_equal(authorization, f"Bearer {secret}"):
        return True
    return origin in ALLOWED_ORIGINS


def install(app: Any, secret: str) -> None:
    """Register write-gate middleware. Imports FastAPI lazily."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    secret = require_secret(secret)

    @app.middleware("http")
    async def _dashboard_auth(request: Request, call_next):
        if not is_mutating(request.method):
            return await call_next(request)
        authorization = request.headers.get("Authorization", "")
        origin = browser_origin(
            request.headers.get("Origin", ""),
            request.headers.get("Referer", ""),
        )
        if is_authorized(secret, authorization, origin):
            return await call_next(request)
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
