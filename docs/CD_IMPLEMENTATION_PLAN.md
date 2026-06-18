# CD Implementation Plan — Agentic Factory

## Overview

Continuous Deployment closes the last gap in the factory loop: after a PR merges to main,
the new code automatically deploys, smoke tests run, and any failure opens a GitHub issue
without human intervention.

This plan covers the two-part implementation:

1. **Self-hosted runners** — GitHub Actions runners on your local network, so deploy
   workflows have access to your infrastructure (Docker, VMs, internal registries)
2. **deploy.yml** — the CD workflow: build → deploy → smoke test → rollback on failure

---

## Part 1 — Self-Hosted Runners

### Why self-hosted

GitHub-hosted runners (`ubuntu-latest`) cannot reach private infrastructure on your
local network. Self-hosted runners run inside your network so they can:

- Pull images from a private registry
- Run `docker compose` against local services
- Reach internal health endpoints for smoke tests
- Access secrets stored locally (Vault, env files)

### Machine requirements

| Requirement | Minimum |
|-------------|---------|
| OS | Ubuntu 22.04 LTS (recommended) or macOS |
| CPU | 2 cores |
| RAM | 4 GB |
| Disk | 40 GB (for Docker image cache) |
| Network | Outbound HTTPS to github.com; inbound not required |

### Setup steps (one-time per machine)

**1. Create a runner in GitHub**

In your repo: **Settings → Actions → Runners → New self-hosted runner**

Select OS, then follow the generated commands (they include a unique registration token).

```bash
# Example — exact commands come from the GitHub UI
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64-2.x.x.tar.gz -L https://github.com/actions/runner/releases/...
tar xzf ./actions-runner-linux-x64-2.x.x.tar.gz
./config.sh --url https://github.com/YOUR-ORG/YOUR-REPO --token YOUR-TOKEN
```

**2. Install as a system service (so it survives reboots)**

```bash
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

**3. Label the runner**

In GitHub: Settings → Actions → Runners → click the runner → add labels.

Recommended labels:
- `self-hosted` (auto-assigned)
- `local-network` (for deploy jobs that need infra access)
- `linux` or `macos`

**4. Security hardening**

Self-hosted runners execute arbitrary code from your repository. For private repos this is
low risk, but apply these controls:

- Run the runner as a dedicated non-root user: `adduser github-runner`
- Do not expose the machine to the public internet
- Rotate the runner registration token if the runner is decommissioned
- For Docker: add `github-runner` to the `docker` group, not root

**5. Optional — runner group (if multiple runners)**

Settings → Actions → Runner groups → New group: `deploy-runners`

Restrict group to specific workflows (e.g., `deploy.yml` only) for blast-radius control.

---

## Part 2 — deploy.yml Workflow

### Workflow structure

```
push to main
     │
     ▼
Build Docker images (or compile binary)
     │
     ▼
Push to registry (or copy to deploy target)
     │
     ▼
Deploy (docker compose up, kubectl apply, etc.)
     │
     ▼
Wait for health endpoint (configurable timeout)
     │
  ┌──┴──────────────────┐
  │                     │
healthy            unhealthy
  │                     │
  ▼                     ▼
post "Deploy OK"   rollback to previous
comment on last    image + open incident
merged PR          issue + page on-call
```

### Filling in deploy.yml.template

Copy the template and fill in these sections:

```bash
cp .github/workflows/deploy.yml.template .github/workflows/deploy.yml
```

Key placeholders to fill:

| Placeholder | What to put |
|-------------|-------------|
| `{{BUILD_COMMAND}}` | `docker compose build` or `go build ./...` |
| `{{PUSH_COMMAND}}` | `docker compose push` or `docker save \| ssh ...` |
| `{{DEPLOY_COMMAND}}` | `docker compose up -d` or `kubectl apply -f k8s/` |
| `{{HEALTH_ENDPOINT}}` | `http://localhost:8000/health` |
| `{{ROLLBACK_COMMAND}}` | `docker compose rollback` or `kubectl rollout undo` |
| `{{SMOKE_TEST_COMMAND}}` | `python3 scripts/smoke_test.py` |

The runner label in the workflow must match what you set in Step 3 above:

```yaml
jobs:
  deploy:
    runs-on: [self-hosted, local-network]
```

### Clarion-specific deploy sequence

For Clarion's Docker Compose stack, the sequence is:

```bash
# 1. Build changed services
docker compose build data-service correlation-service gateway ...

# 2. Roll out with zero-downtime (one service at a time)
docker compose up -d --no-deps data-service
docker compose up -d --no-deps correlation-service
docker compose up -d --no-deps gateway

# 3. Health check
curl -f http://localhost:8000/health || exit 1

# 4. Smoke test
python3 scripts/smoke_test.py --env production

# 5. Rollback (on failure)
docker compose down
git stash   # keep deploy machine in sync
docker compose up -d   # comes up on previous image (if images are tagged)
```

### Image tagging strategy

Tag images with the git SHA so rollbacks are reliable:

```bash
IMAGE_TAG=$(git rev-parse --short HEAD)
docker compose build
docker tag clarion-data-service:latest clarion-data-service:$IMAGE_TAG
docker tag clarion-data-service:latest clarion-data-service:prev  # previous = current before deploy
```

Rollback then becomes:

```bash
docker tag clarion-data-service:prev clarion-data-service:latest
docker compose up -d data-service
```

### Secrets on the runner

The runner has local network access to Vault. For secrets needed at deploy time
(registry credentials, deploy SSH keys), prefer:

1. **Vault** — the runner can read from Vault directly since it's on the same network
2. **GitHub Actions secrets** — for values that must be injected into the workflow
   (e.g., `REGISTRY_TOKEN`) — set via Settings → Secrets → Actions

Never store secrets in the workflow YAML or in the repo.

---

## Part 3 — Smoke Tests

`scripts/smoke_test.py` already exists in Clarion. Extend it with post-deploy checks:

```python
# Minimum checks after every deploy
checks = [
    ("Gateway health",   "GET", "/health",              200),
    ("Auth works",       "POST", "/api/auth/login",     200),
    ("Endpoints load",   "GET", "/api/endpoints",       200),
    ("Groups load",      "GET", "/api/groups",          200),
    ("Settings load",    "GET", "/api/settings",        200),
]
```

Run with `--env production` to target the live endpoint instead of localhost.

---

## Implementation Work Orders

| WO | Title | Risk | Effort |
|----|-------|------|--------|
| WO-320 | Self-hosted runner setup on local machine | P1 | ~2h |
| WO-321 | deploy.yml for Clarion Docker Compose stack | P1 | ~3h |
| WO-322 | Image tagging + rollback script | P2 | ~2h |
| WO-323 | Smoke test expansion (post-deploy coverage) | P2 | ~2h |
| WO-324 | Incident auto-open on deploy failure | P2 | ~1h |

Start with WO-320 (runner setup) — everything else blocks on having a working runner.

---

## Open Decisions

1. **Registry**: Where do Docker images live? Options:
   - Local registry on the deploy machine (simplest, no egress)
   - GitHub Container Registry (ghcr.io) — free for private repos, requires GITHUB_TOKEN
   - Docker Hub (requires credentials secret)

2. **Deploy target**: Is the runner on the same machine as the production Docker Compose
   stack, or does it SSH into a separate deploy host?

3. **Environments**: Deploy to staging first, then production? Or single environment?

4. **On-call**: Who/what gets paged on deploy failure? Options:
   - GitHub issue only (current plan)
   - Slack webhook
   - PagerDuty via observability.yml (already wired)

Resolve these before writing WO-321.
