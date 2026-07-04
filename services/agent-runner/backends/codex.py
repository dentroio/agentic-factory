from typing import AsyncIterator

from backends.base import AgentBackend


class CodexBackend(AgentBackend):
    """Runs OpenAI Codex via the TypeScript/Python SDK.

    Requires: npm install -g @openai/codex or pip install openai-codex (when available).
    Falls back to a subprocess call if the SDK is not importable.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._thread = None

    async def run(self, prompt: str, worktree: str) -> AsyncIterator[str]:
        try:
            import subprocess
            import shutil
            codex_bin = shutil.which("codex")
            if not codex_bin:
                raise RuntimeError("codex CLI not found in PATH")

            import asyncio
            import os
            env = dict(os.environ)
            if self._api_key:
                env["OPENAI_API_KEY"] = self._api_key

            proc = await asyncio.create_subprocess_exec(
                codex_bin, "exec", "-p", prompt,
                cwd=worktree,
                env=env,
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

        except Exception as e:
            yield f"[codex] error: {e}"

    async def ask(self, question: str) -> str:
        try:
            import asyncio
            import os
            import shutil
            codex_bin = shutil.which("codex")
            if not codex_bin:
                return "[codex not available]"
            env = dict(os.environ)
            if self._api_key:
                env["OPENAI_API_KEY"] = self._api_key
            proc = await asyncio.create_subprocess_exec(
                codex_bin, "exec", "-p", question,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            assert proc.stdout is not None
            out, _ = await proc.communicate()
            return out.decode("utf-8", errors="replace").strip()
        except Exception as e:
            return f"[codex error: {e}]"
