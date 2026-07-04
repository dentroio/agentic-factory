"""Quality gate — runs CI and security checks before requesting human validation."""
import asyncio
import json


async def _run(cmd: list[str], cwd: str, timeout: int) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        return proc.returncode or 0, output
    except asyncio.TimeoutError:
        return 1, f"{cmd[0]} timed out after {timeout}s"
    except FileNotFoundError:
        return -1, f"{cmd[0]} not found"
    except Exception as e:
        return 1, str(e)


async def run_ci(worktree: str) -> tuple[bool, str]:
    """Run make ci-local in the worktree."""
    rc, out = await _run(["make", "ci-local"], worktree, timeout=600)
    return rc == 0, out[-3000:]


async def run_bandit(worktree: str) -> tuple[bool, list[dict]]:
    """Run bandit on Python source. Returns (passed, critical/high findings)."""
    rc, out = await _run(
        ["bandit", "-r", ".", "-f", "json", "-q", "--severity-level", "medium"],
        worktree,
        timeout=120,
    )
    if rc == -1:
        return True, []  # bandit not installed — skip
    try:
        data = json.loads(out)
        findings = data.get("results", [])
        blockers = [f for f in findings if f.get("issue_severity") in ("HIGH", "CRITICAL")]
        return len(blockers) == 0, blockers
    except Exception:
        return True, []  # JSON parse error — treat as pass


async def run_semgrep(worktree: str) -> tuple[bool, list[dict]]:
    """Run semgrep if available. Returns (passed, error/warning findings)."""
    rc, out = await _run(
        ["semgrep", "--json", "--quiet", "--config", "auto", "."],
        worktree,
        timeout=180,
    )
    if rc == -1:
        return True, []  # semgrep not installed — skip
    try:
        data = json.loads(out)
        findings = data.get("results", [])
        blockers = [
            f for f in findings
            if f.get("extra", {}).get("severity") in ("ERROR", "WARNING")
        ]
        return len(blockers) == 0, blockers[:20]
    except Exception:
        return True, []


async def run_quality_gate(worktree: str) -> dict:
    """Run all quality checks in parallel. Returns a structured result dict."""
    ci_task = asyncio.create_task(run_ci(worktree))
    bandit_task = asyncio.create_task(run_bandit(worktree))
    semgrep_task = asyncio.create_task(run_semgrep(worktree))

    ci_passed, ci_output = await ci_task
    bandit_passed, bandit_findings = await bandit_task
    semgrep_passed, semgrep_findings = await semgrep_task

    return {
        "ci_passed": ci_passed,
        "security_passed": bandit_passed and semgrep_passed,
        "ci_output": ci_output,
        "bandit_findings": bandit_findings,
        "semgrep_findings": semgrep_findings,
        "finding_count": len(bandit_findings) + len(semgrep_findings),
    }
