"""Guards: per-backend draft ports stay unique and match health_agent."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "services" / "agent-runner"
sys.path.insert(0, str(RUNNER))

import draft_server as ds  # noqa: E402
import health_agent as ha  # noqa: E402


def test_agent_meta_draft_ports_match_health_agent():
    for name, expected in ha.RUNNER_PORTS.items():
        meta = ds._AGENT_META[name]
        port = int((meta.get("extra_env") or {}).get("DRAFT_PORT", "8101"))
        assert port == expected, f"{name}: meta port {port} != health_agent {expected}"


def test_draft_ports_are_unique():
    ports = [
        int((meta.get("extra_env") or {}).get("DRAFT_PORT", "8101"))
        for meta in ds._AGENT_META.values()
    ]
    assert len(ports) == len(set(ports)), f"duplicate DRAFT_PORTs: {ports}"


def test_bind_failure_logs_remediation():
    text = (RUNNER / "draft_server.py").read_text(encoding="utf-8")
    assert "Failed to bind" in text
    assert "lsof" in text
    assert "DRAFT_PORT" in text
