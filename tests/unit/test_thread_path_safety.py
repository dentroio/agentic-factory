"""Guards: thread WO ids and image names cannot escape their roots (AF-28)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"


def _load_thread():
    if str(ORCH) not in sys.path:
        sys.path.insert(0, str(ORCH))
    spec = importlib.util.spec_from_file_location("factory_thread", ORCH / "thread.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_thread"] = module
    spec.loader.exec_module(module)
    return module


def test_require_wo_id_accepts_factory_ids():
    t = _load_thread()
    assert t.require_wo_id("WO-1078") == "WO-1078"
    assert t.require_wo_id("wo-1") == "WO-1"


def test_require_wo_id_rejects_traversal():
    t = _load_thread()
    for bad in ("", "..", "../WO-1", "WO-1/../x", "WO-1.json", "threads", "WO-", "WO-x"):
        with pytest.raises(t.UnsafePath):
            t.require_wo_id(bad)


def test_require_image_filename_rejects_traversal():
    t = _load_thread()
    assert t.require_image_filename("20260816200000.png") == "20260816200000.png"
    for bad in ("", "..", ".", "../x.png", "a/b.png", "a\\b.png"):
        with pytest.raises(t.UnsafePath):
            t.require_image_filename(bad)


def test_contained_path_blocks_dotdot(tmp_path):
    t = _load_thread()
    root = tmp_path / "images"
    root.mkdir()
    inside = t.contained_path(root, "WO-1", "shot.png")
    assert inside.is_relative_to(root.resolve())
    with pytest.raises(t.UnsafePath):
        t.contained_path(root, "..", "shot.png")
    with pytest.raises(t.UnsafePath):
        t.contained_path(root, "WO-1", "..", "shot.png")


def test_save_thread_refuses_unsafe_wo(tmp_path, monkeypatch):
    t = _load_thread()
    monkeypatch.setattr(t, "THREADS_DIR", tmp_path)
    with pytest.raises(t.UnsafePath):
        t.save_thread("..", [{"id": "1"}])
    t.save_thread("WO-1", [{"id": "1"}])
    assert (tmp_path / "WO-1.json").is_file()
    assert list(tmp_path.glob("*.json")) == [tmp_path / "WO-1.json"]


def test_orchestrator_thread_routes_validate():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    assert "def _thread_wo(" in text
    assert "contained_path(DATA_DIR / \"threads\" / \"images\"" in text
    assert "DATA_DIR / \"threads\" / \"images\" / wo / filename" not in text
