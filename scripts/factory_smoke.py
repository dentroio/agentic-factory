#!/usr/bin/env python3
"""Post-deploy smoke checks for the factory engine stack.

Status-site /health must return 200.
Orchestrator /health is behind bearer auth — a TCP/HTTP response of 200 or 401
means the process is up (401 = alive but unauthorized, which is expected).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULTS = {
    "status": os.getenv("FACTORY_STATUS_URL", "http://127.0.0.1:8099/health"),
    "orchestrator": os.getenv("ORCHESTRATOR_HEALTH_URL", "http://127.0.0.1:8100/health"),
}


def _get(url: str, timeout: float, token: str = "") -> tuple[int, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body
    except Exception as exc:  # noqa: BLE001 — surface any connect failure
        raise RuntimeError(f"unreachable: {exc}") from exc


def check_status(url: str, timeout: float) -> None:
    code, body = _get(url, timeout)
    if code != 200:
        raise RuntimeError(f"status-site health → HTTP {code}: {body[:200]}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"status-site health returned non-JSON: {body[:200]}") from exc
    if data.get("status") not in ("ok", "healthy", True) and not data.get("ok"):
        # Accept {"status":"ok"} (current) or {"ok":true}
        if data.get("status") != "ok":
            raise RuntimeError(f"status-site health unexpected payload: {data}")


def check_orchestrator(url: str, timeout: float, token: str) -> None:
    code, body = _get(url, timeout, token=token)
    if token:
        if code != 200:
            raise RuntimeError(f"orchestrator health → HTTP {code}: {body[:200]}")
        return
    # Without a token, middleware returns 401 — that still proves the server is up.
    if code not in (200, 401):
        raise RuntimeError(f"orchestrator health → HTTP {code}: {body[:200]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-url", default=DEFAULTS["status"])
    parser.add_argument("--orchestrator-url", default=DEFAULTS["orchestrator"])
    parser.add_argument(
        "--token",
        default=os.getenv("API_SECRET", "") or os.getenv("ORCHESTRATOR_TOKEN", ""),
        help="Optional bearer for orchestrator /health (API_SECRET)",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    failures: list[str] = []
    try:
        check_status(args.status_url, args.timeout)
        print(f"✅ status-site {args.status_url}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"status-site: {exc}")
        print(f"❌ status-site: {exc}", file=sys.stderr)

    try:
        check_orchestrator(args.orchestrator_url, args.timeout, args.token)
        print(f"✅ orchestrator {args.orchestrator_url}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"orchestrator: {exc}")
        print(f"❌ orchestrator: {exc}", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} smoke check(s) failed", file=sys.stderr)
        return 1
    print("\nAll factory smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
