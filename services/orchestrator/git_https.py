"""HTTPS GitHub fetch without putting the token in process argv."""
from __future__ import annotations

import os


def github_https_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def git_fetch_env(token: str, base_env: dict | None = None) -> dict[str, str]:
    """Auth via GIT_CONFIG_* so `ps` / docker top cannot read the PAT from argv."""
    env = {k: str(v) for k, v in (base_env if base_env is not None else os.environ).items()}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
    env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {token}"
    return env


def redact_secret(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")
