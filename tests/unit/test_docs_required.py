"""WO-1097: docs_required parsing + documentation mandate in coding prompts."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
STATUS_SITE_DIR = REPO_ROOT / "services" / "status-site"

if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))
if str(STATUS_SITE_DIR) not in sys.path:
    sys.path.insert(0, str(STATUS_SITE_DIR))

import prompt_builder as pb  # noqa: E402
from wo_parser import parse_docs_required as status_parse  # noqa: E402


SAMPLE_WITH_DOCS = """# WO-999 — Example

## Documentation Required

- [ ] Update wiki/docs/operator/dashboard.md
- [x] Map route in frontend/src/lib/inAppHelpMap.ts
- [ ] None

## Notes

ok
"""

SAMPLE_NONE = """# WO-999 — Example

## Documentation Required

- None

## Notes

ok
"""

SAMPLE_NA = """# WO-1

## Documentation Required
- N/A
- not applicable

## Acceptance Criteria
- ship it
"""


def test_parse_skips_none_sentinels_status_and_runner():
    assert status_parse(SAMPLE_NONE) == []
    assert pb.parse_docs_required(SAMPLE_NONE) == []
    assert status_parse(SAMPLE_NA) == []
    assert pb.parse_docs_required(SAMPLE_NA) == []


def test_parse_real_items_and_checkbox_completed():
    items = status_parse(SAMPLE_WITH_DOCS)
    # "None" sentinel skipped; one open + one completed remain
    assert len(items) == 2
    assert items[0]["item"].startswith("Update wiki/docs/")
    assert items[0]["completed"] is False
    assert "inAppHelpMap" in items[1]["item"]
    assert items[1]["completed"] is True
    assert pb.parse_docs_required(SAMPLE_WITH_DOCS) == items


def test_parse_empty_without_section():
    assert status_parse("# WO\n\n## Acceptance\n- ok\n") == []
    assert pb.parse_docs_required("") == []


def test_format_documentation_mandate_only_pending():
    mandate = pb.format_documentation_mandate(pb.parse_docs_required(SAMPLE_WITH_DOCS))
    assert "DOCUMENTATION MANDATE" in mandate
    assert "wiki/docs/operator/dashboard.md" in mandate
    assert "inAppHelpMap" not in mandate  # already completed
    assert pb.format_documentation_mandate([]) == ""
    assert pb.format_documentation_mandate(pb.parse_docs_required(SAMPLE_NONE)) == ""


def test_build_prompt_includes_mandate_when_docs_required(tmp_path):
    (tmp_path / "factory.yaml").write_text("display_name: TestProd\n", encoding="utf-8")
    with patch.object(pb, "load_profile") as lp, patch.object(
        pb, "load_patterns_text", return_value=""
    ), patch.object(pb, "_load_memory", return_value={}), patch(
        "tool_policy.prompt_policy_section", return_value="## Tool policy\n"
    ):
        lp.return_value = MagicMock(display_name="TestProd", ui_url="http://localhost:3000")
        prompt = pb.build_prompt(
            {"wo": "999", "title": "Example", "priority": "P2", "effort": "S"},
            SAMPLE_WITH_DOCS,
            str(tmp_path),
            "test-agent",
        )
    assert "DOCUMENTATION MANDATE" in prompt
    assert "wiki/docs/operator/dashboard.md" in prompt


def test_build_prompt_omits_mandate_for_none(tmp_path):
    (tmp_path / "factory.yaml").write_text("display_name: TestProd\n", encoding="utf-8")
    with patch.object(pb, "load_profile") as lp, patch.object(
        pb, "load_patterns_text", return_value=""
    ), patch.object(pb, "_load_memory", return_value={}), patch(
        "tool_policy.prompt_policy_section", return_value="## Tool policy\n"
    ):
        lp.return_value = MagicMock(display_name="TestProd", ui_url="http://localhost:3000")
        prompt = pb.build_prompt(
            {"wo": "999", "title": "Example", "priority": "P2", "effort": "S"},
            SAMPLE_NONE,
            str(tmp_path),
            "test-agent",
        )
    assert "DOCUMENTATION MANDATE" not in prompt
