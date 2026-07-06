import asyncio
import re
import shutil
from typing import AsyncIterator

from backends.base import AgentBackend, BackendHangError, QuotaExceededError

_FIRST_OUTPUT_TIMEOUT = 45
_CONNECTING_RE = re.compile(r"^\s*(connecting|authenticating|initializing|loading)[\.\s]*$", re.I)

# Google surfaces quota errors as RESOURCE_EXHAUSTED or plain 429 text
_QUOTA_RE = re.compile(
    r"RESOURCE_EXHAUSTED|quota exceeded|rate limit|429|"
    r"quota.*limit|limit.*quota|free tier.*limit|"
    r"gemini.*limit|upgrade.*plan",
    re.I,
)


class GeminiBackend(AgentBackend):
    """
    Agentic execution: Gemini CLI (`gemini --yolo -p <prompt>`).
    Text Q&A / review (ask): `gemini -p <question>` — headless, no file edits.

    Install: npm install -g @google/gemini-cli
    Auth:    gemini   (first run prompts Google OAuth — uses your Google/Gemini subscription)

    --yolo auto-approves all tool uses (file edits, shell commands). Without it,
    Gemini prompts for confirmation on every action, blocking the unattended runner.
    """

    def __init__(self) -> None:
        self._pending_messages: list[str] = []

    def _find_bin(self) -> str | None:
        return shutil.which("gemini")

    async def run(self, prompt: str, worktree: str) -> AsyncIterator[str]:
        gemini_bin = self._find_bin()
        if not gemini_bin:
            raise RuntimeError(
                "gemini CLI not found in PATH — install: npm install -g @google/gemini-cli"
            )

        full_prompt = prompt
        if self._pending_messages:
            full_prompt += "\n\n[Additional context]\n" + "\n".join(self._pending_messages)
            self._pending_messages.clear()

        proc = await asyncio.create_subprocess_exec(
            gemini_bin, "--yolo", "-p", full_prompt,
            cwd=worktree,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        got_first_line = False
        connecting_count = 0
        while True:
            try:
                timeout = _FIRST_OUTPUT_TIMEOUT if not got_first_line else None
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise BackendHangError(
                    f"gemini produced no output in {_FIRST_OUTPUT_TIMEOUT}s — "
                    "likely needs Google OAuth (`gemini` first-run login)"
                )
            if not line:
                break
            got_first_line = True
            text = line.decode("utf-8", errors="replace").rstrip()
            if _CONNECTING_RE.match(text):
                connecting_count += 1
                yield text
                if connecting_count >= 8:
                    proc.kill()
                    await proc.wait()
                    raise BackendHangError(
                        "gemini stuck in connecting loop — needs re-authentication"
                    )
            else:
                connecting_count = 0
                yield text
                if _QUOTA_RE.search(text):
                    proc.kill()
                    await proc.wait()
                    raise QuotaExceededError(f"gemini quota exhausted: {text.strip()}")

        await proc.wait()
        if proc.returncode and proc.returncode != 0:
            yield f"[gemini] exited with code {proc.returncode}"

    async def inject(self, message: str) -> None:
        self._pending_messages.append(message)

    async def ask(self, question: str) -> str:
        gemini_bin = self._find_bin()
        if not gemini_bin:
            return "[gemini not available]"
        proc = await asyncio.create_subprocess_exec(
            gemini_bin, "-p", question,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        out, _ = await proc.communicate()
        text = out.decode("utf-8", errors="replace").strip()
        if _QUOTA_RE.search(text):
            raise QuotaExceededError(f"gemini quota exhausted: {text[:120]}")
        return text
