import base64
import re
from config import ORCHESTRATOR_URL, GITHUB_REPO


QUALITY_MANDATE = """
## MANDATORY QUALITY, SECURITY & OPTIMIZATION REQUIREMENTS

Before calling POST {orchestrator_url}/api/validate you MUST:

1. Run `make ci-local` — zero lint errors, zero type errors, all tests pass.
   CI failure is BLOCKING. Fix all errors before calling /api/validate.
   NOTE: black and ruff are auto-fixed by the quality gate before CI runs,
   so formatting-only failures will be fixed automatically. Focus on real errors.

2. SECURITY — your implementation MUST NOT contain:
   - Hardcoded secrets, API keys, or passwords in code
   - SQL string concatenation (always use parameterized queries)
   - Missing require_role() on new API endpoints
   - Unvalidated user input passed to shell commands, SQL, or file paths
   - XSS vectors (unsanitized user content rendered as HTML)
   - eval(), innerHTML=, or document.write() with dynamic input (JS/TS)

3. PERFORMANCE — your implementation MUST NOT contain:
   - Blocking I/O inside async handlers (no time.sleep(), no synchronous
     file reads, no requests.get() — use asyncio/httpx equivalents)
   - Unbounded database queries (always apply LIMIT or pagination)
   - Loading entire large datasets into memory when streaming is possible
   - N+1 query patterns (batch with IN clauses or joins)

4. CODE QUALITY — your implementation MUST:
   - Follow existing codebase patterns exactly — naming, file layout,
     error handling style, abstraction level
   - Not introduce new abstractions unless the WO spec explicitly requires them
   - Handle all error paths (network failures, missing data, bad input)
   - Keep functions focused — if a function exceeds ~40 lines, split it

5. The quality gate (CI + security + JS scanner + peer review chain) runs
   before your validate request is accepted. Fix all issues if rejected.

These requirements are enforced at the platform level. There is no bypass.
""".strip()


FACTORY_API_SECTION = """
## Factory API — call these during your work

Base URL: {orchestrator_url}

POST /api/checkin          Send a heartbeat every 2 minutes with your current step.
                           Body: {{"wo": "{wo_id}", "agent": "{agent_name}", "step": "description"}}

POST /api/validate         Signal that you need human review. REQUIRES a GitHub PR.
                           You MUST commit, push, and open the PR first. Then call:
                           Body: {{
                             "wo": "{wo_id}",
                             "agent": "{agent_name}",
                             "verify_url": "<PR URL>",
                             "steps": ["Review PR: <PR URL>", "Verify at https://localhost"],
                             "ci_passed": true,
                             "security_passed": true,
                             "thread_summary": "What I built and key decisions",
                             "pr_url": "<full GitHub PR URL — REQUIRED>"
                           }}

POST /api/complete          Signal that the PR has merged and the WO is done.
                           Body: {{"wo": "{wo_id}", "agent": "{agent_name}"}}
""".strip()


PROCESS_SECTION = """
## Required Process (follow AGENT_PROCESS.md exactly)

1.  cd to the clarion worktree (already created for you at {worktree_path})
2.  Implement the WO
3.  If backend files changed: make build-svc SVC=<service>
4.  make wait-healthy
5.  make smoke-test
6.  make ci-local   ← MUST PASS before proceeding
7.  Fix any CI failures, then re-run step 6
8.  git add <specific files you changed> && git commit  (do NOT use git add -A)
9.  git push -u origin <branch>
10. gh pr create — get the PR URL from the output
11. Call POST /api/validate with ci_passed=true, security_passed=true, AND pr_url=<PR URL>
    The orchestrator REJECTS validation without a pr_url. Steps 8-10 are mandatory first.
12. After human approval: for P2 run gh pr merge --auto --squash
13. Call POST /api/complete after merge

## Frontend dependency rule
If you edit frontend/package.json, you MUST also regenerate the lock file:
  cd frontend && npm install && cd ..
Then commit BOTH package.json AND package-lock.json together. Never edit package.json
without updating the lock file — `npm ci` in the Docker build will fail otherwise.
""".strip()


CLARION_PATTERNS = """
## Clarion codebase patterns — copy these exactly, do not invent alternatives

### DB write (ALWAYS call db.commit() after execute())
```python
db.execute(text("INSERT INTO my_table (col) VALUES (:val)"), {"val": value})
db.commit()
```

### Parameterized queries (NEVER use f-strings or % formatting in SQL)
```python
# CORRECT
result = db.execute(text("SELECT * FROM endpoints WHERE mac = :mac"), {"mac": mac})
# WRONG — SQL injection risk
result = db.execute(text(f"SELECT * FROM endpoints WHERE mac = '{mac}'"))
```

### API route with auth (every new endpoint needs require_role)
```python
from clarion.api.auth import require_role

@router.get("/api/my-resource")
def get_resource(db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    ...
```

### SQLAlchemy raw query — use text(), not Query objects
```python
from sqlalchemy import text
rows = db.execute(text("SELECT id, name FROM table WHERE active = :active"), {"active": True}).fetchall()
# Access columns by name: row.id, row.name  — NOT row[0]
```

### Migration file (register in src/clarion/storage/adapter.py after creating)
```python
# In adapter.py _MIGRATIONS list:
"sql/migrations/add_my_table.sql",
```
""".strip()


def format_prior_context(rejections: list[dict], thread_msgs: list[dict]) -> str:
    """
    Build a ⚠️ RETRY CONTEXT block from prior rejection reasons and CI failure
    analyses posted to the thread. Returns empty string if nothing to inject.
    """
    parts: list[str] = []

    if rejections:
        latest = rejections[0]
        reason = (latest.get("reject_reason") or "").strip()
        attempt = len(rejections)
        if reason:
            parts.append(
                f"### Previous reviewer rejection (attempt {attempt})\n\n{reason}"
            )

    # Pull CI analysis messages posted by the runner on prior failures
    ci_analyses = [
        m["content"]
        for m in thread_msgs
        if m.get("type") == "ci_analysis" and m.get("content")
    ]
    if ci_analyses:
        # Most recent CI analysis is last in the list
        parts.append(f"### Prior CI failure analysis\n\n{ci_analyses[-1]}")

    if not parts:
        return ""

    body = "\n\n".join(parts)
    return (
        "## ⚠️ RETRY — fix the specific issues below before doing anything else\n\n"
        "This WO was attempted before and failed. Do NOT start from scratch.\n"
        "Read the issues below, apply the targeted fixes, then re-run CI and validate.\n\n"
        f"{body}\n\n"
        "---"
    )


def build_prompt(wo_spec: dict, wo_markdown: str, worktree_path: str, agent_name: str,
                 prior_context: str = "") -> str:
    wo_id = f"WO-{wo_spec['wo']}" if "wo" in wo_spec else f"WO-{wo_spec.get('number', '?')}"
    title = wo_spec.get("title", "Unknown")
    priority = wo_spec.get("priority", "P2")
    effort = wo_spec.get("effort", "M")

    retry_block = f"{prior_context}\n\n" if prior_context else ""

    return f"""You are an AI agent working in the Clarion AI Factory.

{retry_block}## Your Assignment

{wo_id}: {title}
Priority: {priority} | Effort: {effort}
Worktree: {worktree_path}

{QUALITY_MANDATE.format(orchestrator_url=ORCHESTRATOR_URL)}

---

## Full Work Order Specification

{wo_markdown}

---

{CLARION_PATTERNS}

---

{PROCESS_SECTION.format(worktree_path=worktree_path)}

---

{FACTORY_API_SECTION.format(
    orchestrator_url=ORCHESTRATOR_URL,
    wo_id=wo_id,
    agent_name=agent_name,
)}

---

Begin now. Start by reading the WO spec above carefully, then implement it.
"""


def slug_from_title(title: str, wo_number: int | str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{wo_number}-{clean[:40]}"
