"""Guards: git fetch must not put the GitHub token in argv (AF-12)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"


def _load_git_https():
    spec = importlib.util.spec_from_file_location("factory_git_https", ORCH / "git_https.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_git_https"] = module
    spec.loader.exec_module(module)
    return module


def test_fetch_url_has_no_token():
    g = _load_git_https()
    assert g.github_https_url("dentroio/clarion") == "https://github.com/dentroio/clarion.git"
    assert "x-access-token" not in g.github_https_url("dentroio/clarion")


def test_token_is_only_in_env_not_url():
    g = _load_git_https()
    token = "github_pat_example_not_real"
    env = g.git_fetch_env(token, base_env={"PATH": "/usr/bin"})
    assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Bearer {token}"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert token not in g.github_https_url("dentroio/clarion")


def test_redact_secret_strips_token_from_git_stderr():
    g = _load_git_https()
    token = "github_pat_example_not_real"
    raw = f"fatal: could not read Username for 'https://x-access-token:{token}@github.com': No such device"
    assert token not in g.redact_secret(raw, token)
    assert "***" in g.redact_secret(raw, token)


def test_orchestrator_does_not_embed_token_in_git_argv():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    assert "x-access-token:" not in text
    assert "from git_https import git_fetch_env, github_https_url, redact_secret" in text
    assert "env=git_fetch_env(token)" in text
    assert "github_https_url(GITHUB_REPO)" in text
