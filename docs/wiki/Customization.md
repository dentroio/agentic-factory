---
title: "Customization"
description: "Adapting the factory to your project: AI review rules, observability thresholds, CI template, and WO execution instructions"
last_verified: 2026-07-12
covers_wos: []
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

The template ships with a `ci.yml.template` rather than a live `ci.yml`. This is intentional — CI is highly project-specific and a wrong default would fail immediately.

To activate CI:

```bash
cp .github/workflows/ci.yml.template .github/workflows/ci.yml
```

Then edit `ci.yml` to add your actual build, lint, and test steps. The template includes placeholder jobs named `Lint` and `Unit Tests` — rename them to match whatever you add. The job names you choose must match the required status checks in your branch ruleset (**Settings → Rules → Rulesets**).

The `ai-review.yml`, `ci-failure-notifier.yml`, and `ci-auto-fix.yml` workflows all refer to a workflow named `CI` — keep that as the `name:` field at the top of your `ci.yml`.

## WO Execution section

Every WO spec has an **Execution** section injected at the top of every agent prompt before the WO content. It describes project-specific rules the agent must follow — service names, make targets, safety gates.

Open any WO spec file at `docs/work_orders/WO-NNN-slug.md` and look at the Execution section to see the format. When you create WOs via the PM or the UI, the PM pre-fills this section based on your project context. You can also edit it directly after the spec is drafted.

Common things to put in the Execution section:
- Which services to rebuild after editing which files
- How to run the smoke test
- The commit and PR workflow (branch naming, merge strategy)
- Mandatory review steps the agent must complete before opening a PR

## Agent backend selection

The default backend is set during `make agent-setup`. To change it after setup:

```bash
# Edit the prefs file directly
echo "PREFERRED_AGENT=cursor" >> ~/.config/factory-agent/prefs
```

Or run `make agent-setup` again and pick a different backend when prompted.

To dispatch a specific WO with a different backend than the default, tell the PM:

> "Start WO-123 with Gemini."

The PM sends a dispatch signal that overrides the default for that one WO.

See [Agent Backends](Agent-Backends) for a comparison of when to use each backend.

## Environment variables

Non-secret configuration is stored in `~/.config/factory-agent/prefs`. Secrets (GitHub token, API keys, ntfy topic, Slack webhook) are stored in the macOS Keychain under the service name `dentroio-factory` and read at runtime by `scripts/factory-env.sh`.

To add a new secret after initial setup:

```bash
security add-generic-password -s "dentroio-factory" -a "MY_NEW_KEY" -w "the-value"
```

To read a stored secret:

```bash
security find-generic-password -s "dentroio-factory" -a "MY_NEW_KEY" -w
```

Docker Compose reads secrets via the `factory-env.sh` script, which exports them as environment variables before `docker compose up`. You do not need a `.env` file.
