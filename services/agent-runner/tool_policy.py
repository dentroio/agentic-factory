"""Central LLM tool / permission policy for coding backends.

Headless factory runs still need auto-approve (CLIs block without it), but
policy is no longer scattered magic strings. Claude gets an explicit coding
tool allowlist by default so the model cannot invent MCP / browser tools
outside the documented set. Every knob is env-overridable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


# Safe default for unattended coding WOs. Bash remains powerful — worktree
# isolation + quality gates are the remaining defense.
_DEFAULT_CLAUDE_TOOLS = (
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "Glob",
    "Grep",
    "Bash",
    "WebFetch",
    "WebSearch",
    "TodoWrite",
    "NotebookEdit",
)

_VALID_CLAUDE_MODES = frozenset(
    {"default", "acceptEdits", "bypassPermissions", "plan"}
)


@dataclass(frozen=True)
class ToolPolicy:
    """Resolved policy for one agent run."""

    claude_permission_mode: str = "bypassPermissions"
    claude_allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    gemini_yolo: bool = True
    cursor_trust: bool = True

    def summary(self) -> str:
        tools = ",".join(self.claude_allowed_tools) if self.claude_allowed_tools else "(unrestricted)"
        return (
            f"claude_mode={self.claude_permission_mode} "
            f"claude_tools={tools} "
            f"gemini_yolo={self.gemini_yolo} "
            f"cursor_trust={self.cursor_trust}"
        )


def load_tool_policy(
    *,
    env: dict[str, str] | None = None,
) -> ToolPolicy:
    """Load policy from environment (or an injected mapping for tests)."""
    e = env if env is not None else os.environ

    mode = (e.get("AGENT_PERMISSION_MODE") or "bypassPermissions").strip()
    if mode not in _VALID_CLAUDE_MODES:
        mode = "bypassPermissions"

    allowlist_raw = (e.get("AGENT_TOOL_ALLOWLIST") or "on").strip()
    allowlist_key = allowlist_raw.lower()
    if allowlist_key in ("off", "0", "false", "no", "unrestricted"):
        tools: tuple[str, ...] = ()
    elif allowlist_key in ("on", "1", "true", "yes", "default"):
        tools = _DEFAULT_CLAUDE_TOOLS
    else:
        tools = tuple(t.strip() for t in allowlist_raw.split(",") if t.strip())

    yolo_raw = (e.get("GEMINI_YOLO") or "1").strip().lower()
    gemini_yolo = yolo_raw not in ("0", "false", "no", "off")

    trust_raw = (e.get("CURSOR_TRUST") or "1").strip().lower()
    cursor_trust = trust_raw not in ("0", "false", "no", "off")

    return ToolPolicy(
        claude_permission_mode=mode,
        claude_allowed_tools=tools,
        gemini_yolo=gemini_yolo,
        cursor_trust=cursor_trust,
    )


def claude_run_argv(
    claude_bin: str,
    prompt: str,
    model: str,
    policy: ToolPolicy | None = None,
) -> list[str]:
    """Build argv for `claude --print` agentic runs."""
    p = policy or load_tool_policy()
    argv = [
        claude_bin,
        "--print",
        "--permission-mode",
        p.claude_permission_mode,
        "--model",
        model,
    ]
    for tool in p.claude_allowed_tools:
        argv.extend(["--allowedTools", tool])
    argv.extend(["-p", prompt])
    return argv


def gemini_run_argv(
    gemini_bin: str,
    prompt: str,
    policy: ToolPolicy | None = None,
) -> list[str]:
    """Build argv for `gemini` agentic runs."""
    p = policy or load_tool_policy()
    argv = [gemini_bin]
    if p.gemini_yolo:
        argv.append("--yolo")
    argv.extend(["-p", prompt])
    return argv


def cursor_run_argv(
    agent_bin: str,
    prompt: str,
    policy: ToolPolicy | None = None,
) -> list[str]:
    """Build argv for Cursor `agent --print` runs."""
    p = policy or load_tool_policy()
    argv = [agent_bin, "--print"]
    if p.cursor_trust:
        argv.append("--trust")
    argv.append(prompt)
    return argv


def prompt_policy_section(policy: ToolPolicy | None = None) -> str:
    """Short mandate block injected into coding prompts."""
    p = policy or load_tool_policy()
    tools = (
        ", ".join(p.claude_allowed_tools)
        if p.claude_allowed_tools
        else "unrestricted (AGENT_TOOL_ALLOWLIST=off)"
    )
    return f"""## Tool policy (platform)

- Stay inside the assigned worktree. Do not modify files outside it.
- Do not rotate secrets, force-push to main, or change branch protection.
- Claude permission mode: `{p.claude_permission_mode}`; allowed tools: {tools}.
- Prefer Read/Edit/Write/Bash for implementation; avoid unrelated network tools.
""".strip()
