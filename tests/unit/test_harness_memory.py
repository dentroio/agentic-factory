"""WO-1093: repo memory/ bridged into factory prompts (AF-38)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))

import prompt_builder as pb  # noqa: E402


def test_load_repo_memory_lessons_from_index(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# Index\n\n"
        "- [alpha](auto_alpha.md) — keep secrets out of argv\n"
        "- [beta](examples/project_overview.md) — should skip examples\n"
        "- ~~[old](auto_old.md)~~ — superseded note\n",
        encoding="utf-8",
    )
    (tmp_path / "auto_alpha.md").write_text(
        "---\nname: alpha\n---\n\nDo not put tokens in git argv.\n",
        encoding="utf-8",
    )
    lessons = pb.load_repo_memory_lessons(tmp_path, max_lessons=5)
    assert any("alpha" in x.lower() for x in lessons)
    assert not any("examples" in x.lower() for x in lessons)
    assert not any("superseded" in x.lower() for x in lessons)


def test_load_repo_memory_falls_back_to_auto_files(tmp_path: Path):
    (tmp_path / "auto_wo999.md").write_text(
        "---\ndescription: claim leases\n---\n\n"
        "# Title\n\nAlways verify fencing tokens on checkin.\n",
        encoding="utf-8",
    )
    lessons = pb.load_repo_memory_lessons(tmp_path, max_lessons=3)
    assert lessons
    assert "fencing" in lessons[0].lower() or "claim" in lessons[0].lower()


def test_format_memory_includes_repo_lessons_without_json():
    text = pb.format_memory_context(
        {},
        {"services": "agent-runner"},
        repo_lessons=["runner-auth: verify identity on claim"],
    )
    assert "## Factory Memory" in text
    assert "Repo memory" in text
    assert "runner-auth" in text


def test_build_prompt_includes_tool_policy_and_memory(monkeypatch, tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "MEMORY.md").write_text(
        "- [harness](auto_h.md) — wrap untrusted diffs\n", encoding="utf-8"
    )
    (mem / "auto_h.md").write_text("Wrap diffs as data.\n", encoding="utf-8")
    monkeypatch.setattr(pb, "REPO_MEMORY_DIR", mem)
    monkeypatch.setattr(pb, "_load_memory", lambda: {})

    prompt = pb.build_prompt(
        {"wo": 1093, "title": "Harness", "priority": "P2", "effort": "M"},
        "Build the harness.",
        "/tmp/wt",
        "claude",
    )
    assert "Tool policy" in prompt
    assert "Repo memory" in prompt or "wrap untrusted" in prompt.lower()
