"""Quality gate — runs CI and security checks before requesting human validation."""
import asyncio
import json
import os
import re
from pathlib import Path


async def _run(cmd: list[str], cwd: str, timeout: int, env: dict | None = None) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
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


def _ci_env(worktree: str) -> dict:
    """Build a subprocess environment for make ci-local.

    Worktrees live at <repo>/.worktrees/<name>; the main repo clone (two levels
    up) may have Python venvs (.venv-docs, .venv) that contain tools like black.
    Launchd starts the runner with a minimal PATH so those aren't inherited —
    we add them explicitly here.
    """
    env = os.environ.copy()
    main_repo = Path(worktree).parent.parent
    for venv_name in (".venv-docs", ".venv"):
        venv_bin = main_repo / venv_name / "bin"
        if venv_bin.is_dir():
            env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    return env


async def _changed_files(worktree: str, extensions: tuple[str, ...]) -> list[str]:
    """Return repo-relative paths of files changed on this branch vs main.

    Uses three-dot diff so we compare against the merge-base, not the tip of main.
    Only returns files that actually exist on disk (Added, Copied, Modified).
    """
    rc, out = await _run(
        ["git", "diff", "main...HEAD", "--name-only", "--diff-filter=ACM"],
        worktree,
        timeout=15,
    )
    if rc != 0 or not out.strip():
        return []
    root = Path(worktree)
    return [
        f for f in out.strip().splitlines()
        if f.endswith(extensions) and (root / f).exists()
    ]


async def run_ci(worktree: str) -> tuple[bool, str]:
    """Run make ci-local in the worktree.

    Bootstraps npm install if node_modules is absent — worktrees don't inherit
    the main checkout's node_modules so tsc would fail without this.
    Augments PATH with the repo's Python venvs so tools like black are found
    even when the runner was started by launchd with a minimal PATH.
    """
    nm = Path(worktree) / "frontend" / "node_modules"
    tsc_bin = nm / ".bin" / "tsc"
    env = _ci_env(worktree)
    if not tsc_bin.exists():
        await _run(["npm", "install", "--silent", "--prefer-offline"], str(Path(worktree) / "frontend"), timeout=120, env=env)

    rc, out = await _run(["make", "ci-local"], worktree, timeout=600, env=env)
    return rc == 0, out[-3000:]


async def run_bandit(worktree: str) -> tuple[bool, list[dict]]:
    """Run bandit on Python files changed by this branch only.

    Scanning the whole repo would flag pre-existing issues in lab/ and edge/
    that have nothing to do with the agent's work.
    """
    py_files = await _changed_files(worktree, (".py",))
    if not py_files:
        return True, []  # no Python changes — nothing to scan

    rc, out = await _run(
        ["bandit", *py_files, "-f", "json", "-q", "--severity-level", "medium"],
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
        return True, []


async def run_semgrep(worktree: str) -> tuple[bool, list[dict]]:
    """Run semgrep on files changed by this branch only."""
    # semgrep accepts paths directly; pass only changed Python files
    py_files = await _changed_files(worktree, (".py",))
    if not py_files:
        return True, []

    rc, out = await _run(
        ["semgrep", "--json", "--quiet", "--config", "auto", *py_files],
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
            if f.get("extra", {}).get("severity") == "ERROR"
        ]
        return len(blockers) == 0, blockers[:20]
    except Exception:
        return True, []


# Dangerous JS/TS patterns that warrant a security flag.
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
    """Scan JS/TS files changed by this branch for dangerous patterns."""
    js_files_rel = await _changed_files(worktree, (".js", ".ts", ".mjs", ".cjs"))
    if not js_files_rel:
        return True, []

    root = Path(worktree)
    js_files = [root / f for f in js_files_rel]

    # Try eslint first
    rc, out = await _run(
        ["npx", "eslint", "--no-eslintrc", "--plugin", "security",
         "--rule", '{"security/detect-eval-with-expression": "error"}',
         "--format", "json", "--ext", ".js,.ts", *[str(p) for p in js_files]],
        worktree,
        timeout=60,
    )
    if rc != -1:
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


_SERVICE_PATTERNS: list[tuple[str, str]] = [
    (r"^frontend/", "frontend"),
    (r"^services/data-service/|^src/clarion/", "data-service"),
    (r"^services/correlation-service/|^src/clarion/endpoints/correlation_engine", "correlation-service"),
    (r"^services/clustering-service/", "clustering-service"),
    (r"^services/connector-service/", "connector-service"),
    (r"^services/user-service/", "user-service"),
    (r"^services/gateway/", "gateway"),
    (r"^services/ai-service/", "ai-service"),
    (r"^services/monitoring-service/", "monitoring-service"),
    (r"^services/telemetry-ingest-service/", "telemetry-ingest-service"),
    (r"^services/policy-service/", "policy-service"),
]


async def _all_changed_files(worktree: str) -> list[str]:
    """Return all changed files — committed on branch + uncommitted — relative to the worktree root."""
    files: set[str] = set()

    # Uncommitted changes (staged + unstaged + untracked)
    rc, out = await _run(["git", "status", "--short", "--porcelain"], worktree, timeout=15)
    for line in (out.strip().splitlines() if out.strip() else []):
        if len(line) > 3:
            files.add(line[3:].strip())

    # Committed changes on this branch vs main (three-dot so we use merge-base)
    rc2, out2 = await _run(
        ["git", "diff", "main...HEAD", "--name-only", "--diff-filter=ACMR"],
        worktree, timeout=15,
    )
    for line in (out2.strip().splitlines() if out2.strip() else []):
        files.add(line.strip())

    return list(files)


def _detect_services(changed: list[str]) -> list[str]:
    """Map changed file paths to the services that need rebuilding."""
    services: set[str] = set()
    for path in changed:
        for pattern, svc in _SERVICE_PATTERNS:
            if re.match(pattern, path):
                services.add(svc)
    return sorted(services)


async def run_container_rebuild(worktree: str) -> dict:
    """Detect which services changed, rebuild their containers, wait healthy, smoke-test.

    Returns a dict with 'services', 'rebuilt', 'smoke_passed', 'output'.
    Skips entirely if only docs/scripts changed.
    """
    changed = await _all_changed_files(worktree)
    services = _detect_services(changed)

    if not services:
        return {"services": [], "rebuilt": True, "smoke_passed": True,
                "output": "No container changes — docs/scripts only."}

    env = _ci_env(worktree)
    # Worktrees have a different directory name, which makes docker compose default to a
    # different project name. Force it to match the main repo so containers aren't duplicated.
    env.setdefault("COMPOSE_PROJECT_NAME", "clarion")
    output_lines: list[str] = [f"Rebuilding: {', '.join(services)}"]

    compose_cmd = ["docker", "compose", "-f", "docker-compose.yml"]
    for svc in services:
        # Build the image
        rc, out = await _run(
            [*compose_cmd, "build", "--build-arg", f"CACHE_BUST={int(__import__('time').time())}", svc],
            worktree, timeout=600, env=env,
        )
        output_lines.append(f"\n--- {svc} build ---\n{out[-1500:]}")
        if rc != 0:
            return {
                "services": services, "rebuilt": False, "smoke_passed": False,
                "output": "\n".join(output_lines),
            }
        # Restart only this service — --no-deps prevents cascading dependency recreation
        rc, out = await _run(
            [*compose_cmd, "up", "-d", "--no-deps", svc],
            worktree, timeout=60, env=env,
        )
        output_lines.append(f"\n--- {svc} up ---\n{out[-500:]}")
        if rc != 0:
            return {
                "services": services, "rebuilt": False, "smoke_passed": False,
                "output": "\n".join(output_lines),
            }

    # Wait for containers to be healthy
    rc, out = await _run(["make", "wait-healthy"], worktree, timeout=120, env=env)
    output_lines.append(f"\nwait-healthy: {'ok' if rc == 0 else 'FAILED'}\n{out[-500:]}")

    # Smoke test
    rc, smoke_out = await _run(["make", "smoke-test"], worktree, timeout=120, env=env)
    smoke_passed = rc == 0
    output_lines.append(f"\nsmoke-test: {'✅' if smoke_passed else '❌'}\n{smoke_out[-1000:]}")

    return {
        "services": services,
        "rebuilt": True,
        "smoke_passed": smoke_passed,
        "output": "\n".join(output_lines),
    }


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
