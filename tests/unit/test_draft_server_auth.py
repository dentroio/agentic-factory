"""Guards: draft server requires a bearer token (AF-07)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "services" / "agent-runner"
ORCH = REPO_ROOT / "services" / "orchestrator"

if str(RUNNER) not in sys.path:
    sys.path.insert(0, str(RUNNER))

import draft_auth  # noqa: E402


def test_missing_secret_is_not_authorized():
    assert not draft_auth.is_authorized("", "Bearer anything-long-enough")
    assert not draft_auth.is_authorized("   ", "Bearer anything-long-enough")


def test_wrong_or_missing_bearer_is_rejected():
    secret = "s" * 43
    assert not draft_auth.is_authorized(secret, "")
    assert not draft_auth.is_authorized(secret, "Bearer wrong-token-value-not-the-secret")
    assert not draft_auth.is_authorized(secret, secret)


def test_matching_bearer_is_accepted():
    secret = "s" * 43
    assert draft_auth.is_authorized(secret, f"Bearer {secret}")


def test_draft_server_gates_every_method():
    text = (RUNNER / "draft_server.py").read_text(encoding="utf-8")
    assert "from draft_auth import is_authorized" in text
    assert "from config import API_SECRET" in text
    for method in ("do_GET", "do_POST", "do_PUT", "do_DELETE"):
        assert f"def {method}" in text
    assert text.count("if not self._require_auth():") >= 4
    assert '"127.0.0.1"' in text


def test_orchestrator_sends_bearer_to_the_runner():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    assert "def _runner_headers()" in text
    assert 'return {"Authorization": f"Bearer {API_SECRET}"}' in text
    needle = 'f"{AGENT_RUNNER_URL}'
    missing = []
    idx = 0
    while True:
        i = text.find(needle, idx)
        if i < 0:
            break
        window = text[i : i + 500]
        if "}/" in window[:80] and "headers=_runner_headers()" not in window:
            missing.append(window.splitlines()[0].strip())
        idx = i + len(needle)
    assert missing == [], f"runner calls missing headers=_runner_headers(): {missing}"
