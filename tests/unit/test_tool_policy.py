"""WO-1093: centralized tool policy argv builders."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))

import tool_policy as tp  # noqa: E402


def test_default_policy_uses_bypass_and_coding_allowlist():
    p = tp.load_tool_policy(env={})
    assert p.claude_permission_mode == "bypassPermissions"
    assert "Bash" in p.claude_allowed_tools
    assert "Edit" in p.claude_allowed_tools
    assert p.gemini_yolo is True
    assert p.cursor_trust is True


def test_allowlist_off_clears_claude_tools():
    p = tp.load_tool_policy(env={"AGENT_TOOL_ALLOWLIST": "off"})
    assert p.claude_allowed_tools == ()


def test_custom_allowlist_and_mode():
    p = tp.load_tool_policy(
        env={
            "AGENT_PERMISSION_MODE": "acceptEdits",
            "AGENT_TOOL_ALLOWLIST": "Read,Edit,Bash",
            "GEMINI_YOLO": "0",
            "CURSOR_TRUST": "false",
        }
    )
    assert p.claude_permission_mode == "acceptEdits"
    assert p.claude_allowed_tools == ("Read", "Edit", "Bash")
    assert p.gemini_yolo is False
    assert p.cursor_trust is False


def test_invalid_mode_falls_back_to_bypass():
    p = tp.load_tool_policy(env={"AGENT_PERMISSION_MODE": "yolo"})
    assert p.claude_permission_mode == "bypassPermissions"


def test_claude_run_argv_includes_allowed_tools():
    p = tp.load_tool_policy(env={"AGENT_TOOL_ALLOWLIST": "Read,Bash"})
    argv = tp.claude_run_argv("/usr/bin/claude", "do work", "claude-sonnet-5", p)
    assert argv[:5] == [
        "/usr/bin/claude",
        "--print",
        "--permission-mode",
        "bypassPermissions",
        "--model",
    ]
    assert argv.count("--allowedTools") == 2
    assert "Read" in argv and "Bash" in argv
    assert argv[-2:] == ["-p", "do work"]


def test_gemini_and_cursor_argv_respect_flags():
    strict = tp.load_tool_policy(env={"GEMINI_YOLO": "0", "CURSOR_TRUST": "0"})
    assert tp.gemini_run_argv("gemini", "x", strict) == ["gemini", "-p", "x"]
    assert tp.cursor_run_argv("agent", "x", strict) == ["agent", "--print", "x"]

    loose = tp.load_tool_policy(env={})
    assert "--yolo" in tp.gemini_run_argv("gemini", "x", loose)
    assert "--trust" in tp.cursor_run_argv("agent", "x", loose)


def test_prompt_policy_section_mentions_mode():
    text = tp.prompt_policy_section(tp.load_tool_policy(env={}))
    assert "Tool policy" in text
    assert "bypassPermissions" in text
