import asyncio
import shutil
from typing import AsyncIterator

from backends.base import AgentBackend


class ClaudeBackend(AgentBackend):
    """Runs Claude Code CLI headlessly: `claude --print -p <prompt>`."""

    def __init__(self) -> None:
        self._pending_messages: list[str] = []

    async def run(self, prompt: str, worktree: str) -> AsyncIterator[str]:
        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("claude CLI not found in PATH — install Claude Code CLI")

        proc = await asyncio.create_subprocess_exec(
            claude_bin, "--print", "-p", prompt,
            cwd=worktree,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield line.decode("utf-8", errors="replace").rstrip()

        await proc.wait()
        if proc.returncode and proc.returncode != 0:
            yield f"[claude] exited with code {proc.returncode}"

    async def inject(self, message: str) -> None:
        # Queue for next invocation — Claude CLI is non-interactive when using --print
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
        return out.decode("utf-8", errors="replace").strip()
