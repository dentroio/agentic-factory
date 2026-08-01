"""Regression test for a live bug: orchestrator.py's auto_mark_done_wo() called
_cached_get(client, url, ttl=60) — omitting the required positional `params`
argument — so every post-merge "mark WO done" pass threw
`TypeError: _cached_get() missing 1 required positional argument: 'params'`
and silently failed to update the WO spec file's Status line, even though the
dispatch-state and claim-file updates in the same function succeeded (they
don't go through _cached_get). Found live: WO-423 merged (PR #485) but its
spec file still said "Status: Planned" — this is why.

orchestrator.py can't be imported directly in unit tests (heavy deps —
apscheduler, fastapi), so this scans its source text for every _cached_get(
call site and asserts each one supplies a params argument, rather than
mirroring the function itself (the earlier bug wasn't in _cached_get's logic,
it was a caller forgetting an argument — a static call-site check catches
this bug class directly, including future regressions elsewhere in the file).
"""

from __future__ import annotations

import re
from pathlib import Path

ORCHESTRATOR_PATH = (
    Path(__file__).resolve().parents[2] / "services" / "orchestrator" / "orchestrator.py"
)


def _cached_get_call_sites() -> list[str]:
    src = ORCHESTRATOR_PATH.read_text()
    # Match "_cached_get(" through its balanced closing paren, one call at a time.
    calls = []
    for m in re.finditer(r"_cached_get\(", src):
        start = m.end()
        depth = 1
        i = start
        while depth > 0 and i < len(src):
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
            i += 1
        calls.append(src[start : i - 1])
    return calls


def test_cached_get_source_is_readable():
    assert ORCHESTRATOR_PATH.exists()
    assert len(_cached_get_call_sites()) > 0


def test_every_cached_get_call_site_supplies_params():
    """The bug: `_cached_get(client, url, ttl=60)` — two positional args plus a
    kwarg, skipping the required third positional `params`. A correct call
    either has a 3rd positional argument before any `ttl=` kwarg, or an
    explicit `params=` kwarg."""
    offenders = []
    for call_args in _cached_get_call_sites():
        # Split top-level commas only (ignore commas inside nested () / {} / []).
        parts: list[str] = []
        depth = 0
        current = ""
        for ch in call_args:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(current)
                current = ""
            else:
                current += ch
        if current.strip():
            parts.append(current)
        parts = [p.strip() for p in parts if p.strip()]

        has_params_kwarg = any(p.startswith("params=") for p in parts)
        # First two positional args are always (client, url); a 3rd positional
        # arg that isn't itself a kwarg (`name=value`) satisfies `params`.
        positional = [p for p in parts if "=" not in p or p.strip().startswith(("{", "["))]
        has_third_positional = len(positional) >= 3

        if not (has_params_kwarg or has_third_positional):
            offenders.append(call_args.strip()[:80])

    assert offenders == [], f"_cached_get() call site(s) missing params: {offenders}"
