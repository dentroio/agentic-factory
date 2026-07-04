import asyncio
import os
import shutil
from typing import AsyncIterator

from backends.base import AgentBackend


class CodexBackend(AgentBackend):
    """
    Agentic execution: OpenAI Codex CLI (`codex exec -p <prompt>`).
    Text Q&A / review (ask): OpenAI chat completions API directly.

    The CLI is an agentic file editor — calling it for a review question would
    mutate worktree files instead of returning analysis text. For ask(), we go
    directly to the OpenAI API so reviewers receive clean text output.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")

    def _env(self) -> dict:
        env = dict(os.environ)
        if self._api_key:
            env["OPENAI_API_KEY"] = self._api_key
        return env

    async def run(self, prompt: str, worktree: str) -> AsyncIterator[str]:
        codex_bin = shutil.which("codex")
        if not codex_bin:
            raise RuntimeError("codex CLI not found in PATH")

        proc = await asyncio.create_subprocess_exec(
            codex_bin, "exec", "-p", prompt,
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

    async def ask(self, question: str) -> str:
        """Use OpenAI chat completions API — pure text, no file mutations."""
        if not self._api_key:
            return "[codex reviewer: OPENAI_API_KEY not set — skipped]"
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self._api_key)
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": question}],
                max_tokens=2048,
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[codex reviewer error: {e}]"
