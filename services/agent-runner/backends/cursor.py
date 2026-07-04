import asyncio
import os
import shutil
from typing import AsyncIterator

from backends.base import AgentBackend


class CursorBackend(AgentBackend):
    """Runs Cursor headless CLI: `agent --print -p <prompt> --force`."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._pending_messages: list[str] = []

    def _env(self) -> dict:
        env = dict(os.environ)
        if self._api_key:
            env["CURSOR_API_KEY"] = self._api_key
        return env

    async def run(self, prompt: str, worktree: str) -> AsyncIterator[str]:
        agent_bin = shutil.which("agent")
        if not agent_bin:
            raise RuntimeError("Cursor 'agent' CLI not found in PATH")

        full_prompt = prompt
        if self._pending_messages:
            full_prompt += "\n\n[Additional context]\n" + "\n".join(self._pending_messages)
            self._pending_messages.clear()

        proc = await asyncio.create_subprocess_exec(
            agent_bin, "-p", "--force", full_prompt,
            cwd=worktree,
            env=self._env(),
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

    async def inject(self, message: str) -> None:
        self._pending_messages.append(message)

    async def ask(self, question: str) -> str:
        agent_bin = shutil.which("agent")
        if not agent_bin:
            return "[cursor agent not available]"
        proc = await asyncio.create_subprocess_exec(
            agent_bin, "-p", question,
            env=self._env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        out, _ = await proc.communicate()
        return out.decode("utf-8", errors="replace").strip()
