# Skill: Work Order Execution

## How to read a WO spec

Every WO lives at `docs/project_management/work_orders/WO-NNN-slug.md` and has:

- **Background** — why this exists
- **What Needs to Happen** — actionable steps
- **Acceptance Criteria** — numbered, checkable conditions for done
- **Testing** — how to verify
- **Execution** — branch name, risk tier, PR title, dependencies

Always read the `## Execution` section first — it tells you the branch, risk tier, and PM docs to update.

## Step-by-step execution

```
1.  Read the full WO spec
2.  Read §3 Development Environment in AGENT_PROCESS.md — know how to deploy
3.  git checkout main && git pull origin main
4.  git checkout -b wo/NNN-slug
5.  Implement the work
6.  Deploy and verify (rebuild containers or push to staging)
7.  ⛔ STOP — ask the user to verify the running system (see below)
8.  make ci-local (must pass before pushing)
9.  git pull --rebase origin main
10. Open PR using the template in AGENT_PROCESS.md §4
11. P2: gh pr merge --auto --squash
    P0/P1: notify human and wait
12. Update PM docs: PROGRESS.md row, CAPABILITY_STATUS.md section
```

## ⛔ Step 7 — User verification checkpoint

For UI changes, ask the user:

> I've deployed the changes. To verify:
> 1. Open [APP_URL] — log in as [test credentials]
> 2. Navigate to [exact path]
> 3. [Specific action]
> 4. Expected: [exact outcome]
> Confirm and I'll commit.

For backend-only changes, show the curl output and ask: "Does this look correct?"

**Do not commit until the user confirms.**

## WO status values

| Status | Meaning |
|--------|---------|
| 📋 Open | Not started |
| 🔄 In Progress | Branch active, no PR |
| 👀 In Review | PR open |
| ✅ Complete | Merged |
| ⛔ Blocked | Waiting on dependency |

## Claim via orchestrator (optional)

When the orchestrator is running, claim your WO before starting:

```bash
curl -X POST http://localhost:8100/api/claim \
  -H "Content-Type: application/json" \
  -d '{"wo": "WO-NNN", "agent": "Gemini", "workstation": "my-host"}'
```

Check in periodically while working:

```bash
curl -X POST http://localhost:8100/api/checkin \
  -d '{"wo": "WO-NNN", "agent": "Gemini", "step": "Implementing endpoint"}'
```

When ready for human review:

```bash
curl -X POST http://localhost:8100/api/validate \
  -d '{"wo": "WO-NNN", "agent": "Gemini", "verify_url": "http://localhost:8099", "steps": ["Open /settings", "Verify X appears"]}'
```
