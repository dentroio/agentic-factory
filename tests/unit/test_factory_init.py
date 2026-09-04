"""Unit tests for scripts/factory_init.py."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import factory_init as finit  # noqa: E402


def test_init_creates_expected_files(tmp_path):
    created = finit.init_product(
        tmp_path,
        name="demo",
        verify="make ci-local",
        sample_wo=True,
        force=True,
    )
    assert (tmp_path / "factory.yaml").is_file()
    assert (tmp_path / "AGENT_PROCESS.md").is_file()
    assert (tmp_path / "docs" / "factory" / "patterns.md").is_file()
    assert (tmp_path / "docs" / "factory" / "runs" / ".gitkeep").is_file()
    assert (
        tmp_path / "docs" / "project_management" / "work_orders" / "WO-001-hello-factory.md"
    ).is_file()
    yaml = (tmp_path / "factory.yaml").read_text(encoding="utf-8")
    assert "name: demo" in yaml
    assert 'verify: "make ci-local"' in yaml
    assert "factory.yaml" in created


def test_init_does_not_clobber_without_force(tmp_path):
    finit.init_product(tmp_path, name="first", force=True)
    (tmp_path / "factory.yaml").write_text("name: keep-me\n", encoding="utf-8")
    created = finit.init_product(tmp_path, name="second", force=False)
    assert "factory.yaml" not in created
    assert "name: keep-me" in (tmp_path / "factory.yaml").read_text(encoding="utf-8")


def test_main_refuses_engine_root(monkeypatch):
    monkeypatch.setattr(finit, "ENGINE_ROOT", ROOT)
    rc = finit.main(["--path", str(ROOT), "--name", "nope", "--non-interactive"])
    assert rc == 2


def test_main_non_interactive_derives_name(tmp_path):
    """make init PRODUCT=… uses --non-interactive without --name."""
    product = tmp_path / "demo-app"
    product.mkdir()
    rc = finit.main(["--path", str(product), "--non-interactive"])
    assert rc == 0
    yaml = (product / "factory.yaml").read_text(encoding="utf-8")
    assert "name: demo-app" in yaml
