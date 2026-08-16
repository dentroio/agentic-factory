"""Guards: Dependabot is active and covers every Python service (AF-43)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
SERVICES = ROOT / "services"


def test_dependabot_yml_exists_and_is_not_a_template():
    assert DEPENDABOT.exists(), (
        "GitHub only reads .github/dependabot.yml — the .template file is invisible"
    )
    text = DEPENDABOT.read_text(encoding="utf-8")
    assert "{{FILL IN}}" not in text
    assert "{{" not in text


def test_every_requirements_txt_directory_is_listed():
    text = DEPENDABOT.read_text(encoding="utf-8")
    reqs = sorted(SERVICES.glob("*/requirements.txt"))
    assert reqs, "expected services/*/requirements.txt"
    for path in reqs:
        directory = "/" + path.parent.relative_to(ROOT).as_posix()
        assert f'directory: "{directory}"' in text, f"missing Dependabot pip entry for {directory}"


def test_github_actions_ecosystem_is_listed():
    text = DEPENDABOT.read_text(encoding="utf-8")
    assert 'package-ecosystem: "github-actions"' in text


def test_policy_is_monthly_grouped_no_major_no_auto_rebase():
    text = DEPENDABOT.read_text(encoding="utf-8")
    assert "interval: \"weekly\"" not in text
    assert "interval: \"monthly\"" in text
    assert 'rebase-strategy: "disabled"' in text
    assert "version-update:semver-major" in text
    assert "update-types: [\"minor\", \"patch\"]" in text
