import base64
import re
from config import ORCHESTRATOR_URL, GITHUB_REPO


QUALITY_MANDATE = """
## MANDATORY QUALITY & SECURITY REQUIREMENTS

Before calling POST {orchestrator_url}/api/validate you MUST:

1. Run `make ci-local` — zero lint errors, zero type errors, all tests pass.
   CI failure is BLOCKING. Fix all errors before calling /api/validate.

2. Your implementation MUST NOT contain:
   - Hardcoded secrets, API keys, or passwords in code
   - SQL string concatenation (always use parameterized queries)
   - Missing require_role() on new API endpoints
   - Unvalidated user input passed to shell commands, SQL, or file paths
   - XSS vectors (unsanitized user content rendered as HTML)

3. Follow existing codebase patterns exactly. Do not introduce new
   abstractions unless the WO spec explicitly requires them.

4. The quality gate (CI + security scanner) runs before your validate
   request is accepted. Fix all issues and re-run if it rejects you.

These requirements are enforced at the platform level. There is no bypass.
""".strip()


FACTORY_API_SECTION = """
## Factory API — call these during your work

Base URL: {orchestrator_url}

POST /api/checkin          Send a heartbeat every 2 minutes with your current step.
                           Body: {{"wo": "{wo_id}", "agent": "{agent_name}", "step": "description"}}

POST /api/validate         Signal that you need human review before committing.
                           Body: {{
                             "wo": "{wo_id}",
                             "agent": "{agent_name}",
                             "verify_url": "http://localhost:8000/...",
                             "steps": ["check X", "verify Y"],
                             "ci_passed": true,
                             "security_passed": true,
                             "thread_summary": "What I built and key decisions"
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
8.  Call POST /api/validate with ci_passed=true and security_passed=true
9.  After human approval: git add <files> && git commit && git push
10. gh pr create with WO number in title
11. For P2: gh pr merge --auto --squash
12. Call POST /api/complete after merge
""".strip()


def build_prompt(wo_spec: dict, wo_markdown: str, worktree_path: str, agent_name: str) -> str:
    wo_id = f"WO-{wo_spec['wo']}" if "wo" in wo_spec else f"WO-{wo_spec.get('number', '?')}"
    title = wo_spec.get("title", "Unknown")
    priority = wo_spec.get("priority", "P2")
    effort = wo_spec.get("effort", "M")

    return f"""You are an AI agent working in the Clarion AI Factory.

## Your Assignment

{wo_id}: {title}
Priority: {priority} | Effort: {effort}
Worktree: {worktree_path}

{QUALITY_MANDATE.format(orchestrator_url=ORCHESTRATOR_URL)}

---

## Full Work Order Specification

{wo_markdown}

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
