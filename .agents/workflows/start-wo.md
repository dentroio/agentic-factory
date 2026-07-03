# Workflow: /startwo

Start working on the next available Work Order.

## Steps

1. **Query the orchestrator** for the next unclaimed WO:

   ```bash
   curl http://localhost:8100/api/next
   ```

   If orchestrator is unavailable, find the highest-priority open WO manually:
   ```bash
   ls docs/project_management/work_orders/ | sort -V
   ```
   Read each spec and pick the first with `Status: 📋 Open` that has no unmet dependencies.

2. **Read the WO spec** in full:

   ```bash
   cat docs/project_management/work_orders/WO-NNN-slug.md
   ```

3. **Sync with main:**

   ```bash
   git checkout main && git pull origin main
   ```

4. **Claim the WO** via orchestrator:

   ```bash
   curl -X POST http://localhost:8100/api/claim \
     -H "Content-Type: application/json" \
     -d '{"wo": "WO-NNN", "agent": "Gemini", "workstation": "'"$(hostname)"'"}'
   ```

5. **Create the branch:**

   ```bash
   git checkout -b wo/NNN-slug
   ```

6. **Read the development environment** section in `AGENT_PROCESS.md §3` to know how to deploy.

7. **Begin implementation.** Check in periodically:

   ```bash
   curl -X POST http://localhost:8100/api/checkin \
     -d '{"wo": "WO-NNN", "agent": "Gemini", "step": "Current step description"}'
   ```

## What to do if the WO is blocked

If the WO's `depends_on` list has items that aren't done yet, pick the next WO in the queue instead. Do not start a blocked WO.

## After starting

Follow the execution steps in [wo-execution.md](../skills/wo-execution.md).
