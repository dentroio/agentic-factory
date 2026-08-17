"""Guards: PUT /api/config only accepts known agent-config keys."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"


def _load_policy():
    spec = importlib.util.spec_from_file_location(
        "factory_agent_config_policy", ORCH / "agent_config_policy.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_agent_config_policy"] = module
    spec.loader.exec_module(module)
    return module


def test_unknown_key_is_rejected():
    p = _load_policy()
    with pytest.raises(p.AgentConfigError, match="unknown config key"):
        p.apply_agent_config_updates({}, {"not_a_key": "x"})


def test_automation_model_cannot_be_written_here():
    p = _load_policy()
    assert "automation_model" not in p.ALLOWED_CONFIG_KEYS
    with pytest.raises(p.AgentConfigError, match="unknown config key"):
        p.apply_agent_config_updates({}, {"automation_model": "claude-sonnet-5"})


def test_preferred_must_be_a_known_backend():
    p = _load_policy()
    with pytest.raises(p.AgentConfigError, match="preferred must be one of"):
        p.apply_agent_config_updates({}, {"preferred": "not-a-backend"})
    out = p.apply_agent_config_updates({"preferred": "claude"}, {"preferred": "cursor"})
    assert out["preferred"] == "cursor"


def test_timeout_rejects_bool_and_out_of_range():
    p = _load_policy()
    with pytest.raises(p.AgentConfigError, match="timeout must be an integer"):
        p.apply_agent_config_updates({}, {"timeout": True})
    with pytest.raises(p.AgentConfigError, match="timeout must be between"):
        p.apply_agent_config_updates({}, {"timeout": 1})
    out = p.apply_agent_config_updates({}, {"timeout": 7200})
    assert out["timeout"] == 7200


def test_reviewer_slot_and_backend_are_allowlisted():
    p = _load_policy()
    with pytest.raises(p.AgentConfigError, match="unknown reviewer slot"):
        p.apply_agent_config_updates({}, {"reviewers": {"evil": "claude"}})
    with pytest.raises(p.AgentConfigError, match="security must be one of"):
        p.apply_agent_config_updates({}, {"reviewers": {"security": "not-a-backend"}})
    existing = {"reviewers": {"security": "claude"}}
    out = p.apply_agent_config_updates(
        existing, {"reviewers": {"documentation": "codex"}}
    )
    assert out["reviewers"]["security"] == "claude"
    assert out["reviewers"]["documentation"] == "codex"
    assert existing["reviewers"]["security"] == "claude"


def test_name_must_be_hostname_safe():
    p = _load_policy()
    with pytest.raises(p.AgentConfigError, match="hostname-safe"):
        p.apply_agent_config_updates({}, {"name": "../evil"})
    out = p.apply_agent_config_updates({}, {"name": "factory-agent"})
    assert out["name"] == "factory-agent"


def test_orchestrator_put_config_uses_the_policy():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    assert "from agent_config_policy import AgentConfigError, apply_agent_config_updates" in text
    assert "apply_agent_config_updates(_load_agent_config(), incoming)" in text
    assert "AGENT_CONFIG_PATH.write_text" not in text
    assert "dispatch_control.atomic_write_json(AGENT_CONFIG_PATH, merged)" in text
