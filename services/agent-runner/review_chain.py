"""Multi-agent peer review chain — runs before human validation."""
import asyncio
import json
import os
import re

import httpx
from backends import get_backend
from thread_monitor import ThreadMonitor

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8100")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REVIEW_CHAIN: dict[str, list[str]] = {
    "P3": [],
    "P2": ["security", "architecture", "correctness", "performance"],
    "P1": ["security", "architecture", "correctness", "performance"],
    "P0": ["security", "architecture", "correctness", "performance"],
}

DOC_REVIEWER_PROMPT = """You are a documentation completeness reviewer.

You have been given:
- The WO specification's Documentation Required checklist: {docs_required}
- A git diff of all changes made

Your ONLY job: for each item in the Documentation Required list, check whether the diff contains
a meaningful update to the specified file or section.

For each item NOT addressed in the diff, output on its own line:
FINDING: {{"severity": "HIGH", "file": "{file_placeholder}", "line": 0, "issue": "Documentation Required item not completed: {item_placeholder}", "fix": "Update the file as specified in the WO Documentation Required section"}}

If all items are addressed, or if Documentation Required is empty, output exactly:
VERDICT: LGTM — all documentation requirements fulfilled.

Do not flag stylistic issues. Only flag missing updates for items explicitly listed in Documentation Required.
"""

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
        "prompt_template": SECURITY_REVIEWER_PROMPT,
        "blocking_severities": {"CRITICAL", "HIGH"},
    },
    "architecture": {
        "prompt_template": ARCH_REVIEWER_PROMPT,
        "blocking_severities": {"CRITICAL"},
    },
    "correctness": {
        "prompt_template": CORRECTNESS_REVIEWER_PROMPT,
        "blocking_severities": {"CRITICAL", "HIGH"},
    },
    "performance": {
        "prompt_template": PERF_REVIEWER_PROMPT,
        "blocking_severities": {"CRITICAL"},
    },
    "documentation": {
        "prompt_template": DOC_REVIEWER_PROMPT,
        "blocking_severities": {"HIGH"},
    },
}

# ---------------------------------------------------------------------------
# Config — fetched live from orchestrator so UI changes take effect immediately
# ---------------------------------------------------------------------------

_DEFAULT_REVIEWER_BACKENDS = {
    "security": "claude",
    "architecture": "claude",
    "correctness": "claude",
    "performance": "claude",
    "documentation": "claude",
}


async def _fetch_agent_config() -> dict:
    """Fetch live agent config from orchestrator. Falls back to env vars on failure."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{ORCHESTRATOR_URL}/api/config")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {
        "preferred": os.getenv("PREFERRED_AGENT", "claude"),
        "force_cross_llm_review": True,
        "reviewers": {
            k: os.getenv(f"{k.upper()}_REVIEWER_BACKEND", v)
            for k, v in _DEFAULT_REVIEWER_BACKENDS.items()
        },
    }


def _assign_reviewer_backends(
    reviewer_names: list[str],
    config: dict,
    coding_backend: str,
) -> dict[str, str]:
    """Return {reviewer_name: backend_name} for each reviewer.

    If force_cross_llm_review is on and multiple backends are available,
    rotates reviewers across backends that differ from the coding agent.
    Manual UI assignments are used when the flag is off or only one backend exists.
    """
    from draft_server import _probe_backends as _probe
    available = [b for b, ok in _probe().items() if ok]

    force = config.get("force_cross_llm_review", True)
    if force and len(available) > 1:
        alternatives = [b for b in available if b != coding_backend]
        if not alternatives:
            alternatives = available
        return {
            name: alternatives[i % len(alternatives)]
            for i, name in enumerate(reviewer_names)
        }

    # Manual config — use what the settings UI saved
    reviewer_cfg = config.get("reviewers", _DEFAULT_REVIEWER_BACKENDS)
    default = next(iter(available), "claude")
    return {name: reviewer_cfg.get(name, default) for name in reviewer_names}


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
    coding_backend: str = "",
    docs_required: list[dict] | None = None,
) -> tuple[bool, list[dict]]:
    """Run the full review chain for the WO's priority level.

    Returns (chain_passed, all_findings).
    Stops on the first reviewer that finds blocking issues.
    coding_backend — the backend that wrote the code; used to auto-assign
    reviewers to different LLMs when force_cross_llm_review is enabled.
    docs_required — list of {item, completed} dicts from the WO spec's
    Documentation Required section. When non-empty, a documentation reviewer
    runs after the main chain.
    """
    priority = wo_spec.get("priority", "P2")
    reviewer_names = REVIEW_CHAIN.get(priority, REVIEW_CHAIN["P2"])

    if not reviewer_names:
        return True, list(previous_findings)

    agent_config = await _fetch_agent_config()
    reviewer_backends = _assign_reviewer_backends(reviewer_names, agent_config, coding_backend)

    force = agent_config.get("force_cross_llm_review", True)
    mode_note = f"cross-LLM auto ({coding_backend} wrote → reviewers: {', '.join(set(reviewer_backends.values()))})" if force and coding_backend else "manual"
    all_findings = list(previous_findings)
    chain_passed = True

    await monitor.post(
        f"🔍 Running **{len(reviewer_names)}-reviewer** peer review chain "
        f"({', '.join(reviewer_names)}) for {wo_spec.get('priority', 'P2')} WO — {mode_note}...",
        msg_type="text",
    )

    for reviewer_name in reviewer_names:
        cfg = REVIEWER_CONFIG[reviewer_name]
        assigned_backend = reviewer_backends[reviewer_name]
        backend = get_backend(assigned_backend)

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
            _format_review(reviewer_name, assigned_backend, findings, passed),
            msg_type="review",
            metadata={
                "reviewer": reviewer_name,
                "backend": assigned_backend,
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

    # Documentation reviewer — runs after the main chain if docs_required is non-empty
    if chain_passed and docs_required:
        doc_cfg = REVIEWER_CONFIG["documentation"]
        doc_backend_name = next(iter(_assign_reviewer_backends(
            ["documentation"], agent_config, coding_backend
        ).values()), "claude")
        doc_backend = get_backend(doc_backend_name)
        docs_str = json.dumps(docs_required, indent=2)
        doc_prompt = (
            f"WO: {wo_spec.get('wo', '?')} — {wo_spec.get('title', '')}\n\n"
            f"=== DOCUMENTATION REQUIRED ===\n{docs_str}\n\n"
            f"=== GIT DIFF ===\n{diff[:8000]}\n\n"
            + doc_cfg["prompt_template"].format(
                docs_required=docs_str,
                file_placeholder="<file>",
                item_placeholder="<item>",
            )
        )
        try:
            doc_response = await asyncio.wait_for(doc_backend.ask(doc_prompt), timeout=120)
            doc_findings = parse_reviewer_response(doc_response)
            doc_blocking = [f for f in doc_findings if f.get("severity") in doc_cfg["blocking_severities"]]
            doc_passed = len(doc_blocking) == 0
            all_findings.extend(doc_findings)
            await monitor.post(
                _format_review("documentation", doc_backend_name, doc_findings, doc_passed),
                msg_type="review",
                metadata={
                    "reviewer": "documentation",
                    "backend": doc_backend_name,
                    "findings": doc_findings,
                    "passed": doc_passed,
                },
            )
            if not doc_passed:
                chain_passed = False
                await monitor.post(
                    f"🔴 **documentation reviewer** found {len(doc_blocking)} missing doc update(s). "
                    f"Update the required files before requesting human review.",
                    msg_type="text",
                )
        except Exception as e:
            await monitor.post(
                f"⚠️ **documentation reviewer** error: {e} — skipping.",
                msg_type="text",
            )

    return chain_passed, all_findings
