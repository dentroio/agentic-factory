"""Unit tests for factory product profile loading."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent-runner"))

from factory_profile import (  # noqa: E402
    detect_services_from_paths,
    is_legacy_product,
    load_patterns_text,
    load_profile,
)


@pytest.fixture(autouse=True)
def _clear_profile_env(monkeypatch):
    monkeypatch.delenv("FACTORY_PROFILE", raising=False)
    monkeypatch.delenv("FACTORY_LEGACY_PRODUCT", raising=False)
    monkeypatch.setenv("GITHUB_REPO", "acme/demo")


def test_missing_profile_is_generic(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPO", "acme/demo")
    p = load_profile(tmp_path)
    assert p.source == "defaults"
    assert p.compose_project == ""
    assert p.verify == "make ci-local"
    text = load_patterns_text(tmp_path, p)
    assert "Clarion" not in text
    assert "clarion" not in text.lower()


def test_loads_factory_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPO", "acme/demo")
    (tmp_path / "factory.yaml").write_text(
        "name: demo\nverify: make test\nui_url: http://localhost:9\n"
        "ui_verify_hint: check it\ncompose_project: ''\n"
        "patterns_file: docs/factory/patterns.md\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "factory").mkdir(parents=True)
    (tmp_path / "docs" / "factory" / "patterns.md").write_text("## Hello\n", encoding="utf-8")
    p = load_profile(tmp_path)
    assert p.source.startswith("file:")
    assert p.name == "demo"
    assert p.verify == "make test"
    assert p.ui_url == "http://localhost:9"
    assert load_patterns_text(tmp_path, p) == "## Hello"


def test_legacy_only_when_env_matches(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPO", "dentroio/clarion")
    monkeypatch.setenv("FACTORY_LEGACY_PRODUCT", "dentroio/clarion")
    assert is_legacy_product()
    p = load_profile(tmp_path)
    assert p.source == "legacy"
    assert p.compose_project == "clarion"
    assert p.enable_connector_preflight is True


def test_detect_services_generic_capture():
    p = load_profile(None)
    svcs = detect_services_from_paths(
        ["services/gateway/main.py", "frontend/src/App.tsx", "README.md"],
        p,
    )
    assert "frontend" in svcs
    assert "gateway" in svcs
