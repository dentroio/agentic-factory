from abc import ABC, abstractmethod
from typing import AsyncIterator


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
