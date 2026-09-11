"""Unit tests for scripts/factory_smoke.py (no live services required)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "factory_smoke", ROOT / "scripts" / "factory_smoke.py"
)
assert SPEC and SPEC.loader
factory_smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(factory_smoke)


def test_check_status_accepts_ok_payload():
    body = json.dumps({"status": "ok", "repo": "dentroio/agentic-factory"})
    with patch.object(factory_smoke, "_get", return_value=(200, body)):
        factory_smoke.check_status("http://example/health", 1.0)


def test_check_status_rejects_non_200():
    with patch.object(factory_smoke, "_get", return_value=(503, "down")):
        with pytest.raises(RuntimeError, match="HTTP 503"):
            factory_smoke.check_status("http://example/health", 1.0)


def test_orchestrator_accepts_401_without_token():
    with patch.object(factory_smoke, "_get", return_value=(401, '{"detail":"Unauthorized"}')):
        factory_smoke.check_orchestrator("http://example/health", 1.0, token="")


def test_orchestrator_requires_200_with_token():
    with patch.object(factory_smoke, "_get", return_value=(401, "nope")):
        with pytest.raises(RuntimeError, match="HTTP 401"):
            factory_smoke.check_orchestrator("http://example/health", 1.0, token="secret")
    with patch.object(factory_smoke, "_get", return_value=(200, '{"ok":true}')):
        factory_smoke.check_orchestrator("http://example/health", 1.0, token="secret")
