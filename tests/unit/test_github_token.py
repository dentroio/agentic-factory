"""AF-11: factory GitHub token must be a fine-grained PAT."""
from __future__ import annotations

import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import github_token as gt  # noqa: E402


def test_classifies_fine_grained_classic_and_oauth():
    assert gt.classify("github_pat_abc") == gt.FINE_GRAINED
    assert gt.classify("ghp_abc") == gt.CLASSIC
    assert gt.classify("gho_abc") == gt.OAUTH
    assert gt.classify("") == gt.UNKNOWN


def test_require_fine_grained_accepts_only_github_pat():
    assert gt.require_fine_grained("  github_pat_abc\n") == "github_pat_abc"
    try:
        gt.require_fine_grained("ghp_abc")
        assert False, "classic PAT must be rejected"
    except ValueError as exc:
        assert "ghp_" in str(exc)
        assert "classic" in str(exc).lower()
    try:
        gt.require_fine_grained("gho_abc")
        assert False, "oauth token must be rejected"
    except ValueError as exc:
        assert "gho_" in str(exc)


def test_cli_rejects_classic_and_oauth(monkeypatch):
    monkeypatch.setattr(gt.sys, "stdin", io.StringIO("ghp_abc"))
    assert gt.main(["--require-fine-grained"]) == 1
    monkeypatch.setattr(gt.sys, "stdin", io.StringIO("gho_abc"))
    assert gt.main(["--require-fine-grained"]) == 1
    monkeypatch.setattr(gt.sys, "stdin", io.StringIO("github_pat_abc"))
    assert gt.main(["--require-fine-grained"]) == 0


def test_cli_store_does_not_pass_token_on_argv(monkeypatch):
    seen = {}

    def fake_store(token: str) -> None:
        seen["token"] = token

    monkeypatch.setattr(gt, "_store_keychain", fake_store)
    monkeypatch.setattr(gt.sys, "stdin", io.StringIO("github_pat_abc"))
    assert gt.main(["--store"]) == 0
    assert seen["token"] == "github_pat_abc"


def test_setup_and_env_example_do_not_ask_for_classic_scopes():
    setup = (SCRIPTS_DIR / "agent-setup.sh").read_text(encoding="utf-8")
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "repo, read:org" not in setup
    assert "read:org" not in setup
    assert "github_pat_" in setup
    assert "github_token.py" in setup
    assert "--store" in setup
    assert "classic PAT: repo + read:org" not in example
    assert "github_pat_..." in example
    assert "gist" in setup.lower()
    assert "No gist" in setup or "no gist" in setup.lower()


def test_wiki_does_not_document_classic_pat():
    started = (REPO_ROOT / "docs" / "wiki" / "Getting-Started.md").read_text(encoding="utf-8")
    dash = (REPO_ROOT / "docs" / "wiki" / "Dashboard-Guide.md").read_text(encoding="utf-8")
    for text in (started, dash):
        assert "read:org" not in text
        assert "classic PAT" not in text
        assert "github_pat_" in text
