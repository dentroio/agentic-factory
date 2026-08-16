"""Guards: runner subprocesses time out and are killed (AF-24)."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "services" / "agent-runner"
BACKENDS = RUNNER / "backends"


def _load_proc():
    spec = importlib.util.spec_from_file_location("factory_proc", RUNNER / "proc.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_proc"] = module
    spec.loader.exec_module(module)
    return module


async def test_communicate_returns_stdout():
    proc_mod = _load_proc()
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('ok')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc_mod.communicate(child, timeout=5)
    assert b"ok" in out
    assert child.returncode == 0


async def test_communicate_kills_on_timeout():
    proc_mod = _load_proc()
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    with pytest.raises(asyncio.TimeoutError):
        await proc_mod.communicate(child, timeout=0.3)
    assert child.returncode is not None


def test_runner_has_no_bare_communicate():
    files = [
        RUNNER / "runner.py",
        RUNNER / "review_chain.py",
        RUNNER / "quality_gate.py",
        BACKENDS / "claude.py",
        BACKENDS / "codex.py",
        BACKENDS / "gemini.py",
        BACKENDS / "cursor.py",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert ".communicate(" not in text, f"unbounded communicate in {path.name}"
        assert "from proc import" in text
        assert "communicate" in text
