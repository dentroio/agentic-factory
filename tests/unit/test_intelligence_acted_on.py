"""Tests for intelligence._acted_on persistence (WO-1041)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORCH_DIR = Path(__file__).resolve().parents[2] / "services" / "orchestrator"
sys.path.insert(0, str(ORCH_DIR))


def test_acted_on_survives_restart(tmp_path, monkeypatch):
    """_acted_on written to disk by _flush_acted_on; re-loaded by _load_acted_on."""
    import intelligence as intel

    acted_on_path = tmp_path / "intelligence_acted_on.json"
    monkeypatch.setattr(intel, "_ACTED_ON_PATH", acted_on_path)
    monkeypatch.setattr(intel, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(intel, "_acted_on", {})

    # Mark an action and flush
    intel._mark_acted("close_major", "99")
    intel._flush_acted_on()

    assert acted_on_path.exists()
    data = json.loads(acted_on_path.read_text())
    assert "close_major:99" in data

    # Simulate restart: clear in-memory dict and reload from disk
    intel._acted_on.clear()
    assert not intel._already_acted("close_major", "99")  # gone from memory

    intel._load_acted_on()
    assert intel._already_acted("close_major", "99")  # back after reload


def test_acted_on_no_duplicate_after_restart(tmp_path, monkeypatch):
    """After reload, _already_acted prevents repeated actions."""
    import intelligence as intel

    acted_on_path = tmp_path / "intelligence_acted_on.json"
    monkeypatch.setattr(intel, "_ACTED_ON_PATH", acted_on_path)
    monkeypatch.setattr(intel, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(intel, "_acted_on", {})

    intel._mark_acted("ghost_cleanup", "WO-999")
    intel._flush_acted_on()

    intel._acted_on.clear()
    intel._load_acted_on()

    assert intel._already_acted("ghost_cleanup", "WO-999")


def test_acted_on_load_handles_missing_file(tmp_path, monkeypatch):
    """_load_acted_on doesn't crash when the file doesn't exist."""
    import intelligence as intel

    monkeypatch.setattr(intel, "_ACTED_ON_PATH", tmp_path / "nonexistent.json")
    monkeypatch.setattr(intel, "_acted_on", {})

    intel._load_acted_on()  # should not raise
    assert intel._acted_on == {}
