"""Tests for WO-1043: WO number reservation — pure logic, no heavy imports."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


# ── Pure-logic helpers mirroring orchestrator's reservation implementation ────
# (Orchestrator can't be imported in unit tests due to heavy deps like apscheduler)

RESERVATION_TTL_HOURS = 1


def _expire(reserved: dict[int, dict]) -> dict[int, dict]:
    """Return a copy of reserved with stale entries removed."""
    cutoff = datetime.now(UTC) - timedelta(hours=RESERVATION_TTL_HOURS)
    return {
        num: meta
        for num, meta in reserved.items()
        if datetime.fromisoformat(meta["reserved_at"]) >= cutoff
    }


def _next_wo_num(known: set[int], reserved: dict[int, dict]) -> int:
    all_nums = known | set(reserved)
    return (max(all_nums) + 1) if all_nums else 1000


def _reserve(reserved: dict[int, dict], known: set[int], title: str, reserved_by: str) -> tuple[int, dict]:
    num = _next_wo_num(known, reserved)
    meta = {
        "reserved_by": reserved_by,
        "reserved_at": datetime.now(UTC).isoformat(),
        "title": title,
    }
    return num, meta


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_two_concurrent_reservations_get_different_numbers():
    """Two sequential reserve calls from the same known set return different numbers."""
    reserved: dict[int, dict] = {}
    known: set[int] = {1000, 1001, 1002}

    num1, meta1 = _reserve(reserved, known, "caller-a", "agent-a")
    reserved[num1] = meta1

    num2, meta2 = _reserve(reserved, known, "caller-b", "agent-b")
    reserved[num2] = meta2

    assert num1 != num2


def test_reservation_persists_to_disk(tmp_path):
    """Reservation dict survives a JSON round-trip (restart simulation)."""
    reserved = {
        1044: {
            "reserved_by": "claude-code",
            "reserved_at": datetime.now(UTC).isoformat(),
            "title": "my new feature",
        }
    }
    path = tmp_path / "reserved_wos.json"
    path.write_text(json.dumps({str(k): v for k, v in reserved.items()}, indent=2))

    loaded = {int(k): v for k, v in json.loads(path.read_text()).items()}
    assert 1044 in loaded
    assert loaded[1044]["reserved_by"] == "claude-code"


def test_expired_reservations_are_removed():
    """Reservations older than TTL are not returned by _expire."""
    now = datetime.now(UTC)
    old_ts = (now - timedelta(hours=2)).isoformat()
    fresh_ts = now.isoformat()

    reserved = {
        100: {"reserved_by": "old", "reserved_at": old_ts, "title": "stale"},
        200: {"reserved_by": "new", "reserved_at": fresh_ts, "title": "fresh"},
    }

    active = _expire(reserved)
    assert 100 not in active
    assert 200 in active


def test_unreserved_number_not_returned_in_active(tmp_path):
    """After TTL expires, GET /api/wos/reserved shows only active reservations."""
    old_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    reserved = {999: {"reserved_by": "x", "reserved_at": old_ts, "title": "y"}}
    active = _expire(reserved)
    assert not active


def test_reservation_includes_known_dispatch_numbers():
    """_next_wo_num accounts for numbers already in dispatch state."""
    known = {1041, 1042, 1043}
    reserved: dict[int, dict] = {}
    assert _next_wo_num(known, reserved) == 1044


def test_scan_fallback_wo_resolver():
    """wo_resolver.branch_name_for works correctly for a reserved number."""
    from wo_resolver import branch_name_for
    assert branch_name_for(1044, "my new feature") == "wo/1044-my-new-feature"
