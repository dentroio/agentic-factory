"""Unit tests for services/agent-runner/product_setup.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent-runner"))

import product_setup as ps  # noqa: E402


@pytest.fixture(autouse=True)
def _allow_any_path(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_ALLOW_ANY_PATH", "1")
    monkeypatch.setenv("FACTORY_PREFS", str(tmp_path / "prefs"))
    # Reload module-level PREFS_PATH from env — patch the attribute directly
    monkeypatch.setattr(ps, "PREFS_PATH", tmp_path / "prefs")


def test_write_and_read_prefs(tmp_path):
    prefs = tmp_path / "prefs"
    out = ps.write_prefs(
        {"GITHUB_REPO": "acme/demo", "LOCAL_REPO_PATH": str(tmp_path / "app")},
        prefs,
    )
    assert out["GITHUB_REPO"] == "acme/demo"
    assert ps.read_prefs(prefs)["LOCAL_REPO_PATH"] == str(tmp_path / "app")
    ps.write_prefs({"LOCAL_REPO_PATH": ""}, prefs)
    assert "LOCAL_REPO_PATH" not in ps.read_prefs(prefs)


def test_normalize_repo_forms():
    assert ps.normalize_repo("acme/demo") == "acme/demo"
    assert ps.normalize_repo("https://github.com/acme/demo.git") == "acme/demo"
    assert ps.normalize_repo("git@github.com:acme/demo.git") == "acme/demo"
    with pytest.raises(ps.ProductSetupError):
        ps.normalize_repo("not-a-repo")


def test_resolve_local_path_rejects_relative(monkeypatch):
    monkeypatch.delenv("FACTORY_ALLOW_ANY_PATH", raising=False)
    with pytest.raises(ps.ProductSetupError, match="absolute"):
        ps.resolve_local_path("relative/path")


def test_resolve_local_path_home_guard(monkeypatch, tmp_path):
    monkeypatch.delenv("FACTORY_ALLOW_ANY_PATH", raising=False)
    outside = Path("/tmp/factory-product-setup-outside")
    with pytest.raises(ps.ProductSetupError, match="home"):
        ps.resolve_local_path(str(outside))


def test_configure_product_scaffolds(tmp_path):
    app = tmp_path / "my-app"
    app.mkdir()
    result = ps.configure_product(
        github_repo="acme/demo",
        local_repo_path=str(app),
        scaffold=True,
        prefs_file=tmp_path / "prefs",
    )
    assert (app / "factory.yaml").is_file()
    assert (app / "AGENT_PROCESS.md").is_file()
    assert result["restart_required"] is True
    assert result["github_repo"] == "acme/demo"
    assert "factory.yaml" in result["scaffolded"] or result["has_factory_yaml"]


def test_default_clone_dest_prefers_existing_parent(tmp_path, monkeypatch):
    home = tmp_path / "home"
    projects = home / "Projects"
    projects.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    dest = ps.default_clone_dest("acme/demo")
    assert dest == projects / "demo"


def test_configure_preferred_agent(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    result = ps.configure_product(
        github_repo="acme/demo",
        local_repo_path=str(app),
        preferred_agent="cursor",
        prefs_file=tmp_path / "prefs",
    )
    assert result["preferred_agent"] == "cursor"
    assert ps.read_prefs(tmp_path / "prefs")["PREFERRED_AGENT"] == "cursor"
    with pytest.raises(ps.ProductSetupError):
        ps.configure_product(preferred_agent="nope", prefs_file=tmp_path / "prefs")
