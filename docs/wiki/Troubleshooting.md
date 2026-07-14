---
title: "Troubleshooting"
description: "Diagnosing and resolving common factory issues: startup, agents, CI failures, and Docker"
last_verified: 2026-07-11
covers_wos: []
doc_owner: factory-team
---

# Troubleshooting

## Factory won't start

**Symptom:** `make up` fails or services do not come up.

**Check Docker first:**
```bash
docker info
```

If Docker is not running, start Docker Desktop and try again. The pre-push hook also blocks pushes when Docker is offline if backend files changed.

**Port conflict:** If port 8099 or 8100 is already in use:
```bash
lsof -i :8099
lsof -i :8100
```

Identify and stop whatever is using those ports, then `make up` again. Alternatively, change the port mapping in `docker-compose.status.yml`.

**Missing `.env.runtime`:** The `make up` target reads Keychain and writes `.env.runtime`. If Keychain entries are missing:
```bash
make agent-setup
```

Re-run setup to store credentials, then try `make up` again.

## Orchestrator shows "offline" in the dashboard

The Overview tab's agent-runner badge says "Offline" when port 8101 is not responding. This is the draft server inside the agent-runner process — it means the agent-runner is not running.

```bash
make agent-run
```

The orchestrator itself (port 8100) is a Docker service and should always be up when `make up` has been run. If the orchestrator container itself is down:
```bash
docker ps | grep orchestrator
docker logs factory-orchestrator
make restart
```

## Agent backend shows "unavailable" in the WO form

The New WO form grays out backends that the draft server cannot find. The draft server probes each CLI at startup.

**For subscription backends (claude, cursor, codex, gemini):**
1. Confirm the agent-runner is running (`make agent-run`).
2. Check that the CLI is installed and in PATH: `which claude`, `which agent`, `which codex`, `which gemini`.
3. Confirm you are logged in to the subscription service. Cursor's CLI is `agent`, not `cursor`.

**For claude-api:**
The claude-api backend is available when `ANTHROPIC_API_KEY` is set in **Settings → Authentication**. If the badge shows "Not set," the backend will be unavailable.

## PM chat returns "No AI backend available"

The PM assistant uses the agent-runner's `ask()` function for subscription backends. If no backends are available, the orchestrator falls back to `claude-api`. If `ANTHROPIC_API_KEY` is also not set, the PM has nowhere to route the request.

Fix: set `ANTHROPIC_API_KEY` in **Settings → Authentication**, or start the agent-runner with at least one subscription CLI available.

## WO stuck after a CI failure or build crash

When the runner's container rebuild or CI gate fails mid-run, it automatically calls `POST /api/dispatch/{wo}/retry` to release the WO back into the queue. In most cases no intervention is needed — the WO will reappear as open on the next poll.

If the auto-release did not fire (e.g., the runner process was killed before it could call the endpoint) and the WO shows as `in_progress` with no active agent:

```bash
curl -X POST http://localhost:8100/api/dispatch/WO-NNN/retry
```

The runner also posts a `ci_analysis` thread message before releasing, so the reason for the failure is stored in the WO thread. On the next attempt, `format_prior_context()` injects this analysis into the agent's prompt alongside any prior reviewer rejection reasons.

To inspect what failure context is queued for a WO's next attempt:
```bash
curl -s http://localhost:8100/api/thread/WO-NNN/messages | python3 -m json.tool | grep -A5 '"type": "ci_analysis"'
curl -s http://localhost:8100/api/validations | python3 -m json.tool | grep -A5 '"reject_reason"'
```

## WO stuck in "claimed" but agent isn't running

A WO in `claimed` or `in_progress` status with no recent heartbeat means the agent-runner crashed or was stopped while a WO was in flight.

**Check the last heartbeat:** The Overview tab shows when the last checkin was received. If it was more than a few minutes ago and the runner is not visibly running, the runner has stopped.

**Restart the runner:**
```bash
make agent-run
```

The runner will re-claim the WO. The claim file (`docs/factory/runs/WO-NNN.json`) acts as a mutex — if it already exists, the runner will detect it is still the owner and continue rather than starting fresh.

If you want to abandon the WO and start fresh:
1. Delete the claim file from the repository: `docs/factory/runs/WO-NNN.json`
2. Push the deletion to `main`
3. The runner will claim the WO as new on the next poll

## Dependabot PRs not getting bridge issues

The `dependabot-wo-bridge.yml` workflow fires when a Dependabot PR's CI fails. If bridge issues are not appearing:

1. Confirm the workflow file exists: `.github/workflows/dependabot-wo-bridge.yml`
2. Check the workflow run history in GitHub Actions — the trigger fires on `workflow_run` completion of the CI workflow.
3. Confirm the CI workflow's `name:` field matches what the bridge workflow is listening for.
4. Confirm `ANTHROPIC_API_KEY` is set in GitHub repo secrets — the workflow calls the planning agent.

## GitHub Actions failing with missing secrets

Most AI workflows require `ANTHROPIC_API_KEY`. If you see errors like `ANTHROPIC_API_KEY not set` or `AuthenticationError` in Actions logs:

1. Go to your GitHub repo **Settings → Secrets and variables → Actions**
2. Add a secret named `ANTHROPIC_API_KEY` with your key from [console.anthropic.com](https://console.anthropic.com)

The local factory runtime and the GitHub Actions runtime have separate secret stores. Setting the key in the dashboard **Settings → Authentication** covers the local runtime only.

## AI review blocking all PRs unexpectedly

If the `Claude Code Review` status check is failing on every PR:

1. Check the Actions run log — if the error is `ANTHROPIC_API_KEY not set`, see above.
2. If the review ran but produced a "Review required" verdict, read the review comment on the PR. The verdict is anchored to the `### Verdict` section — look there for the specific failing check.
3. If the diff is very large (4,000+ lines), the review may have been truncated. Split the PR.

To temporarily unblock a PR without fixing the underlying issue, a repo admin can override the required status check from the PR merge box. Use sparingly.

## Notifications not arriving

See the [Notifications troubleshooting section](Notifications.md) for step-by-step diagnosis of ntfy and Slack delivery issues.

## Dashboard data looks stale

The dashboard auto-refreshes every 60 seconds. If data looks wrong after more than a minute:

1. Hard refresh the browser (Cmd+Shift+R).
2. Check that the orchestrator is running: `docker ps | grep orchestrator`.
3. The orchestrator polls GitHub every 5 minutes by default (configurable via `POLL_INTERVAL`). WOs that were just merged to main may not appear as done for up to 5 minutes.

If the orchestrator container is up but data is clearly wrong (e.g., a WO shows in-progress but the agent finished hours ago), check the orchestrator logs:
```bash
docker logs factory-orchestrator --tail=100
```

Look for errors in the poll cycle or database write operations.
