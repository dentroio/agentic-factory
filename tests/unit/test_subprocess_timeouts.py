"""Guards: runner subprocesses time out and are killed (AF-24)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
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


async def test_communicate_kills_grandchild_on_timeout(tmp_path):
    """Timeout must kill make's children (npx tsc), not only make itself."""
    proc_mod = _load_proc()
    pid_file = tmp_path / "grand.pid"
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-c",
        (
            "import os, time, pathlib\n"
            f"path = pathlib.Path({str(pid_file)!r})\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    time.sleep(60)\n"
            "else:\n"
            "    path.write_text(str(pid))\n"
            "    time.sleep(60)\n"
        ),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    grand = None
    for _ in range(50):
        if pid_file.exists() and pid_file.read_text().strip().isdigit():
            grand = int(pid_file.read_text().strip())
            break
        await asyncio.sleep(0.05)
    assert grand is not None
    with pytest.raises(asyncio.TimeoutError):
        await proc_mod.communicate(child, timeout=0.4)
    assert child.returncode is not None
    await asyncio.sleep(0.2)
    with pytest.raises(OSError):
        os.kill(grand, 0)


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


def test_quality_gate_ci_is_isolated_and_budgeted():
    text = (RUNNER / "quality_gate.py").read_text(encoding="utf-8")
    run_fn = text.split("async def _run")[1].split("async def ")[0]
    assert "start_new_session=True" in run_fn
    assert "_CI_RUN_TIMEOUT = 2700" in text
    assert "_CI_LOCK_TIMEOUT = 2700" in text
    assert "timeout=_CI_RUN_TIMEOUT" in text


def test_reentry_keeps_uncommitted_worktree_state():
    setup = (RUNNER / "runner.py").read_text(encoding="utf-8").split(
        "async def _setup_worktree"
    )[1].split("async def ")[0]
    assert "git stash" not in setup
    assert "keeping uncommitted state for re-entry" in setup


def test_parallel_sdk_review_is_bounded():
    text = (RUNNER / "review_chain.py").read_text(encoding="utf-8")
    sync_start = text.index("def _run_sdk_reviewer_sync")
    async_start = text.index("async def _run_sdk_reviewer")
    async_end = text.index("# Config", async_start)
    sync_body = text[sync_start:async_start]
    async_body = text[async_start:async_end]
    assert "timeout=" in sync_body
    assert "Anthropic(" in sync_body
    assert "wait_for" in async_body
    assert "timeout=ASK" in async_body
