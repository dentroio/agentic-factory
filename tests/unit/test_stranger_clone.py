"""Stranger-clone / no-Clarion-leak regression for the default product path.

A fresh adopter must not receive Clarion prompts, compose names, or patterns
unless FACTORY_LEGACY_PRODUCT explicitly matches GITHUB_REPO.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent-runner"))

from factory_profile import (  # noqa: E402
    is_legacy_product,
    load_patterns_text,
    load_profile,
)

# Public agent-facing surfaces that must not name Clarion as the default product.
_PUBLIC_SURFACES = [
    ROOT / "README.md",
    ROOT / "scripts" / "agent-setup.sh",
    ROOT / "services" / "agent-runner" / "prompt_builder.py",
    ROOT / "docs" / "wiki" / "Getting-Started.md",
    ROOT / "docs" / "wiki" / "Adopting.md",
    ROOT / "docs" / "adopters" / "BYO.md",
]

_CLARION_RE = re.compile(r"clarion", re.IGNORECASE)


@pytest.fixture(autouse=True)
def _clear_legacy(monkeypatch):
    monkeypatch.delenv("FACTORY_PROFILE", raising=False)
    monkeypatch.delenv("FACTORY_LEGACY_PRODUCT", raising=False)
    monkeypatch.setenv("GITHUB_REPO", "acme/stranger-app")


def test_default_profile_has_no_clarion(tmp_path):
    p = load_profile(tmp_path)
    assert p.source == "defaults"
    assert p.compose_project == ""
    assert p.name != "clarion"
    text = load_patterns_text(tmp_path, p)
    assert "clarion" not in text.lower()
    assert not is_legacy_product()


def test_legacy_patterns_only_when_env_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPO", "dentroio/clarion")
    monkeypatch.setenv("FACTORY_LEGACY_PRODUCT", "dentroio/clarion")
    assert is_legacy_product()
    p = load_profile(tmp_path)
    assert p.source == "legacy"
    text = load_patterns_text(tmp_path, p)
    # Legacy path may mention Clarion; that is intentional for the live instance.
    assert p.compose_project == "clarion"


def test_public_surfaces_do_not_default_to_clarion():
    """Agent-facing onboarding must not steer strangers toward Clarion."""
    offenders: list[str] = []
    for path in _PUBLIC_SURFACES:
        assert path.is_file(), f"missing surface: {path}"
        body = path.read_text(encoding="utf-8")
        # Allow historical / independence mentions only in Adopting if needed —
        # but Getting Started / BYO / README / agent-setup / prompt_builder must be clean.
        if path.name in {"Adopting.md"}:
            # Adopting may mention the independence program; skip hard fail there.
            continue
        if _CLARION_RE.search(body):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"Clarion named in public default surfaces: {offenders}"


def test_clarion_patterns_file_not_used_for_strangers(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPO", "acme/demo")
    monkeypatch.delenv("FACTORY_LEGACY_PRODUCT", raising=False)
    legacy_file = ROOT / "services" / "agent-runner" / "clarion_patterns.md"
    assert legacy_file.is_file()  # still shipped for live legacy instances
    text = load_patterns_text(tmp_path, load_profile(tmp_path))
    assert "clarion.api.auth" not in text
    assert "Clarion codebase patterns" not in text
