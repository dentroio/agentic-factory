"""Allowlist runner agent names and configure bodies. Pause must block start."""
from __future__ import annotations

ALLOWED_RUNNER_AGENTS = frozenset({"claude", "cursor", "codex", "gemini"})
ALLOWED_CONFIGURE_KEYS = frozenset({"api_key", "domain_filter", "start"})
MAX_API_KEY_LEN = 8192
MAX_DOMAIN_FILTER_LEN = 256


class RunnerAgentError(ValueError):
    """Rejected runner-agent request. Safe to return as an HTTP 400 detail."""


def require_runner_agent(name: str) -> str:
    if name not in ALLOWED_RUNNER_AGENTS:
        raise RunnerAgentError("unknown agent")
    return name


def parse_configure_body(incoming: object) -> dict:
    """Return a sanitized configure payload. Does not log values."""
    if not isinstance(incoming, dict):
        raise RunnerAgentError("body must be a JSON object")
    unknown = [key for key in incoming if key not in ALLOWED_CONFIGURE_KEYS]
    if unknown:
        raise RunnerAgentError(f"unknown agent config key: {unknown[0]}")
    out: dict = {}
    if "api_key" in incoming:
        raw = incoming["api_key"]
        if not isinstance(raw, str):
            raise RunnerAgentError("api_key must be a string")
        key = raw.strip()
        if len(key) > MAX_API_KEY_LEN:
            raise RunnerAgentError("api_key exceeds max length")
        out["api_key"] = key
    if "domain_filter" in incoming:
        raw = incoming["domain_filter"]
        if raw is None:
            out["domain_filter"] = None
        elif isinstance(raw, str):
            value = raw.strip()
            if len(value) > MAX_DOMAIN_FILTER_LEN:
                raise RunnerAgentError("domain_filter exceeds max length")
            out["domain_filter"] = value
        else:
            raise RunnerAgentError("domain_filter must be a string or null")
    if "start" in incoming:
        flag = incoming["start"]
        if not isinstance(flag, bool):
            raise RunnerAgentError("start must be a boolean")
        out["start"] = flag
    return out
