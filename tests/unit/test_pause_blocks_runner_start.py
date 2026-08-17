"""Guards: pause refuses runner start; agent names and configure bodies are allowlisted."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"


def _load_policy():
    spec = importlib.util.spec_from_file_location(
        "factory_runner_agents", ORCH / "runner_agents.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_runner_agents"] = module
    spec.loader.exec_module(module)
    return module


def test_unknown_agent_is_rejected():
    p = _load_policy()
    with pytest.raises(p.RunnerAgentError, match="unknown agent"):
        p.require_runner_agent("not-an-agent")
    with pytest.raises(p.RunnerAgentError, match="unknown agent"):
        p.require_runner_agent("..")
    assert p.require_runner_agent("claude") == "claude"


def test_unknown_configure_key_is_rejected():
    p = _load_policy()
    with pytest.raises(p.RunnerAgentError, match="unknown agent config key"):
        p.parse_configure_body({"label": "com.evil"})


def test_start_must_be_boolean():
    p = _load_policy()
    with pytest.raises(p.RunnerAgentError, match="start must be a boolean"):
        p.parse_configure_body({"start": 1})
    assert p.parse_configure_body({"start": True}) == {"start": True}


def test_orchestrator_refuses_start_while_paused():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    assert "from runner_agents import RunnerAgentError, parse_configure_body, require_runner_agent" in text
    start_fn = text.split("async def start_runner_agent")[1].split("async def ")[0]
    assert "_refuse_if_paused()" in start_fn
    configure_fn = text.split("async def configure_runner_agent")[1].split("async def ")[0]
    assert "if body.get(\"start\"):" in configure_fn
    assert "_refuse_if_paused()" in configure_fn
    assert "except Exception:\n        pass" not in configure_fn
