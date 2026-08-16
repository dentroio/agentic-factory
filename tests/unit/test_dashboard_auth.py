"""AF-08: dashboard writes need bearer or loopback Origin — not a human login."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_DIR = REPO_ROOT / "services" / "status-site"
if str(STATUS_DIR) not in sys.path:
    sys.path.insert(0, str(STATUS_DIR))

import dashboard_auth as da  # noqa: E402


def test_require_secret_rejects_empty():
    try:
        da.require_secret("")
    except RuntimeError as exc:
        assert "API_SECRET is not set" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_mutating_methods():
    assert not da.is_mutating("GET")
    assert not da.is_mutating("HEAD")
    assert not da.is_mutating("OPTIONS")
    assert da.is_mutating("POST")
    assert da.is_mutating("PUT")
    assert da.is_mutating("DELETE")


def test_bearer_authorizes_writes():
    secret = "s" * 43
    assert da.is_authorized(secret, f"Bearer {secret}", "")
    assert not da.is_authorized(secret, "Bearer wrong-token-value-not-the-secret", "")
    assert not da.is_authorized("", f"Bearer {secret}", "")


def test_loopback_origin_authorizes_browser_writes():
    secret = "s" * 43
    assert da.is_authorized(secret, "", "http://127.0.0.1:8099")
    assert da.is_authorized(secret, "", "http://localhost:8099")
    assert not da.is_authorized(secret, "", "https://evil.example")
    assert not da.is_authorized(secret, "", "http://127.0.0.1:8099.evil.example")
    assert not da.is_authorized(secret, "", "")


def test_origin_from_referer():
    assert da.origin_from_referer("http://127.0.0.1:8099/factory") == "http://127.0.0.1:8099"
    assert da.origin_from_referer("https://evil.example/page") == "https://evil.example"
    assert da.origin_from_referer("http://user@127.0.0.1:8099/") == ""
    assert da.browser_origin("", "http://localhost:8099/settings") == "http://localhost:8099"
    assert da.browser_origin("http://127.0.0.1:8099", "https://evil.example/") == "http://127.0.0.1:8099"


def test_main_installs_auth_and_fails_closed():
    text = (STATUS_DIR / "main.py").read_text(encoding="utf-8")
    assert "import dashboard_auth" in text
    assert "dashboard_auth.require_secret" in text
    assert "dashboard_auth.install(" in text
    assert "/login" not in text


def test_no_login_page():
    assert not (STATUS_DIR / "templates" / "login.html").exists()
    text = (STATUS_DIR / "dashboard_auth.py").read_text(encoding="utf-8")
    assert "login.html" not in text
    assert "factory_dashboard_session" not in text


def test_compose_dashboard_is_loopback():
    text = (REPO_ROOT / "docker-compose.status.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:8099:8099"' in text
    assert "- \"8099:8099\"" not in text
    assert "- '8099:8099'" not in text
