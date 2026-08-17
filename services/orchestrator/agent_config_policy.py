"""Allowlist and validate agent config written through PUT /api/config."""
from __future__ import annotations

import re

ALLOWED_BACKENDS = frozenset({"claude", "cursor", "codex", "gemini"})
ALLOWED_REVIEWER_SLOTS = frozenset({
    "security",
    "architecture",
    "correctness",
    "performance",
    "documentation",
})
ALLOWED_CONFIG_KEYS = frozenset({
    "preferred",
    "name",
    "timeout",
    "force_cross_llm_review",
    "reviewers",
})

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
TIMEOUT_MIN = 60
TIMEOUT_MAX = 86400


class AgentConfigError(ValueError):
    """Rejected config update. Safe to return as an HTTP 400 detail."""


def apply_agent_config_updates(existing: dict, incoming: object) -> dict:
    """Merge allowlisted updates into a copy of existing. Does not mutate existing."""
    if not isinstance(incoming, dict):
        raise AgentConfigError("body must be a JSON object")
    unknown = [key for key in incoming if key not in ALLOWED_CONFIG_KEYS]
    if unknown:
        raise AgentConfigError(f"unknown config key: {unknown[0]}")
    out = dict(existing)
    reviewers = dict(existing.get("reviewers") or {})
    if "reviewers" in incoming:
        raw_reviewers = incoming["reviewers"]
        if not isinstance(raw_reviewers, dict):
            raise AgentConfigError("reviewers must be an object")
        unknown_slots = [slot for slot in raw_reviewers if slot not in ALLOWED_REVIEWER_SLOTS]
        if unknown_slots:
            raise AgentConfigError(f"unknown reviewer slot: {unknown_slots[0]}")
        for slot, backend in raw_reviewers.items():
            reviewers[slot] = _require_backend(slot, backend)
        out["reviewers"] = reviewers
    if "preferred" in incoming:
        out["preferred"] = _require_backend("preferred", incoming["preferred"])
    if "name" in incoming:
        out["name"] = _require_name(incoming["name"])
    if "timeout" in incoming:
        out["timeout"] = _require_timeout(incoming["timeout"])
    if "force_cross_llm_review" in incoming:
        flag = incoming["force_cross_llm_review"]
        if not isinstance(flag, bool):
            raise AgentConfigError("force_cross_llm_review must be a boolean")
        out["force_cross_llm_review"] = flag
    return out


def _require_backend(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise AgentConfigError(f"{field} must be a string")
    backend = value.strip().lower()
    if backend not in ALLOWED_BACKENDS:
        raise AgentConfigError(f"{field} must be one of {', '.join(sorted(ALLOWED_BACKENDS))}")
    return backend


def _require_name(value: object) -> str:
    if not isinstance(value, str):
        raise AgentConfigError("name must be a string")
    name = value.strip()
    if not _NAME_RE.fullmatch(name):
        raise AgentConfigError("name must be a short hostname-safe identifier")
    return name


def _require_timeout(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgentConfigError("timeout must be an integer")
    if value < TIMEOUT_MIN or value > TIMEOUT_MAX:
        raise AgentConfigError(f"timeout must be between {TIMEOUT_MIN} and {TIMEOUT_MAX}")
    return value
