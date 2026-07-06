from abc import ABC, abstractmethod
from typing import AsyncIterator


class BackendHangError(RuntimeError):
    """Raised when a backend produces no output within the startup timeout."""


class QuotaExceededError(RuntimeError):
    """Raised when a backend reports it has hit its usage/rate limit.

    The runner catches this and marks the backend as exhausted for the rest of
    the daemon session, skipping it in all future fallback attempts.
    """


class AgentBackend(ABC):
    @abstractmethod
    async def run(self, prompt: str, worktree: str) -> AsyncIterator[str]:
        """Run the agent with the given prompt in the given worktree.
        Yields progress chunks as strings."""
        ...

    async def inject(self, message: str) -> None:
        """Inject a mid-task message into the running agent (optional)."""

    async def ask(self, question: str) -> str:
        """Ask a one-shot question and return the answer (for Q&A mode)."""
        return ""
