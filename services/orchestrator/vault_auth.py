"""Load the orchestrator's Vault token — never the root token (AF-10 / WO-1057)."""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

ORCHESTRATOR_TOKEN_FILENAME = "orchestrator_token"
ROOT_TOKEN_FILENAME = "root_token"


def load_vault_token(
    keys_dir: Path,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return a scoped Vault token from env or the orchestrator token file.

    Ignores ``root_token`` even if it is present in ``keys_dir``.
    """
    environ = os.environ if env is None else env
    from_env = (environ.get("VAULT_TOKEN") or "").strip()
    if from_env:
        return from_env
    path = keys_dir / ORCHESTRATOR_TOKEN_FILENAME
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""
