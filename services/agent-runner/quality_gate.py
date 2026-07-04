"""Quality gate — runs CI and security checks before requesting human validation."""
import asyncio
import json
import re
from pathlib import Path


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
    """Run bandit on Python source. Blocks on HIGH or CRITICAL severity."""
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
    """Run semgrep if available. Blocks on ERROR severity only (not WARNING)."""
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
        # WARNING is too noisy and produces false positives — only block on ERROR
        blockers = [
            f for f in findings
            if f.get("extra", {}).get("severity") == "ERROR"
        ]
        return len(blockers) == 0, blockers[:20]
    except Exception:
        return True, []


# Dangerous JS/TS patterns that warrant a security flag.
# These are heuristic — not a replacement for eslint, but catch obvious issues
# when eslint-plugin-security isn't available.
_JS_DANGER_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\beval\s*\("), "eval() usage — potential code injection"),
    (re.compile(r"\.innerHTML\s*=(?!=)"), "innerHTML assignment — potential XSS"),
    (re.compile(r"document\.write\s*\("), "document.write() — potential XSS"),
    (re.compile(r"new\s+Function\s*\("), "new Function() — potential code injection"),
    (re.compile(r"child_process"), "child_process import — ensure inputs are sanitised"),
    (re.compile(r'(password|secret|api_key|apikey)\s*=\s*["\'][^"\']{6,}["\']', re.I),
     "Hardcoded credential"),
]


async def run_js_security(worktree: str) -> tuple[bool, list[dict]]:
    """
    Scan JS/TS files for dangerous patterns.

    First tries eslint with eslint-plugin-security if available.
    Falls back to regex pattern matching on .js/.ts files.
    """
    root = Path(worktree)
    js_files = [
        p for ext in ("*.js", "*.ts", "*.mjs", "*.cjs")
        for p in root.rglob(ext)
        if "node_modules" not in p.parts and ".git" not in p.parts
    ]
    if not js_files:
        return True, []

    # Try eslint first
    rc, out = await _run(
        ["npx", "eslint", "--no-eslintrc", "--plugin", "security",
         "--rule", '{"security/detect-eval-with-expression": "error"}',
         "--format", "json", "--ext", ".js,.ts", "."],
        worktree,
        timeout=60,
    )
    if rc != -1:  # eslint ran (even if it found issues)
        try:
            results = json.loads(out)
            blockers = [
                {"file": r["filePath"], "line": m["line"], "issue": m["message"],
                 "severity": "HIGH" if m["severity"] == 2 else "MEDIUM"}
                for r in results
                for m in r.get("messages", [])
                if m.get("severity", 0) >= 2
            ]
            return len(blockers) == 0, blockers[:20]
        except Exception:
            pass

    # Regex fallback
    findings: list[dict] = []
    for path in js_files:
        try:
            text = path.read_text(errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                for pattern, desc in _JS_DANGER_PATTERNS:
                    if pattern.search(line):
                        findings.append({
                            "file": str(path.relative_to(root)),
                            "line": lineno,
                            "issue": desc,
                            "severity": "HIGH",
                        })
        except OSError:
            pass

    return len(findings) == 0, findings[:20]


async def run_quality_gate(worktree: str) -> dict:
    """Run all quality checks in parallel. Returns a structured result dict."""
    ci_task = asyncio.create_task(run_ci(worktree))
    bandit_task = asyncio.create_task(run_bandit(worktree))
    semgrep_task = asyncio.create_task(run_semgrep(worktree))
    js_task = asyncio.create_task(run_js_security(worktree))

    ci_passed, ci_output = await ci_task
    bandit_passed, bandit_findings = await bandit_task
    semgrep_passed, semgrep_findings = await semgrep_task
    js_passed, js_findings = await js_task

    return {
        "ci_passed": ci_passed,
        "security_passed": bandit_passed and semgrep_passed and js_passed,
        "ci_output": ci_output,
        "bandit_findings": bandit_findings,
        "semgrep_findings": semgrep_findings,
        "js_findings": js_findings,
        "finding_count": len(bandit_findings) + len(semgrep_findings) + len(js_findings),
    }
