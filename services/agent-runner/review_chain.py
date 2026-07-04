"""Multi-agent peer review chain — runs before human validation."""
import asyncio
import json
import os
import re

from backends import get_backend
from thread_monitor import ThreadMonitor

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REVIEW_CHAIN: dict[str, list[str]] = {
    "P3": [],
    "P2": ["security", "architecture", "correctness", "performance"],
    "P1": ["security", "architecture", "correctness", "performance"],
    "P0": ["security", "architecture", "correctness", "performance"],
}

SECURITY_REVIEWER_PROMPT = """You are a security code reviewer performing an adversarial review.

You have been given:
- The WO specification (what should be built)
- A git diff of all changes made
- Previous reviewer findings: {previous_findings}

Review ONLY for security issues:
- SQL injection, command injection, SSRF, XSS
- Authentication and authorization bypass
- Hardcoded secrets, API keys, passwords, or tokens
- Missing input validation at system boundaries (user input, external APIs)
- Insecure direct object references or missing ownership checks
- Sensitive data exposure in logs, responses, or error messages
- Path traversal or directory listing vulnerabilities

For EACH issue found, output on its own line:
FINDING: {{"severity": "CRITICAL|HIGH|MEDIUM|LOW", "file": "path/to/file.py", "line": N, "issue": "description", "fix": "recommended fix"}}

If no issues found, output exactly:
VERDICT: LGTM — no security issues found.

Be precise. Do not invent issues. Only flag actual problems visible in the diff.
"""

ARCH_REVIEWER_PROMPT = """You are an architecture code reviewer.

You have been given:
- The WO specification (what should be built)
- A git diff of all changes made
- Previous reviewer findings: {previous_findings}

Review for architecture and design issues:
- Does the implementation match the WO spec exactly (no scope creep, no missing pieces)?
- Does it follow existing codebase patterns (file layout, naming, abstractions)?
- Are abstractions appropriate — not over-engineered, not duplicating existing utilities?
- Are there missing edge cases, error paths, or failure modes?
- Is the code maintainable by the next developer?
- Are added dependencies justified?

For EACH issue found, output on its own line:
FINDING: {{"severity": "CRITICAL|HIGH|MEDIUM|LOW", "file": "path/to/file.py", "line": N, "issue": "description", "fix": "recommended fix"}}

If no issues found, output exactly:
VERDICT: LGTM — architecture looks sound.
"""

CORRECTNESS_REVIEWER_PROMPT = """You are a correctness code reviewer.

You have been given:
- The WO specification (what should be built)
- A git diff of all changes made
- Previous reviewer findings: {previous_findings}

Review for correctness issues:
- Does the code actually do what the spec says?
- Off-by-one errors, integer overflow, type mismatches
- Race conditions or incorrect use of async/await
- Incorrect assumptions about data shape or API contracts
- Missing or incorrect error handling
- Test coverage gaps for important cases

For EACH issue found, output on its own line:
FINDING: {{"severity": "CRITICAL|HIGH|MEDIUM|LOW", "file": "path/to/file.py", "line": N, "issue": "description", "fix": "recommended fix"}}

If no issues found, output exactly:
VERDICT: LGTM — implementation is correct.
"""

PERF_REVIEWER_PROMPT = """You are a performance code reviewer.

You have been given:
- The WO specification (what should be built)
- A git diff of all changes made
- Previous reviewer findings: {previous_findings}

Review for performance issues:
- N+1 database queries or missing batching
- Missing database indexes for new query patterns
- Unbounded result sets (missing pagination, limits, or timeouts)
- Blocking I/O in async contexts (sync file I/O, requests in async handlers)
- Large in-memory data structures or missing streaming for big payloads
- Missing caching for expensive repeated computations

For EACH issue found, output on its own line:
FINDING: {{"severity": "CRITICAL|HIGH|MEDIUM|LOW", "file": "path/to/file.py", "line": N, "issue": "description", "fix": "recommended fix"}}

If no issues found, output exactly:
VERDICT: LGTM — no performance issues found.
"""

REVIEWER_CONFIG: dict[str, dict] = {
    "security": {
        "backend": os.getenv("SECURITY_REVIEWER_BACKEND", "claude"),
        "prompt_template": SECURITY_REVIEWER_PROMPT,
        "blocking_severities": {"CRITICAL", "HIGH"},
    },
    "architecture": {
        "backend": os.getenv("ARCH_REVIEWER_BACKEND", "claude"),
        "prompt_template": ARCH_REVIEWER_PROMPT,
        "blocking_severities": {"CRITICAL"},
    },
    "correctness": {
        "backend": os.getenv("CORRECTNESS_REVIEWER_BACKEND", "claude"),
        "prompt_template": CORRECTNESS_REVIEWER_PROMPT,
        "blocking_severities": {"CRITICAL", "HIGH"},
    },
    "performance": {
        "backend": os.getenv("PERF_REVIEWER_BACKEND", "claude"),
        "prompt_template": PERF_REVIEWER_PROMPT,
        "blocking_severities": {"CRITICAL"},
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_reviewer_prompt(
    reviewer_name: str,
    template: str,
    wo_spec: dict,
    diff: str,
    previous_findings: list[dict],
) -> str:
    wo_id = wo_spec.get("wo", "?")
    title = wo_spec.get("title", "Unknown")
    previous_str = (
        json.dumps(previous_findings, indent=2)
        if previous_findings
        else "None — you are the first reviewer."
    )
    prompt = template.format(previous_findings=previous_str)
    return (
        f"WO: {wo_id} — {title}\n\n"
        f"=== WO SPECIFICATION ===\n"
        f"Priority: {wo_spec.get('priority', 'P2')}\n"
        f"Services: {wo_spec.get('services', 'unknown')}\n"
        f"Notes: {wo_spec.get('notes', '')}\n\n"
        f"=== GIT DIFF ===\n{diff[:8000]}\n\n"  # cap at 8k chars
        f"=== REVIEWER INSTRUCTIONS ===\n{prompt}"
    )


def parse_reviewer_response(response: str) -> list[dict]:
    """Extract structured findings from the reviewer LLM response."""
    findings = []
    for line in response.splitlines():
        line = line.strip()
        if not line.startswith("FINDING:"):
            continue
        json_str = line[len("FINDING:"):].strip()
        # strip markdown code fences if present
        json_str = re.sub(r"^```[a-z]*\n?", "", json_str).rstrip("`")
        try:
            finding = json.loads(json_str)
            if "severity" in finding and "issue" in finding:
                findings.append(finding)
        except (json.JSONDecodeError, ValueError):
            # best-effort: include as unstructured finding
            findings.append({
                "severity": "LOW",
                "file": "unknown",
                "line": 0,
                "issue": json_str[:200],
                "fix": "",
            })
    return findings


def _format_review(
    reviewer_name: str, backend_name: str, findings: list[dict], passed: bool
) -> str:
    icon = "✅" if passed else "🔴"
    header = f"{icon} **{reviewer_name.capitalize()} Review** (via {backend_name})"
    if not findings:
        return f"{header}\n\nLGTM — no issues found."

    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    sorted_findings = sorted(findings, key=lambda f: severity_order.get(f.get("severity", "LOW"), 3))

    lines = [header, ""]
    for f in sorted_findings:
        sev = f.get("severity", "?")
        file_ = f.get("file", "?")
        line = f.get("line", "?")
        issue = f.get("issue", "?")
        fix = f.get("fix", "")
        badge = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}.get(sev, "⚪")
        lines.append(f"{badge} **{sev}** `{file_}:{line}` — {issue}")
        if fix:
            lines.append(f"  ↳ *Fix: {fix}*")
    return "\n".join(lines)


async def get_worktree_diff(worktree: str) -> str:
    """Return a git diff of all committed changes in the worktree."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "HEAD~1", "HEAD", "--",
            cwd=worktree,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        diff = out.decode("utf-8", errors="replace")
        if not diff.strip():
            # fallback: uncommitted changes
            proc2 = await asyncio.create_subprocess_exec(
                "git", "diff",
                cwd=worktree,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out2, _ = await proc2.communicate()
            diff = out2.decode("utf-8", errors="replace")
        return diff or "[no diff available]"
    except Exception as e:
        return f"[diff error: {e}]"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_review_chain(
    wo_spec: dict,
    diff: str,
    monitor: ThreadMonitor,
    previous_findings: list[dict],
) -> tuple[bool, list[dict]]:
    """Run the full review chain for the WO's priority level.

    Returns (chain_passed, all_findings).
    Stops on the first reviewer that finds blocking issues.
    """
    priority = wo_spec.get("priority", "P2")
    reviewer_names = REVIEW_CHAIN.get(priority, REVIEW_CHAIN["P2"])

    if not reviewer_names:
        return True, list(previous_findings)

    all_findings = list(previous_findings)
    chain_passed = True

    await monitor.post(
        f"🔍 Running **{len(reviewer_names)}-reviewer** peer review chain "
        f"({', '.join(reviewer_names)}) for {wo_spec.get('priority', 'P2')} WO...",
        msg_type="text",
    )

    for reviewer_name in reviewer_names:
        cfg = REVIEWER_CONFIG[reviewer_name]
        backend = get_backend(cfg["backend"])

        prompt = build_reviewer_prompt(
            reviewer_name, cfg["prompt_template"], wo_spec, diff, all_findings
        )

        try:
            response = await asyncio.wait_for(backend.ask(prompt), timeout=120)
        except TimeoutError:
            await monitor.post(
                f"⚠️ **{reviewer_name} reviewer** timed out — skipping.",
                msg_type="text",
            )
            continue
        except Exception as e:
            await monitor.post(
                f"⚠️ **{reviewer_name} reviewer** error: {e} — skipping.",
                msg_type="text",
            )
            continue

        findings = parse_reviewer_response(response)
        blocking = [f for f in findings if f.get("severity") in cfg["blocking_severities"]]
        passed = len(blocking) == 0

        all_findings.extend(findings)

        await monitor.post(
            _format_review(reviewer_name, cfg["backend"], findings, passed),
            msg_type="review",
            metadata={
                "reviewer": reviewer_name,
                "backend": cfg["backend"],
                "findings": findings,
                "passed": passed,
            },
        )

        if not passed:
            chain_passed = False
            await monitor.post(
                f"🔴 **{reviewer_name} reviewer** found {len(blocking)} blocking "
                f"issue(s). Chain halted — agent must fix before human review.",
                msg_type="text",
            )
            break

    return chain_passed, all_findings
