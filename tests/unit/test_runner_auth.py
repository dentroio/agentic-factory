"""Unit tests for WO-1090: Agent Runner Authentication & Zero-Trust Hardening."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"


def _load_runner_auth():
    spec = importlib.util.spec_from_file_location("runner_auth", ORCH / "runner_auth.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["runner_auth"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def auth_mod():
    return _load_runner_auth()


def test_issue_and_hash_runner_token(auth_mod):
    tok = auth_mod.issue_runner_token()
    assert tok.startswith("rn_")
    assert len(tok) >= 35

    h1 = auth_mod.hash_runner_token(tok)
    h2 = auth_mod.hash_runner_token(tok)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_load_and_save_runners(auth_mod, tmp_path: Path):
    path = tmp_path / "runners.json"
    runners = [
        {"id": "run_1", "agent_name": "claude-01", "status": "active"},
        {"id": "run_2", "agent_name": "cursor-02", "status": "revoked"},
    ]
    auth_mod.save_runners(path, runners)
    loaded = auth_mod.load_runners(path)
    assert len(loaded) == 2
    assert loaded[0]["agent_name"] == "claude-01"
    assert loaded[1]["status"] == "revoked"


def test_register_and_find_runner(auth_mod, tmp_path: Path):
    path = tmp_path / "runners.json"
    runners = []
    res = auth_mod.register_runner(
        path,
        runners,
        agent_name="claude-01",
        backend="claude",
        workstation="host-mac",
    )
    assert res["agent_name"] == "claude-01"
    assert res["token"].startswith("rn_")
    assert len(runners) == 1

    # Find active runner by plaintext token
    found = auth_mod.find_runner_by_token(runners, res["token"])
    assert found is not None
    assert found["id"] == res["id"]
    assert found["status"] == "active"

    # Reject invalid token
    assert auth_mod.find_runner_by_token(runners, "rn_wrong") is None
    assert auth_mod.find_runner_by_token(runners, "invalid_prefix") is None
    assert auth_mod.find_runner_by_token(runners, "") is None


def test_revoke_runner(auth_mod, tmp_path: Path):
    path = tmp_path / "runners.json"
    runners = []
    res = auth_mod.register_runner(path, runners, agent_name="cursor-01")
    runner_id = res["id"]

    # Revoke
    revoked = auth_mod.revoke_runner(path, runners, runner_id)
    assert revoked is not None
    assert revoked["status"] == "revoked"

    # Revoking non-existent runner returns None
    assert auth_mod.revoke_runner(path, runners, "non_existent_id") is None


def test_check_agent_identity(auth_mod):
    # Master token (runner is None) -> Any agent name is accepted
    ok, err = auth_mod.check_agent_identity(None, "any-agent")
    assert ok is True
    assert err == ""

    # Runner token issued for claude-01
    runner = {"id": "run_1", "agent_name": "claude-01"}

    # Matching agent name
    ok, err = auth_mod.check_agent_identity(runner, "claude-01")
    assert ok is True
    assert err == ""

    # Case-insensitive match
    ok, err = auth_mod.check_agent_identity(runner, "CLAUDE-01")
    assert ok is True
    assert err == ""

    # Mismatched agent name (spoofing attempt)
    ok, err = auth_mod.check_agent_identity(runner, "cursor-02")
    assert ok is False
    assert "Identity mismatch" in err
