import asyncio
import os
import shutil
from typing import AsyncIterator

from backends.base import AgentBackend


class CursorBackend(AgentBackend):
    """
    Agentic execution: Cursor agent CLI (`agent --print <prompt>`).
    Text Q&A / review (ask): `agent --print --mode ask <question>` — read-only, no file edits.

    Install: curl https://cursor.com/install -fsS | bash
    Auth:    Uses CURSOR_API_KEY env var or your logged-in Cursor account (subscription).

    The `agent` binary is installed to ~/.local/bin/agent. Ensure ~/.local/bin is in PATH.

    --print makes the agent non-interactive (outputs to stdout, no TUI).
    --mode ask restricts to read-only Q&A — the agent cannot edit files in this mode.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key or os.getenv("CURSOR_API_KEY", "")
        self._pending_messages: list[str] = []

    def _find_bin(self) -> str | None:
        # The Cursor headless install puts 'agent' in ~/.local/bin
        for candidate in [
            shutil.which("agent"),
            os.path.expanduser("~/.local/bin/agent"),
            os.path.expanduser("~/.local/bin/cursor-agent"),
        ]:
            if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    def _env(self) -> dict:
        env = dict(os.environ)
        if self._api_key:
            env["CURSOR_API_KEY"] = self._api_key
        return env

    async def run(self, prompt: str, worktree: str) -> AsyncIterator[str]:
        agent_bin = self._find_bin()
        if not agent_bin:
            raise RuntimeError(
                "Cursor agent CLI not found — install: curl https://cursor.com/install -fsS | bash"
            )

        full_prompt = prompt
        if self._pending_messages:
            full_prompt += "\n\n[Additional context]\n" + "\n".join(self._pending_messages)
            self._pending_messages.clear()

        proc = await asyncio.create_subprocess_exec(
            agent_bin, "--print", full_prompt,
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
        if proc.returncode and proc.returncode != 0:
            yield f"[cursor-agent] exited with code {proc.returncode}"

    async def inject(self, message: str) -> None:
        self._pending_messages.append(message)

    async def ask(self, question: str) -> str:
        """
        Pure read-only Q&A via `agent --print --mode ask`.

        --mode ask restricts Cursor to explanations and answers only — no file edits,
        no shell commands. Safe to call during peer review without touching the worktree.
        Falls back to Claude CLI if the agent binary is not installed.
        """
        agent_bin = self._find_bin()
        if agent_bin:
            try:
                proc = await asyncio.create_subprocess_exec(
                    agent_bin, "--print", "--mode", "ask", question,
                    env=self._env(),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                assert proc.stdout is not None
                out, _ = await proc.communicate()
                text = out.decode("utf-8", errors="replace").strip()
                if text:
                    return text
            except Exception:
                pass

        # Fall back to Claude CLI (subscription-based)
        claude_bin = shutil.which("claude")
        if claude_bin:
            try:
                proc = await asyncio.create_subprocess_exec(
                    claude_bin, "--print", "-p", question,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                assert proc.stdout is not None
                out, _ = await proc.communicate()
                return out.decode("utf-8", errors="replace").strip()
            except Exception:
                pass

        return (
            "[cursor reviewer: agent CLI not found and claude not available — "
            "install via curl https://cursor.com/install -fsS | bash]"
        )
