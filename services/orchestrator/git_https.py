"""HTTPS GitHub fetch without putting the token in process argv."""
from __future__ import annotations

import base64
import os


def github_https_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def git_fetch_env(token: str, base_env: dict | None = None) -> dict[str, str]:
    """Auth via GIT_CONFIG_* so `ps` / docker top cannot read the PAT from argv.

    GitHub's smart-HTTP git transport only accepts Basic auth (any username,
    PAT as the password) — it replies 401 + `WWW-Authenticate: Basic` to a
    Bearer-scheme Authorization header, which git surfaces as a misleading
    "could not read Username" prompt-disabled error rather than a clean 401.
    """
    env = {k: str(v) for k, v in (base_env if base_env is not None else os.environ).items()}
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
    env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {basic}"
    return env


def redact_secret(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")
