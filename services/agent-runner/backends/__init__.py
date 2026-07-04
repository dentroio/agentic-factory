from backends.base import AgentBackend
from backends.claude import ClaudeBackend
from backends.cursor import CursorBackend
from backends.codex import CodexBackend
from config import PREFERRED_AGENT, CURSOR_API_KEY, OPENAI_API_KEY


def get_backend(preferred: str | None = None) -> AgentBackend:
    name = (preferred or PREFERRED_AGENT).lower()
    if name == "cursor":
        return CursorBackend(api_key=CURSOR_API_KEY)
    if name == "codex":
        return CodexBackend(api_key=OPENAI_API_KEY)
    return ClaudeBackend()
