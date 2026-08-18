"""Bounded subprocess communicate with kill-on-timeout (AF-24)."""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess

GIT = 30
GIT_PUSH = 120
GIT_FETCH = 60
WO_START = 120
GH = 60
ASK = 120


async def communicate(
    proc: asyncio.subprocess.Process,
    timeout: float,
) -> tuple[bytes | None, bytes | None]:
    """Wait for stdout/stderr, then kill the child if it overruns `timeout`."""
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _kill(proc)
        raise


def _kill_descendants(pid: int) -> None:
    """SIGKILL children of pid, deepest first.

    `make ci-local` shares the runner process group, so a timeout that only
    kills `make` leaves `npx tsc` running. That leftover compile starved the
    next WO and made both look like test failures.
    """
    try:
        out = subprocess.check_output(
            ["pgrep", "-P", str(pid)], text=True, stderr=subprocess.DEVNULL,
        )
        children = [int(line) for line in out.split() if line.strip().isdigit()]
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        children = []
    for child in children:
        _kill_descendants(child)
        try:
            os.kill(child, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    pid = proc.pid
    # Only kill the process group when this child is the group leader
    # (start_new_session=True). Otherwise killpg would take down the runner.
    try:
        if pid is not None and os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGKILL)
        else:
            if pid is not None:
                _kill_descendants(pid)
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            if pid is not None:
                _kill_descendants(pid)
            proc.kill()
        except ProcessLookupError:
            return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (asyncio.TimeoutError, ProcessLookupError):
        pass
