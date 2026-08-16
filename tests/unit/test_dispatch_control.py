"""Unit tests for dispatch pause helpers and claim-lease matching (WO-1054)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "dispatch_control",
        REPO_ROOT / "services" / "orchestrator" / "dispatch_control.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["dispatch_control"] = module
    spec.loader.exec_module(module)
    return module


m = _load()


def test_lease_matches_only_the_issued_token():
    token = m.issue_claim_token()
    assert m.lease_matches(token, token)
    assert not m.lease_matches(token, "nope")
    assert not m.lease_matches(token, "")
    assert not m.lease_matches(token, None)
    assert not m.lease_matches("", token)
    assert not m.lease_matches(None, None)


def test_issue_claim_token_is_unique():
    tokens = {m.issue_claim_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(t) >= 32 for t in tokens)


def test_save_and_load_pause(tmp_path):
    path = tmp_path / "factory_paused.json"
    assert m.load_pause(path) == {"paused": False, "reason": ""}
    m.save_pause(path, True, "audit closeout")
    loaded = m.load_pause(path)
    assert loaded["paused"] is True
    assert loaded["reason"] == "audit closeout"
    m.save_pause(path, False)
    assert m.load_pause(path)["paused"] is False


def test_corrupt_pause_file_is_not_paused(tmp_path):
    path = tmp_path / "factory_paused.json"
    path.write_text("{not json")
    assert m.load_pause(path)["paused"] is False


def test_merge_allowed_only_for_p2_p3():
    assert m.merge_allowed_for_priority("P2")
    assert m.merge_allowed_for_priority("p3")
    assert not m.merge_allowed_for_priority("P0")
    assert not m.merge_allowed_for_priority("P1")
    assert not m.merge_allowed_for_priority(None)
    assert not m.merge_allowed_for_priority("")
    assert not m.merge_allowed_for_priority("unknown")


def test_run_local_sh_refuses_to_start_without_api_secret():
    text = (REPO_ROOT / "services" / "agent-runner" / "run-local.sh").read_text()
    assert 'if [ -z "${API_SECRET:-}" ]; then' in text
    assert "The orchestrator refuses unauthenticated calls. Refusing to start." in text
    assert "\n    exit 1\nfi\n" in text


def test_attempt_counts_survive_missing_and_corrupt_files(tmp_path):
    path = tmp_path / "attempt_counts.json"
    assert m.load_attempt_counts(path) == {}
    path.write_text("{not json")
    assert m.load_attempt_counts(path) == {}
    path.write_text('{"WO-1": 2, "WO-2": "nope", "WO-3": 0}')
    assert m.load_attempt_counts(path) == {"WO-1": 2}


def test_recorded_attempts_prefers_the_higher_count():
    counts = {"WO-10": 2}
    assert m.recorded_attempts(counts, "WO-10", 1) == 2
    assert m.recorded_attempts(counts, "WO-10", 4) == 4
    assert m.recorded_attempts({}, "WO-10", 3) == 3
    assert m.recorded_attempts({}, "WO-11", 0) == 0


def test_record_and_clear_attempt_round_trip(tmp_path):
    path = tmp_path / "attempt_counts.json"
    counts: dict[str, int] = {}
    m.record_attempt(counts, "WO-12", 2)
    m.save_attempt_counts(path, counts)
    loaded = m.load_attempt_counts(path)
    assert loaded["WO-12"] == 2
    m.clear_attempt(loaded, "WO-12")
    m.save_attempt_counts(path, loaded)
    assert "WO-12" not in m.load_attempt_counts(path)


def test_claim_and_reset_use_persisted_attempt_counts():
    text = (REPO_ROOT / "services" / "orchestrator" / "orchestrator.py").read_text()
    assert "ATTEMPTS_PATH" in text
    assert "recorded_attempts(" in text
    assert "clear_attempt(_attempt_counts, wo_id)" in text
    assert "save_attempt_counts(ATTEMPTS_PATH, _attempt_counts)" in text


def test_atomic_write_json_replaces_without_leaving_tmp(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"old": true}')
    m.atomic_write_json(path, {"new": 1})
    assert path.read_text(encoding="utf-8").strip().startswith("{")
    assert '"new"' in path.read_text(encoding="utf-8")
    assert not path.with_name("state.json.tmp").exists()


def test_dispatch_and_thread_saves_use_atomic_write():
    orch = (REPO_ROOT / "services" / "orchestrator" / "orchestrator.py").read_text()
    thread = (REPO_ROOT / "services" / "orchestrator" / "thread.py").read_text()
    assert "DISPATCH_STATE_PATH.write_text" not in orch
    assert "HOLD_PATH.write_text" not in orch
    assert "VALIDATIONS_PATH.write_text" not in orch
    assert "atomic_write_json(DISPATCH_STATE_PATH" in orch
    assert "atomic_write_json(HOLD_PATH" in orch
    assert "atomic_write_json(VALIDATIONS_PATH" in orch
    assert "atomic_write_json(THREADS_DIR" in thread
    assert ".write_text(json.dumps(messages" not in thread


def test_live_claim_skips_vanished_and_finished_entries():
    state = {
        "WO-1": {"status": "claimed", "agent": "a"},
        "WO-2": {"status": "in_progress", "agent": "b"},
        "WO-3": {"status": "complete", "agent": "c"},
        "WO-4": "not a dict",
    }
    assert m.live_claim(state, "WO-1") is state["WO-1"]
    assert m.live_claim(state, "WO-2") is state["WO-2"]
    assert m.live_claim(state, "WO-3") is None
    assert m.live_claim(state, "WO-4") is None
    assert m.live_claim(state, "WO-missing") is None
    del state["WO-1"]
    assert m.live_claim(state, "WO-1") is None


def test_stale_sweep_re_reads_before_mutating():
    orch = (REPO_ROOT / "services" / "orchestrator" / "orchestrator.py").read_text()
    assert "live_claim(_dispatch_state, wo_id)" in orch
    assert '_dispatch_state[wo_id]["status"] = "stale"' not in orch
    assert '_dispatch_state[wo_id]["status"] = "awaiting_human"' not in orch
    assert "stale-sweep {wo_id} failed" in orch
    assert "_preflight_held.get(wo_id)" in orch