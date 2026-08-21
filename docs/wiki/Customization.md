---
title: "Customization"
description: "Adapting the factory to your project: AI review rules, observability thresholds, CI template, WO execution instructions, agent process docs, WO templates, documentation enforcement, and agent memory"
last_verified: 2026-08-21
covers_wos:
  - WO-1014
  - WO-1021
  - WO-1023
  - WO-1032
  - WO-1040
doc_owner: factory-team
---

# Customization

The factory ships with sensible defaults and a set of project-agnostic AI review checks. This page covers the files you edit to adapt it to your specific stack and conventions.

## scripts/review_context.txt

This file is loaded into the Claude system prompt on every PR review. Use it to add checks that only make sense in the context of your project — invariants the AI could not discover by reading the diff alone.

Format: numbered list, one check per line. Lines starting with `#` are treated as comments.

```text
1. db.commit() after every db.execute() write — this project's DB adapter does NOT auto-commit.
   Flag any INSERT/UPDATE/DELETE not followed by db.commit().

2. Every new API route must include the require_role() dependency.
   Missing auth gates are a critical security issue.

3. New migration files must be registered in src/app/storage/adapter.py — no auto-discovery.
   Flag any new migration file not added to the registry.
```

Good checks are specific and falsifiable. "Check for security issues" is not a check — "Flag any use of `eval()` or `exec()` on user-supplied input" is. The AI applies your context on top of its built-in universal checks (hardcoded secrets, swallowed exceptions, SQL injection, missing test coverage).

Delete the file entirely if your project has no specific checks. The universal rules always apply.

## scripts/observability_thresholds.json

The `observability.yml` workflow polls `METRICS_ENDPOINT` every 15 minutes and compares the response against these thresholds. If any threshold is exceeded, it creates a GitHub issue and routes it into the WO workflow via the planning agent.

```json
{
  "error_rate_pct": 1.0,
  "p99_latency_ms": 2000,
  "unhealthy_services": ["database", "cache"]
}
```

| Field | What it checks |
|-------|---------------|
| `error_rate_pct` | Percentage of requests returning 5xx. Alert if above this value. |
| `p99_latency_ms` | 99th percentile response time in milliseconds. Alert if above this value. |
| `unhealthy_services` | Service names to check in the health endpoint's `services` map. Alert if any are not `"healthy"`. |

Set `METRICS_ENDPOINT` as a GitHub Actions variable (**Settings → Secrets and variables → Actions → Variables**) pointing to your application's health or metrics endpoint. If the variable is not set, the observability workflow skips silently.

## .github/workflows/ci.yml.template

The template ships with a `ci.yml.template` rather than a live `ci.yml`. This is intentional — CI is highly project-specific and a w