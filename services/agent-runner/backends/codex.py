import asyncio
import re
import shutil
from typing import AsyncIterator

from backends.base import AgentBackend, BackendHangError, QuotaExceededError

_FIRST_OUTPUT_TIMEOUT = 45  # seconds before we declare the backend hung

# OpenAI surfaces quota/rate-limit errors as text in CLI output
_QUOTA_RE = re.compile(
    r"rate limit exceeded|insufficient.quota|you exceeded your.*quota|"
    r"429|quota.*exceeded|exceeded.*quota|billing.*limit|"
    r"exceeded your current quota",
    re.I,
)


class CodexBackend(AgentBackend):
    """
    Agentic execution: OpenAI Codex CLI (`codex exec <prompt>`).
    Text Q&A / review (ask): `codex review <instructions>` — non-interactive code review.

    Install: npm install -g @openai/codex
    Auth:    codex login   (OAuth to your OpenAI account — uses ChatGPT/OpenAI subscription)

    No API key required. All calls go through your subscription, not pay-per-use API billing.
    """

    def __init__(self) -> None:
        pass

    def _find_bin(self) -> str | None:
        return shutil.which("codex")

    async def run(self, prompt: str, worktree: str) -> AsyncIterator[str]:
        codex_bin = self._find_bin()
        if not codex_bin:
            raise RuntimeError(
                "codex CLI not found in PATH — install: npm install -g @openai/codex"
            )

        # Pass prompt via stdin ("-") to handle prompts that exceed shell arg limits
        proc = await asyncio.create_subprocess_exec(
            codex_bin, "exec", "-",
            cwd=worktree,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        if proc.stdin:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()

        got_first_line = False
        while True:
            try:
                timeout = _FIRST_OUTPUT_TIMEOUT if not got_first_line else None
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise BackendHangError(
                    f"codex produced no output in {_FIRST_OUTPUT_TIMEOUT}s — "
                    "likely needs `codex login` or OPENAI_API_KEY"
                )
            if not line:
                break
            got_first_line = True
            text = line.decode("utf-8", errors="replace").rstrip()
            yield text
            if _QUOTA_RE.search(text):
                proc.kill()
                await proc.wait()
                raise QuotaExceededError(f"codex quota exhausted: {text.strip()}")

        await proc.wait()
        if proc.returncode and proc.returncode != 0:
            yield f"[codex] exited with code {proc.returncode}"

    async def inject(self, message: str) -> None:
        # Codex exec is non-interactive; messages are queued but there is no running
        # process to receive them. They will be visible in the next run() call prompt.
        pass

    async def ask(self, question: str) -> str:
        codex_bin = self._find_bin()
        if not codex_bin:
            return "[codex not available]"
        proc = await asyncio.create_subprocess_exec(
            codex_bin, "review", question,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        out, _ = await proc.communicate()
        text = out.decode("utf-8", errors="replace").strip()
        if _QUOTA_RE.search(text):
            raise QuotaExceededError(f"codex quota exhausted: {text[:120]}")
        return text
