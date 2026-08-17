"""Guards: PUT /api/secrets only accepts known keys (AF-28 remainder)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"


def _load_policy():
    spec = importlib.util.spec_from_file_location(
        "factory_secrets_policy", ORCH / "secrets_policy.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_secrets_policy"] = module
    spec.loader.exec_module(module)
    return module


def test_unknown_key_is_rejected():
    p = _load_policy()
    with pytest.raises(p.SecretPolicyError, match="unknown secret key"):
        p.apply_secret_updates({}, {"NOT_A_KEY": "x"})


def test_api_secret_cannot_be_written_through_this_api():
    p = _load_policy()
    assert "API_SECRET" not in p.ALLOWED_SECRET_KEYS
    with pytest.raises(p.SecretPolicyError, match="unknown secret key"):
        p.apply_secret_updates({}, {"API_SECRET": "should-not-land"})


def test_classic_github_token_is_rejected():
    p = _load_policy()
    with pytest.raises(p.SecretPolicyError, match="github_pat_"):
        p.apply_secret_updates({}, {"GITHUB_TOKEN": "ghp_classic"})
    with pytest.raises(p.SecretPolicyError, match="github_pat_"):
        p.apply_secret_updates({}, {"GITHUB_TOKEN": "gho_oauth"})


def test_fine_grained_github_token_is_accepted():
    p = _load_policy()
    out = p.apply_secret_updates({}, {"GITHUB_TOKEN": "github_pat_example"})
    assert out["GITHUB_TOKEN"] == "github_pat_example"


def test_empty_value_deletes_allowlisted_key():
    p = _load_policy()
    existing = {"NTFY_TOPIC": "factory", "GITHUB_REPO": "dentroio/clarion"}
    out = p.apply_secret_updates(existing, {"NTFY_TOPIC": "  "})
    assert "NTFY_TOPIC" not in out
    assert out["GITHUB_REPO"] == "dentroio/clarion"
    assert existing["NTFY_TOPIC"] == "factory"


def test_non_string_value_is_rejected():
    p = _load_policy()
    with pytest.raises(p.SecretPolicyError, match="must be a string"):
        p.apply_secret_updates({}, {"NTFY_TOPIC": 1})


def test_existing_unknown_keys_are_left_in_place():
    p = _load_policy()
    existing = {"LEGACY": "keep", "NTFY_TOPIC": "old"}
    out = p.apply_secret_updates(existing, {"NTFY_TOPIC": "new"})
    assert out["LEGACY"] == "keep"
    assert out["NTFY_TOPIC"] == "new"


def test_orchestrator_put_secrets_uses_the_policy():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    assert "from secrets_policy import SecretPolicyError, apply_secret_updates" in text
    assert "apply_secret_updates(_secrets_cache, incoming)" in text
    assert "SECRETS_PATH.write_text" not in text
    assert "dispatch_control.atomic_write_json(SECRETS_PATH, secrets)" in text
