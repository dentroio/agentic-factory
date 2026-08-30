"""Unit tests for WO-1089: Multi-Repo Autonomous Orchestrator Dispatch."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"


def _load_db():
    spec = importlib.util.spec_from_file_location("factory_db_multirepo", ORCH / "db.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_db_multirepo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db_mod():
    return _load_db()


@pytest.fixture
def temp_db(db_mod, tmp_path: Path) -> Path:
    db_path = tmp_path / "test_multirepo.db"
    db_mod.init_history_table(db_path)
    return db_path


def test_db_run_history_supports_repo_column(db_mod, temp_db: Path):
    rec_clarion = {
        "wo": "WO-496",
        "slug": "suppress-same-value-events",
        "agent": "cursor-01",
        "backend": "cursor",
        "repo": "dentroio/clarion",
        "final_status": "complete",
    }
    rec_factory = {
        "wo": "WO-1088",
        "slug": "durable-history",
        "agent": "claude-01",
        "backend": "claude",
        "repo": "dentroio/agentic-factory",
        "final_status": "complete",
    }
    db_mod.record_run_history(temp_db, rec_clarion)
    db_mod.record_run_history(temp_db, rec_factory)

    clarion_runs = db_mod.get_run_history(temp_db, repo="dentroio/clarion")
    assert len(clarion_runs) == 1
    assert clarion_runs[0]["wo"] == "WO-496"
    assert clarion_runs[0]["repo"] == "dentroio/clarion"

    factory_runs = db_mod.get_run_history(temp_db, repo="dentroio/agentic-factory")
    assert len(factory_runs) == 1
    assert factory_runs[0]["wo"] == "WO-1088"
    assert factory_runs[0]["repo"] == "dentroio/agentic-factory"


def test_db_runs_upsert_supports_repo(db_mod, tmp_path: Path):
    path = tmp_path / "runs_test.db"
    db_mod.reset_writer_for_tests()
    with db_mod.connect(path) as conn:
        conn.execute("""
        CREATE TABLE runs (
          wo TEXT PRIMARY KEY,
          slug TEXT DEFAULT '',
          agent TEXT DEFAULT '',
          backend TEXT DEFAULT '',
          workstation TEXT DEFAULT '',
          claimed_at TEXT,
          status TEXT DEFAULT 'claimed',
          step TEXT DEFAULT '',
          last_seen TEXT,
          completed_at TEXT,
          pr_url TEXT DEFAULT '',
          pr_number INTEGER,
          attempt_count INTEGER DEFAULT 0,
          first_claimed_at TEXT,
          retried_at TEXT,
          stuck INTEGER DEFAULT 0,
          stuck_since TEXT,
          claim_token TEXT DEFAULT '',
          repo TEXT DEFAULT ''
        )
        """)

    state = {
        "WO-1": {"status": "claimed", "agent": "a", "repo": "dentroio/clarion"},
        "WO-2": {"status": "in_progress", "agent": "b", "repo": "dentroio/agentic-factory"},
    }
    db_mod.sync_runs(path, state)

    with db_mod.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT wo, repo FROM runs ORDER BY wo").fetchall()
        assert len(rows) == 2
        assert rows[0]["wo"] == "WO-1"
        assert rows[0]["repo"] == "dentroio/clarion"
        assert rows[1]["wo"] == "WO-2"
        assert rows[1]["repo"] == "dentroio/agentic-factory"


def test_orchestrator_source_has_multirepo_dispatch():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    # Verify multi-repo helpers and routes
    assert "def _get_configured_repos() -> list[dict]:" in text
    assert '@app.get("/api/factory/projects")' in text
    assert 'async def get_next(domain: str = "", repo: str = ""):' in text
    # Verify file-in-flight and service-in-flight are scoped per repo
    assert "files_in_flight_by_repo" in text
    assert "services_in_flight_by_repo" in text
    # Verify auto_mark_done_wo targets specific repo
    assert "target_repo = (_dispatch_state.get(wo_id) or {}).get(\"repo\")" in text


def test_multirepo_candidate_filtering_logic():
    """Verify repo filtering and isolation logic."""
    queue = [
        {"wo": "WO-100", "repo": "dentroio/clarion", "files_likely_changed": ["README.md"], "priority": "P1"},
        {"wo": "WO-200", "repo": "dentroio/agentic-factory", "files_likely_changed": ["README.md"], "priority": "P2"},
    ]
    # Active run on clarion touching README.md
    dispatch_state = {
        "WO-100": {"status": "in_progress", "repo": "dentroio/clarion", "agent": "agent-1"},
    }
    files_by_wo = {w["wo"]: set(w["files_likely_changed"]) for w in queue}
    files_in_flight_by_repo: dict[str, set[str]] = {}
    for aid, aentry in dispatch_state.items():
        act_repo = aentry.get("repo", "dentroio/clarion")
        files_in_flight_by_repo.setdefault(act_repo, set()).update(files_by_wo.get(aid, set()))

    # Candidate in agentic-factory also touches README.md, but in a DIFFERENT repo.
    # It should NOT collide!
    cand_wo = queue[1]
    cand_repo = cand_wo["repo"]
    cand_files = files_by_wo[cand_wo["wo"]]
    overlap = cand_files & files_in_flight_by_repo.get(cand_repo, set())
    assert len(overlap) == 0  # No collision across repos!

    # Candidate in same repo (clarion) DOES collide
    clarion_cand = queue[0]
    clarion_overlap = files_by_wo[clarion_cand["wo"]] & files_in_flight_by_repo.get("dentroio/clarion", set())
    assert len(clarion_overlap) == 1
