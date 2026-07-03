# Workflow: /completwo

Wrap up a Work Order and get it into review.

## Steps

1. **Confirm acceptance criteria are met.** Re-read the WO spec's `## Acceptance Criteria` section and verify each item.

2. **Deploy and verify the running system:**
   - For Docker-based projects: `make build-svc SVC=<name> && make wait-healthy && make smoke-test`
   - For CD-based projects: merge will trigger auto-deploy; write explicit verification steps in the PR

3. **⛔ Stop — ask the human to verify** before committing. See [wo-execution.md §step 7](../skills/wo-execution.md).

4. **Run the CI gate:**

   ```bash
   make ci-local
   ```

   Fix any failures before continuing.

5. **Sync with main before opening the PR:**

   ```bash
   git pull --rebase origin main
   ```

6. **Open the PR:**

   ```bash
   gh pr create \
     --title "feat(scope): WO-NNN — Title" \
     --body "$(cat <<'EOF'
   ## Summary
   - What changed and why

   ## Work Order
   WO-NNN — Title

   ## Test plan
   - [ ] make ci-local passes
   - [ ] Relevant tests pass or were added

   ## UI Verification
   1. Open [APP_URL] — log in as [credentials]
   2. Navigate to [path]
   3. [Action]
   4. Expected: [exact result]

   🤖 Generated with Google Antigravity
   EOF
   )"
   ```

7. **Auto-merge if P2:**

   ```bash
   gh pr merge --auto --squash
   ```

   For P0/P1: notify the human and wait for their approval.

8. **Submit to orchestrator for validation** (when human checkpoint is needed):

   ```bash
   curl -X POST http://localhost:8100/api/validate \
     -H "Content-Type: application/json" \
     -d '{
       "wo": "WO-NNN",
       "agent": "Gemini",
       "workstation": "'"$(hostname)"'",
       "verify_url": "http://localhost:8099",
       "steps": [
         "Open APP_URL",
         "Navigate to X",
         "Verify Y appears"
       ]
     }'
   ```

9. **Update PM docs:**
   - Add a row to `docs/project_management/PROGRESS.md`
   - Update relevant section in `docs/project_management/CAPABILITY_STATUS.md`

10. **After merge, sync:**

    ```bash
    make sync
    ```
