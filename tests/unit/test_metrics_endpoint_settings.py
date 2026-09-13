"""Unit tests for WO-1099: METRICS_ENDPOINT on Deploy & Harness settings."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator" / "orchestrator.py"
STATUS = REPO_ROOT / "services" / "status-site"
TEMPLATE = STATUS / "templates" / "settings_deploy_harness.html"
HELP = STATUS / "templates" / "base.html"
MAIN = STATUS / "main.py"


def test_orchestrator_reads_and_writes_metrics_endpoint():
    text = ORCH.read_text(encoding="utf-8")
    assert 'await _get_repo_variable(client, engine_repo, "METRICS_ENDPOINT")' in text
    assert '"metrics_endpoint": (metrics_raw or "").strip()' in text
    assert 'if "metrics_endpoint" in body:' in text
    assert 'await _set_repo_variable(client, engine_repo, "METRICS_ENDPOINT", endpoint)' in text
    assert 'await _delete_repo_variable(client, engine_repo, "METRICS_ENDPOINT")' in text


def test_status_site_has_metrics_form_and_route():
    main = MAIN.read_text(encoding="utf-8")
    assert '@app.post("/settings/deploy-harness/metrics"' in main
    assert '"metrics_endpoint": deploy.get("metrics_endpoint") or ""' in main

    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert 'action="/settings/deploy-harness/metrics"' in tpl
    assert 'name="metrics_endpoint"' in tpl
    assert "Observability" in tpl


def test_help_map_documents_observability_section():
    text = HELP.read_text(encoding="utf-8")
    assert "'/settings/deploy-harness'" in text
    assert "Observability" in text
    assert "METRICS_ENDPOINT" in text
