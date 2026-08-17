"""Allowlist and validate secret keys written through PUT /api/secrets."""
from __future__ import annotations

ALLOWED_SECRET_KEYS = frozenset({
    "GITHUB_TOKEN",
    "GITHUB_REPO",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "SLACK_WEBHOOK_URL",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "NTFY_TOPIC",
    "NTFY_SERVER",
})

MAX_SECRET_VALUE_LEN = 8192


class SecretPolicyError(ValueError):
    """Rejected secret update. Safe to return as an HTTP 400 detail."""


def apply_secret_updates(existing: dict, incoming: object) -> dict:
    """Merge allowlisted updates into a copy of existing. Does not mutate existing."""
    if not isinstance(incoming, dict):
        raise SecretPolicyError("body must be a JSON object")
    unknown = [key for key in incoming if key not in ALLOWED_SECRET_KEYS]
    if unknown:
        raise SecretPolicyError(f"unknown secret key: {unknown[0]}")
    out = dict(existing)
    for key, raw in incoming.items():
        if raw is None:
            out.pop(key, None)
            continue
        if not isinstance(raw, str):
            raise SecretPolicyError(f"{key} must be a string")
        value = raw.strip()
        if not value:
            out.pop(key, None)
            continue
        if len(value) > MAX_SECRET_VALUE_LEN:
            raise SecretPolicyError(f"{key} exceeds max length")
        if key == "GITHUB_TOKEN" and not value.startswith("github_pat_"):
            raise SecretPolicyError(
                "GITHUB_TOKEN must be a fine-grained github_pat_ token"
            )
        out[key] = value
    return out
