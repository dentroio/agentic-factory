import asyncio
import shutil
from typing import AsyncIterator

from backends.base import AgentBackend


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
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield line.decode("utf-8", errors="replace").rstrip()

        await proc.wait()
        if proc.returncode and proc.returncode != 0:
            yield f"[gemini] exited with code {proc.returncode}"

    async def inject(self, message: str) -> None:
        self._pending_messages.append(message)

    async def ask(self, question: str) -> str:
        """Headless text Q&A via `gemini -p` — no file mutations."""
        gemini_bin = self._find_bin()
        if gemini_bin:
            try:
                proc = await asyncio.create_subprocess_exec(
                    gemini_bin, "-p", question,
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

        return "[gemini reviewer: gemini not found and claude not available as fallback]"
