import asyncio
import re
import shutil
from typing import AsyncIterator

from backends.base import AgentBackend, QuotaExceededError

# Claude Code emits these when the subscription usage cap is hit
_QUOTA_RE = re.compile(
    r"usage limit reached|rate limit|you've reached your|claude\.ai usage|"
    r"exceeded.*limit|limit.*exceeded|upgrade your plan|claude\.ai/upgrade",
    re.I,
)


class ClaudeBackend(AgentBackend):
    """Runs Claude Code CLI headlessly with auto-approved permissions."""

    def __init__(self) -> None:
        self._pending_messages: list[str] = []

    async def run(self, prompt: str, worktree: str) -> AsyncIterator[str]:
        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("claude CLI not found in PATH — install Claude Code CLI")

        proc = await asyncio.create_subprocess_exec(
            claude_bin, "--print", "--permission-mode", "bypassPermissions", "-p", prompt,
            cwd=worktree,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            yield text
            if _QUOTA_RE.search(text):
                proc.kill()
                await proc.wait()
                raise QuotaExceededError(f"claude quota exhausted: {text.strip()}")

        await proc.wait()
        if proc.returncode and proc.returncode != 0:
            yield f"[claude] exited with code {proc.returncode}"

    async def inject(self, message: str) -> None:
        self._pending_messages.append(message)

    async def ask(self, question: str) -> str:
        claude_bin = shutil.which("claude")
        if not claude_bin:
            return "[claude not available]"
        proc = await asyncio.create_subprocess_exec(
            claude_bin, "--print", "-p", question,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        out, _ = await proc.communicate()
        text = out.decode("utf-8", errors="replace").strip()
        if _QUOTA_RE.search(text):
            raise QuotaExceededError(f"claude quota exhausted: {text[:120]}")
        return text
