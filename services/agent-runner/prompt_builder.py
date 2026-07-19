import base64
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from config import ORCHESTRATOR_URL, GITHUB_REPO

_RUNNER_DIR = Path(__file__).parent
MEMORY_PATH = _RUNNER_DIR / "memory" / "factory_memory.json"
PATTERNS_FILE = _RUNNER_DIR / "clarion_patterns.md"

_FALLBACK_PATTERNS = """## Clarion codebase patterns — see clarion_patterns.md for full details
### DB write: always call db.commit() after db.execute()
### Parameterized queries: never use f-strings in SQL
### API route: every new endpoint needs require_role() dependency
### Migrations: see clarion_patterns.md for current auto-discovery pattern
"""


def _load_memory() -> dict:
    try:
        if MEMORY_PATH.exists():
            return json.loads(MEMORY_PATH.read_text())
    except Exception:
        pass
    return {}


def _load_patterns() -> str:
    try:
        if PATTERNS_FILE.exists():
            return PATTERNS_FILE.read_text().strip()
    except Exception:
        pass
    return _FALLBACK_PATTERNS.strip()


def format_memory_context(memory: dict, wo_spec: dict) -> str:
    """Build the ## Factory Memory section for the agent prompt."""
    if not memory:
        return ""

    wo_services = wo_spec.get("services", "").lower()
    parts: list[str] = []

    # Relevant lessons (matching WO services or applies_to="all")
    lessons = memory.get("lessons", [])
    relevant = [
        l for l in lessons
        if any(
            svc.lower() in wo_services or wo_services in svc.lower() or svc == "all"
            for svc in l.get("applies_to", [])
        )
    ]
    if relevant:
        items = "\n".join(
            f"- {l['content']} [from {l.get('source_wo', '?')}]"
            for l in relevant
        )
        parts.append(f"### Lessons learned (relevant to this WO)\n{items}")

    # Environment state
    env = memory.get("environment", {})
    if env:
        conn = ", ".join(env.get("connected_connectors", [])) or "none"
        not_conn = ", ".join(env.get("NOT_connected", [])) or "—"
        svcs = ", ".join(env.get("healthy_services", [])) or "—"
        recent_migrations = env.get("recent_migrations", [])
        recent_routes = env.get("recent_routes", [])
        env_lines = [
            f"- Connected connectors: {conn}",
            f"- NOT configured: {not_conn}",
            f"- Healthy services: {svcs}",
        ]
        if recent_migrations:
            env_lines.append(f"- Recently added DB migrations: {', '.join(recent_migrations)}")
        if recent_routes:
            env_lines.append(f"- Recently added routes: {', '.join(recent_routes)}")
        parts.append(f"### Environment state (as of {env.get('last_updated', '?')[:10]})\n" + "\n".join(env_lines))

    # Recently completed WOs (last 5)
    done = memory.get("completed_wos", [])[-5:]
    if done:
        items = "\n".join(f"- {d['wo']}: {d['summary']}" for d in reversed(done))
        parts.append(f"### Recently completed WOs\n{items}")

    if not parts:
        return ""

    return "## Factory Memory\n\n" + "\n\n".join(parts)


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


# Loaded at import time so every prompt gets the current patterns file.
# Hot-reload is intentional: updating clarion_patterns.md takes effect on next prompt build.
CLARION_PATTERNS = _load_patterns()


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

    memory = _load_memory()
    memory_section = format_memory_context(memory, wo_spec)
    memory_block = f"{memory_section}\n\n---\n\n" if memory_section else ""

    # Re-load patterns at call time so file changes are reflected without restart
    patterns = _load_patterns()

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

{memory_block}{patterns}

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


def update_memory_after_completion(wo_id: str, wo_spec: dict, summary: str = "") -> None:
    """Append a completed-WO entry to factory_memory.json."""
    try:
        memory = _load_memory()
        done = memory.setdefault("completed_wos", [])
        entry = {
            "wo": wo_id,
            "completed_at": datetime.now(UTC).strftime("%Y-%m-%d"),
            "summary": summary or wo_spec.get("title", wo_id),
        }
        # Deduplicate — replace if already present
        memory["completed_wos"] = [d for d in done if d.get("wo") != wo_id] + [entry]
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(json.dumps(memory, indent=2))
    except Exception as e:
        print(f"[memory] failed to update after completion: {e}")


def update_memory_after_failure(wo_id: str, failure_reason: str, services: str = "") -> None:
    """Add a failure_pattern lesson to factory_memory.json."""
    try:
        memory = _load_memory()
        lessons = memory.setdefault("lessons", [])
        # Avoid duplicate lessons for the same WO
        if any(l.get("source_wo") == wo_id and l.get("category") == "failure_pattern" for l in lessons):
            return
        lesson_id = f"lesson-{len(lessons) + 1:03d}"
        applies = [s.strip() for s in services.split(",") if s.strip()] or ["all"]
        lessons.append({
            "id": lesson_id,
            "added_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_wo": wo_id,
            "category": "failure_pattern",
            "applies_to": applies,
            "content": f"{wo_id} failed: {failure_reason[:300]}",
        })
        MEMORY_PATH.write_text(json.dumps(memory, indent=2))
    except Exception as e:
        print(f"[memory] failed to update after failure: {e}")


def slug_from_title(title: str, wo_number: int | str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{wo_number}-{clean[:40]}"
