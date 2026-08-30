"""Unit tests for WO-1088: Durable Orchestrator Run History & Audit Trail."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"
STATUS_SITE = REPO_ROOT / "services" / "status-site"


def _load_db():
    spec = importlib.util.spec_from_file_location("factory_db_history", ORCH / "db.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_db_history"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db_mod():
    return _load_db()


@pytest.fixture
def temp_db(db_mod, tmp_path: Path) -> Path:
    db_path = tmp_path / "test_factory.db"
    db_mod.init_history_table(db_path)
    return db_path


def test_init_history_table_idempotent(db_mod, temp_db: Path):
    # Running twice should not raise errors
    db_mod.init_history_table(temp_db)
    with db_mod.connect(temp_db) as conn:
        conn.row_factory = sqlite3.Row
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t["name"] for t in tables]
        assert "run_history" in table_names


def test_record_and_get_run_history(db_mod, temp_db: Path):
    rec1 = {
        "wo": "WO-496",
        "slug": "suppress-same-value-events",
        "agent": "cursor-01",
        "backend": "cursor",
        "workstation": "mac-mini",
        "claimed_at": "2026-08-30T01:00:00+00:00",
        "completed_at": "2026-08-30T01:15:00+00:00",
        "final_status": "complete",
        "step": "merged by cursor-01",
        "attempt_count": 1,
        "pr_number": 750,
        "pr_url": "https://github.com/dentroio/clarion/pull/750",
        "review_verdicts": {"security": "APPROVE", "architecture": "APPROVE"},
    }
    id1 = db_mod.record_run_history(temp_db, rec1)
    assert id1 > 0

    rec2 = {
        "wo": "WO-497",
        "slug": "fix-nats-reconnect",
        "agent": "claude-02",
        "backend": "claude",
        "claimed_at": "2026-08-30T02:00:00+00:00",
        "completed_at": "2026-08-30T02:10:00+00:00",
        "final_status": "failed",
        "failure_category": "code",
        "failure_reason": "pytest failed in test_nats.py",
        "attempt_count": 1,
    }
    id2 = db_mod.record_run_history(temp_db, rec2)
    assert id2 > id1

    # Query all
    all_runs = db_mod.get_run_history(temp_db)
    assert len(all_runs) == 2
    assert all_runs[0]["wo"] == "WO-497"  # Most recent first
    assert all_runs[0]["final_status"] == "failed"
    assert all_runs[0]["failure_category"] == "code"
    assert all_runs[0]["duration_seconds"] == 600

    assert all_runs[1]["wo"] == "WO-496"
    assert all_runs[1]["duration_seconds"] == 900
    assert all_runs[1]["final_status"] == "complete"
    assert all_runs[1]["review_verdicts"] == {"security": "APPROVE", "architecture": "APPROVE"}


def test_get_run_history_filters(db_mod, temp_db: Path):
    for i in range(5):
        db_mod.record_run_history(temp_db, {
            "wo": f"WO-{100 + i}",
            "agent": "agent-a" if i % 2 == 0 else "agent-b",
            "backend": "claude",
            "final_status": "complete" if i < 3 else "failed",
        })

    by_wo = db_mod.get_run_history(temp_db, wo="WO-101")
    assert len(by_wo) == 1
    assert by_wo[0]["wo"] == "WO-101"

    by_status = db_mod.get_run_history(temp_db, status="failed")
    assert len(by_status) == 2

    by_agent = db_mod.get_run_history(temp_db, agent="agent-a")
    assert len(by_agent) == 3

    # Limit and offset
    page1 = db_mod.get_run_history(temp_db, limit=2, offset=0)
    page2 = db_mod.get_run_history(temp_db, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["id"] != page2[0]["id"]


def test_get_run_metrics(db_mod, temp_db: Path):
    db_mod.record_run_history(temp_db, {
        "wo": "WO-101",
        "backend": "claude",
        "claimed_at": "2026-08-30T00:00:00+00:00",
        "completed_at": "2026-08-30T00:10:00+00:00",
        "final_status": "complete",
    })
    db_mod.record_run_history(temp_db, {
        "wo": "WO-102",
        "backend": "claude",
        "claimed_at": "2026-08-30T01:00:00+00:00",
        "completed_at": "2026-08-30T01:20:00+00:00",
        "final_status": "complete",
    })
    db_mod.record_run_history(temp_db, {
        "wo": "WO-103",
        "backend": "cursor",
        "final_status": "failed",
        "failure_category": "lock_timeout",
    })
    db_mod.record_run_history(temp_db, {
        "wo": "WO-104",
        "backend": "cursor",
        "final_status": "released",
    })

    metrics = db_mod.get_run_metrics(temp_db)
    assert metrics["total_runs"] == 4
    assert metrics["completed_runs"] == 2
    assert metrics["failed_runs"] == 1
    assert metrics["released_runs"] == 1
    assert metrics["pass_rate_pct"] == 50.0
    assert metrics["avg_duration_seconds"] == 900.0  # (600 + 1200) / 2
    assert "claude" in metrics["by_backend"]
    assert metrics["by_backend"]["claude"]["completed"] == 2
    assert metrics["by_backend"]["claude"]["avg_duration_seconds"] == 900.0
    assert metrics["by_failure_category"] == {"lock_timeout": 1}


def test_orchestrator_source_has_history_integration():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    assert "init_history_table as _db_init_history_table" in text
    assert "record_run_history as _db_record_run_history" in text
    assert "get_run_history as _db_get_run_history" in text
    assert "get_run_metrics as _db_get_run_metrics" in text
    assert '@app.get("/api/history")' in text
    assert '@app.get("/api/history/metrics")' in text
    assert '@app.get("/api/history/{wo_id}")' in text


def test_status_site_source_has_history_dashboard():
    text = (STATUS_SITE / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/history"' in text
    assert '@app.get("/api/history")' in text
    assert '@app.get("/api/history/metrics")' in text
    template_file = STATUS_SITE / "templates" / "history.html"
    assert template_file.exists()
    t_text = template_file.read_text(encoding="utf-8")
    assert "Execution History & Audit Trail" in t_text
    assert "history-table" in t_text
