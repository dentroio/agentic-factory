"""Bounded subprocess communicate with kill-on-timeout (AF-24)."""
from __future__ import annotations

import asyncio

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


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.kill()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (asyncio.TimeoutError, ProcessLookupError):
        pass
