"""Unit tests for scripts/factory_doctor.py."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import factory_doctor as doctor  # noqa: E402
import factory_init as finit  # noqa: E402


def _git_init(path: Path, remote: str | None = None) -> None:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TEMPLATE_DIR": ""}
    subprocess.run(
        ["git", "init", "--template="],
        cwd=path,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
        capture_output=True,
        env=env,
    )
    (path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=path,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        env=env,
    )
    if remote:
        subprocess.run(
            ["git", "remote", "add", "origin", remote],
            cwd=path,
            check=True,
            capture_output=True,
            env=env,
        )


def test_doctor_fails_without_factory_yaml(tmp_path, capsys):
    _git_init(tmp_path)
    (tmp_path / "Makefile").write_text("ci-local:\n\t@true\n", encoding="utf-8")
    report = doctor.run_doctor(product_path=tmp_path, skip_network=True)
    assert not report.passed
    assert any(r.label == "factory.yaml" and not r.ok for r in report.results)
    capsys.readouterr()


def test_doctor_passes_after_init(tmp_path, capsys):
    _git_init(tmp_path, remote="https://github.com/acme/demo.git")
    (tmp_path / "Makefile").write_text("ci-local:\n\t@true\n", encoding="utf-8")
    finit.init_product(tmp_path, name="demo", force=True)
    report = doctor.run_doctor(product_path=tmp_path, skip_network=True)
    assert report.passed, [r for r in report.results if not r.ok]
    capsys.readouterr()


def test_doctor_detects_repo_mismatch(tmp_path, monkeypatch, capsys):
    _git_init(tmp_path, remote="https://github.com/acme/other.git")
    (tmp_path / "Makefile").write_text("ci-local:\n\t@true\n", encoding="utf-8")
    finit.init_product(tmp_path, name="demo", force=True)
    prefs = tmp_path / "prefs"
    prefs.write_text(
        "GITHUB_REPO=acme/demo\nLOCAL_REPO_PATH=" + str(tmp_path) + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    monkeypatch.delenv("LOCAL_REPO_PATH", raising=False)
    report = doctor.run_doctor(prefs_path=prefs, skip_network=True)
    assert not report.passed
    assert any(
        r.label == "origin matches GITHUB_REPO" and not r.ok for r in report.results
    )
    capsys.readouterr()


def test_load_prefs_env_overrides_file(tmp_path, monkeypatch):
    prefs = tmp_path / "prefs"
    prefs.write_text("GITHUB_REPO=from/file\nLOCAL_REPO_PATH=/tmp/a\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPO", "from/env")
    data = doctor.load_prefs(prefs)
    assert data["GITHUB_REPO"] == "from/env"
