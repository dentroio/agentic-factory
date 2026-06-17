#!/usr/bin/env python3
"""
Observability agent — polls a health/metrics endpoint and creates a GitHub
issue (WO draft) when anomalies are detected.

Runs on a schedule (e.g., every 15 minutes via observability.yml). If an
anomaly is found, the workflow creates a GitHub issue labeled 'new-wo',
which triggers the planning agent to draft a WO spec.

Usage:
    python3 scripts/observability_agent.py \
        --endpoint http://localhost:8000/api/health \
        --thresholds scripts/observability_thresholds.json \
        --output /tmp/anomaly.md

Exit codes:
    0 — healthy (no anomaly)
    1 — anomaly detected (workflow creates GH issue)

Setup:
    export ANTHROPIC_API_KEY=sk-ant-...
    Create scripts/observability_thresholds.json (see below for format)

Thresholds file format (scripts/observability_thresholds.json):
    {
      "error_rate_pct": 1.0,
      "p99_latency_ms": 2000,
      "unhealthy_services": []
    }
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

SYSTEM_PROMPT = """You are an observability agent. You receive a health/metrics snapshot
and a list of threshold violations. Write a concise incident report in WO Problem format.

The report will be posted as a GitHub issue body. It should:
1. Describe the anomaly clearly (what is broken or degraded)
2. Include the raw metric values that triggered the alert
3. Suggest likely causes (without guessing — stick to what the data shows)
4. Be actionable: what does an on-call engineer or agent need to check first?

Keep it under 300 words. No headers other than ## Problem and ## Suggested Investigation.
"""


def load_thresholds(path: str) -> dict:
    defaults = {
        "error_rate_pct": 1.0,
        "p99_latency_ms": 2000,
        "unhealthy_services": [],
    }
    if path and os.path.exists(path):
        with open(path) as f:
            loaded = json.load(f)
        defaults.update(loaded)
    return defaults


def fetch_metrics(endpoint: str, timeout: int = 10) -> dict:
    try:
        req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"_fetch_error": str(e), "status": "unreachable"}
    except json.JSONDecodeError:
        return {"_parse_error": "endpoint did not return JSON", "status": "unknown"}


def check_thresholds(metrics: dict, thresholds: dict) -> list[str]:
    violations = []

    if "_fetch_error" in metrics:
        violations.append(f"Endpoint unreachable: {metrics['_fetch_error']}")
        return violations

    if metrics.get("status") not in ("ok", "healthy", "up", None):
        violations.append(f"Health status: {metrics.get('status', 'unknown')}")

    error_rate = metrics.get("error_rate_pct") or metrics.get("error_rate")
    if error_rate is not None and float(error_rate) > thresholds["error_rate_pct"]:
        violations.append(
            f"Error rate {error_rate}% exceeds threshold {thresholds['error_rate_pct']}%"
        )

    p99 = metrics.get("p99_latency_ms") or metrics.get("latency_p99_ms")
    if p99 is not None and float(p99) > thresholds["p99_latency_ms"]:
        violations.append(
            f"p99 latency {p99}ms exceeds threshold {thresholds['p99_latency_ms']}ms"
        )

    for svc in thresholds.get("unhealthy_services", []):
        svc_status = metrics.get("services", {}).get(svc)
        if svc_status and svc_status not in ("ok", "healthy", "up"):
            violations.append(f"Service '{svc}' status: {svc_status}")

    return violations


def write_anomaly_report(violations: list[str], metrics: dict, api_key: str) -> str:
    import anthropic

    snapshot = json.dumps(metrics, indent=2)[:1000]
    violation_list = "\n".join(f"- {v}" for v in violations)

    user_content = f"""Threshold violations detected at {datetime.now(timezone.utc).isoformat()}:

{violation_list}

Raw metrics snapshot:
```json
{snapshot}
```

Write the incident report."""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    return message.content[0].text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True, help="Health/metrics endpoint URL")
    parser.add_argument("--thresholds", default="scripts/observability_thresholds.json")
    parser.add_argument("--output", required=True, help="Output path for anomaly report")
    parser.add_argument("--no-ai", action="store_true", help="Skip Claude; write raw violation list")
    args = parser.parse_args()

    thresholds = load_thresholds(args.thresholds)
    metrics = fetch_metrics(args.endpoint)
    violations = check_thresholds(metrics, thresholds)

    if not violations:
        print("Observability: all checks healthy.")
        with open(args.output, "w") as f:
            f.write("")
        sys.exit(0)

    print(f"Observability: {len(violations)} violation(s) detected:")
    for v in violations:
        print(f"  - {v}")

    if args.no_ai:
        report = "## Problem\n\n" + "\n".join(f"- {v}" for v in violations)
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            report = "## Problem\n\n" + "\n".join(f"- {v}" for v in violations)
            print("WARNING: ANTHROPIC_API_KEY not set — writing raw violation list", file=sys.stderr)
        else:
            report = write_anomaly_report(violations, metrics, api_key)

    with open(args.output, "w") as f:
        f.write(report)

    print(f"Anomaly report written to {args.output}")
    sys.exit(1)


if __name__ == "__main__":
    main()
