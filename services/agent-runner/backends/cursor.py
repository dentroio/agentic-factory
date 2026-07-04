import asyncio
import os
import shutil
from typing import AsyncIterator

from backends.base import AgentBackend


class CursorBackend(AgentBackend):
    """
    Agentic execution: Cursor headless CLI (`agent -p --force <prompt>`).
    Text Q&A / review (ask): Cursor has no public text API.

    For ask(), we fall back in order:
      1. OpenAI chat completions (if OPENAI_API_KEY is set)
      2. Claude CLI `--print` mode (if claude is in PATH)
      3. Error string (review is skipped with a warning)

    This ensures that setting ARCH_REVIEWER_BACKEND=cursor doesn't silently
    corrupt the worktree by triggering an agentic file-editing session.
    """

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
        """
        Pure text Q&A — does NOT invoke the Cursor CLI (which would edit files).

        Falls back to OpenAI API, then Claude CLI.
        """
        # 1. OpenAI API
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if openai_key:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=openai_key)
                response = await client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": question}],
                    max_tokens=2048,
                    temperature=0.2,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                pass  # fall through to Claude

        # 2. Claude CLI --print (non-agentic, pure text output)
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
            "[cursor reviewer: no text API available — set OPENAI_API_KEY "
            "or ensure claude CLI is in PATH to use Cursor as a reviewer]"
        )
