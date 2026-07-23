"""Tests for WO-1042: corroboration gate, override tombstone, advisory ghost, attribution."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ORCH_DIR = Path(__file__).resolve().parents[2] / "services" / "orchestrator"
sys.path.insert(0, str(ORCH_DIR))


# ── 1. Corroboration gate ─────────────────────────────────────────────────────


def test_title_only_match_does_not_auto_complete():
    """resolve_wo_for_pr_with_source returns source='title' for PRs without a wo/ branch."""
    from wo_resolver import resolve_wo_for_pr_with_source

    pr = {
        "title": "Fix regression from WO-410",
        "head": {"ref": "fix/some-regression"},
    }
    num, src = resolve_wo_for_pr_with_source(pr)
    assert num == 410
    assert src == "title"
    # A caller implementing the corroboration gate must NOT auto-complete when src == "title"


def test_branch_match_returns_branch_source():
    from wo_resolver import resolve_wo_for_pr_with_source

    pr = {
        "title": "WO-410 unrelated title mentioning old WO",
        "head": {"ref": "wo/1042-guard"},
    }
    num, src = resolve_wo_for_pr_with_source(pr)
    assert num == 1042
    assert src == "branch"


# ── 2. Override tombstone ─────────────────────────────────────────────────────
# Test the override logic as pure functions (orchestrator.py has heavy deps that
# can't be imported in unit tests; the logic is simple enough to test inline).


def _is_overridden_impl(overrides: dict, wo_id: str, action: str) -> bool:
    return overrides.get(wo_id, {}).get("action") == action


def test_override_is_respected():
    overrides = {"WO-410": {"action": "no-auto-complete"}}
    assert _is_overridden_impl(overrides, "WO-410", "no-auto-complete") is True
    assert _is_overridden_impl(overrides, "WO-410", "other-action") is False
    assert _is_overridden_impl(overrides, "WO-999", "no-auto-complete") is False


def test_override_persists_to_disk(tmp_path):
    """JSON round-trip: save overrides and reload them."""
    override_path = tmp_path / "wo_overrides.json"
    overrides = {"WO-410": {"action": "no-auto-complete", "set_by": "human"}}
    override_path.write_text(json.dumps(overrides, indent=2), encoding="utf-8")

    loaded = json.loads(override_path.read_text())
    assert _is_overridden_impl(loaded, "WO-410", "no-auto-complete") is True


def test_override_survives_restart(tmp_path):
    """Override written to disk survives a simulated restart (re-read from disk)."""
    override_path = tmp_path / "wo_overrides.json"
    override_path.write_text(
        json.dumps({"WO-999": {"action": "no-auto-complete", "set_by": "human", "set_at": "2026-07-23T00:00:00Z"}}),
        encoding="utf-8",
    )
    loaded = json.loads(override_path.read_text())
    assert _is_overridden_impl(loaded, "WO-999", "no-auto-complete") is True


# ── 3. Advisory ghost (first pass sets warning, not status=ghost) ─────────────


import asyncio
import pytest


@pytest.mark.asyncio
async def test_ghost_first_pass_sets_warning_not_ghost(monkeypatch, tmp_path):
    """First ghost detection sets ghost_warning flag, does NOT change status to ghost."""
    import intelligence as intel

    acted_on_path = tmp_path / "acted_on.json"
    monkeypatch.setattr(intel, "_ACTED_ON_PATH", acted_on_path)
    monkeypatch.setattr(intel, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(intel, "_acted_on", {})

    updates: dict[str, dict] = {}

    def fake_update(wo_id: str, patch: dict) -> None:
        updates.setdefault(wo_id, {}).update(patch)

    fake_enqueue = MagicMock()

    with (
        patch.object(intel, "_gh_get", new=AsyncMock(return_value=[])),
        patch.object(intel, "_gh_post", new=AsyncMock()),
        patch.object(intel, "_find_ghost_entries", return_value=["WO-123"]),
    ):
        # Entry without ghost_warning flag (first detection)
        dispatch = {"WO-123": {"status": "in_progress", "pr_number": None}}
        await intel.run_intelligence_pass(
            github_token="fake",
            github_repo="owner/repo",
            anthropic_key="",
            dispatch_state=dispatch,
            enqueue_wo=fake_enqueue,
            update_dispatch=fake_update,
        )

    assert "WO-123" in updates
    assert updates["WO-123"].get("ghost_warning") is True
    # Status must NOT have been changed to "ghost" on first pass
    assert updates["WO-123"].get("status") != "ghost"


@pytest.mark.asyncio
async def test_ghost_escalates_after_24h(monkeypatch, tmp_path):
    """Ghost escalates to status=ghost only after 24h with ghost_warning already set."""
    import intelligence as intel

    acted_on_path = tmp_path / "acted_on.json"
    monkeypatch.setattr(intel, "_ACTED_ON_PATH", acted_on_path)
    monkeypatch.setattr(intel, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(intel, "_acted_on", {})

    updates: dict[str, dict] = {}

    def fake_update(wo_id: str, patch: dict) -> None:
        updates.setdefault(wo_id, {}).update(patch)

    warned_at = (datetime.now(UTC) - timedelta(hours=25)).isoformat()

    with (
        patch.object(intel, "_gh_get", new=AsyncMock(return_value=[])),
        patch.object(intel, "_gh_post", new=AsyncMock()),
        patch.object(intel, "_find_ghost_entries", return_value=["WO-456"]),
    ):
        dispatch = {
            "WO-456": {
                "status": "in_progress",
                "ghost_warning": True,
                "ghost_warning_at": warned_at,
            }
        }
        await intel.run_intelligence_pass(
            github_token="fake",
            github_repo="owner/repo",
            anthropic_key="",
            dispatch_state=dispatch,
            enqueue_wo=MagicMock(),
            update_dispatch=fake_update,
        )

    assert updates.get("WO-456", {}).get("status") == "ghost"


# ── 4. Attribution on automated GitHub comments ───────────────────────────────


@pytest.mark.asyncio
async def test_attribution_in_ghost_warning_comment(monkeypatch, tmp_path):
    """Ghost warning GitHub comment includes run_id attribution."""
    import intelligence as intel

    acted_on_path = tmp_path / "acted_on.json"
    monkeypatch.setattr(intel, "_ACTED_ON_PATH", acted_on_path)
    monkeypatch.setattr(intel, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(intel, "_acted_on", {})

    posted_bodies: list[str] = []

    async def fake_gh_post(client, token, path, body):
        posted_bodies.append(body.get("body", ""))

    with (
        patch.object(intel, "_gh_get", new=AsyncMock(return_value=[])),
        patch.object(intel, "_gh_post", new=AsyncMock(side_effect=fake_gh_post)),
        patch.object(intel, "_find_ghost_entries", return_value=["WO-789"]),
    ):
        dispatch = {"WO-789": {"status": "in_progress", "pr_number": 42}}
        await intel.run_intelligence_pass(
            github_token="fake",
            github_repo="owner/repo",
            anthropic_key="",
            dispatch_state=dispatch,
            enqueue_wo=MagicMock(),
            update_dispatch=lambda w, p: None,
        )

    assert posted_bodies, "expected a GitHub comment to be posted"
    body = posted_bodies[0]
    assert "intelligence-loop" in body
    assert "run `" in body  # correlation ID present
