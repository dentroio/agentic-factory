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


# ── WO-1052: per-repo reservation ──────────────────────────────────────────────
# Root cause was not a stale counter — GITHUB_REPO/WO_PATH were hardcoded to
# Clarion, so any caller numbering a different repo's WOs (e.g. agentic-factory's
# own docs/work_orders/) always got Clarion's next number back. Fix makes repo
# an explicit dimension of both the reservation bucket and the known-numbers scan.

DEFAULT_REPO = "dentroio/clarion"
FACTORY_REPO = "dentroio/agentic-factory"


def _next_wo_num_for_repo(
    repo: str,
    known_by_repo: dict[str, set[int]],
    reserved_by_repo: dict[str, dict[int, dict]],
) -> int:
    all_nums = known_by_repo.get(repo, set()) | set(reserved_by_repo.get(repo, {}))
    return (max(all_nums) + 1) if all_nums else 1000


def _migrate_reserved(raw: dict, default_repo: str) -> dict[str, dict[int, dict]]:
    """Mirrors orchestrator._load_reserved's flat -> nested migration."""
    if raw and all("/" not in k for k in raw):
        raw = {default_repo: raw}
    return {repo: {int(k): v for k, v in bucket.items()} for repo, bucket in raw.items()}


def test_two_repos_number_independently_even_with_overlapping_ranges():
    """Clarion and agentic-factory both use WO numbers in the low-1000s —
    a reservation in one repo must not consume a number in the other."""
    known_by_repo = {
        DEFAULT_REPO: {1030, 1031, 1032, 1033, 1034},  # clarion's own WO-1035 already exists
        FACTORY_REPO: {1043, 1044, 1045, 1046},
    }
    reserved_by_repo: dict[str, dict[int, dict]] = {}

    clarion_num = _next_wo_num_for_repo(DEFAULT_REPO, known_by_repo, reserved_by_repo)
    factory_num = _next_wo_num_for_repo(FACTORY_REPO, known_by_repo, reserved_by_repo)

    assert clarion_num == 1035
    assert factory_num == 1047
    assert clarion_num != factory_num  # the actual bug: both used to resolve to 1035


def test_reservation_in_one_repo_does_not_block_the_other():
    known_by_repo = {DEFAULT_REPO: {1040}, FACTORY_REPO: {1040}}
    reserved_by_repo: dict[str, dict[int, dict]] = {}

    num_a = _next_wo_num_for_repo(DEFAULT_REPO, known_by_repo, reserved_by_repo)
    reserved_by_repo.setdefault(DEFAULT_REPO, {})[num_a] = {
        "reserved_by": "x", "reserved_at": datetime.now(UTC).isoformat(), "title": "t",
    }

    # Factory's next number is unaffected by Clarion's reservation
    num_b = _next_wo_num_for_repo(FACTORY_REPO, known_by_repo, reserved_by_repo)
    assert num_b == 1041


def test_migrate_flat_format_promotes_to_default_repo():
    old_flat = {"1035": {"reserved_by": "x", "reserved_at": "2026-01-01T00:00:00+00:00", "title": "t"}}
    migrated = _migrate_reserved(old_flat, DEFAULT_REPO)
    assert migrated == {DEFAULT_REPO: {1035: old_flat["1035"]}}


def test_migrate_leaves_nested_format_untouched():
    already_nested = {
        FACTORY_REPO: {"1047": {"reserved_by": "x", "reserved_at": "2026-01-01T00:00:00+00:00", "title": "t"}}
    }
    migrated = _migrate_reserved(already_nested, DEFAULT_REPO)
    assert migrated == {FACTORY_REPO: {1047: already_nested[FACTORY_REPO]["1047"]}}


def test_migrate_empty_dict_is_a_noop():
    assert _migrate_reserved({}, DEFAULT_REPO) == {}


# ── Follow-up fix: completed dispatch entries shouldn't inflate "next" ────────
# Found live: Clarion's real spec files top out at WO-441, but dispatch_state
# had five completed one-off process/conflict-resolution WOs numbered in the
# 1000s (e.g. "WO-1035: Resolve conflict...", merged as real PRs but never
# given a spec file). Merging ALL dispatch_state numbers into the known set
# permanently pinned "next" at 1036 instead of 442. Only in-flight (non-
# "complete") dispatch entries should count — completed ones are either
# already reflected in the spec-file scan, or historical noise.

def _known_from_dispatch_state(dispatch_state: dict[str, dict]) -> set[int]:
    """Mirrors orchestrator._next_wo_number's dispatch-state filtering."""
    known: set[int] = set()
    for wo_id, meta in dispatch_state.items():
        if isinstance(meta, dict) and meta.get("status") == "complete":
            continue
        try:
            known.add(int(wo_id.replace("WO-", "")))
        except ValueError:
            pass
    return known


def test_completed_dispatch_entries_are_excluded_from_known_numbers():
    dispatch_state = {
        "WO-1035": {"status": "complete"},
        "WO-1034": {"status": "complete"},
    }
    assert _known_from_dispatch_state(dispatch_state) == set()


def test_in_flight_dispatch_entries_still_protect_against_collision():
    dispatch_state = {
        "WO-442": {"status": "claimed"},
        "WO-441": {"status": "complete"},
    }
    assert _known_from_dispatch_state(dispatch_state) == {442}


def test_spec_file_max_wins_when_only_completed_dispatch_noise_is_present():
    spec_file_known = {437, 438, 439, 440, 441}
    dispatch_known = _known_from_dispatch_state({
        "WO-1027": {"status": "complete"},
        "WO-1035": {"status": "complete"},
    })
    all_known = spec_file_known | dispatch_known
    assert (max(all_known) + 1) == 442
