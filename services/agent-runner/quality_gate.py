"""Quality gate — runs CI and security checks before requesting human validation."""
import asyncio
import json
import os
import re
from pathlib import Path

from proc import communicate as _communicate


async def _run(cmd: list[str], cwd: str, timeout: int, env: dict | None = None) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        stdout, _ = await _communicate(proc, timeout=timeout)
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
    we add them explicitly here, including NVM-managed node/npm.
    """
    env = os.environ.copy()
    main_repo = Path(worktree).parent.parent
    for venv_name in (".venv-docs", ".venv"):
        venv_bin = main_repo / venv_name / "bin"
        if venv_bin.is_dir():
            env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"

    # Add NVM-managed node/npm — launchd doesn't source .nvm/nvm.sh so these
    # aren't in the inherited PATH. Scan ~/.nvm/versions/node/ for installed versions.
    nvm_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_dir.is_dir():
        for node_ver in sorted(nvm_dir.iterdir(), reverse=True):
            node_bin = node_ver / "bin"
            if node_bin.is_dir() and (node_bin / "node").exists():
                env["PATH"] = f"{node_bin}:{env.get('PATH', '')}"
                break  # use the latest installed version

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


_CI_LOCK_PATH = Path("/tmp/factory-ci-local.lock")
_CI_LOCK_TIMEOUT = 2700  # wait at least as long as one ci-local run
# 1800s was already 2x the worst historically observed `make ci-local` run
# (frontend tsc under load) and still wasn't enough: WO-443 hit exactly this
# wall clock twice in a row (both attempts logged "make timed out after
# 1800s") during a period of genuine host contention — several agents/
# worktrees rebuilding containers concurrently pushed load average past 45.
# Bumping for headroom against that recurring condition. The real fix is
# concurrency control on how many heavy builds run at once (tracked
# separately, see occupancy.py) — this alone won't help if contention keeps
# growing unbounded, it just buys more room before the next WO hits it too.
_CI_RUN_TIMEOUT = 2700
_COMPOSE_LOCK_TIMEOUT = 600  # seconds to wait for a per-service compose lock
# scripts/wait_healthy.sh's own retry loop already waits up to 300s (its default
# timeout) before giving up — under real host load with several agents rebuilding
# containers concurrently this has been observed taking 143s+. A shorter external
# wrapper timeout kills the subprocess mid-retry and reports a false "CI tests
# failed" before wait_healthy.sh's own timeout ever gets to fire, which was the
# root cause behind several WOs (496, 497, 500, 443, 513, 495) parking on a
# spurious gate failure despite the underlying code being correct.
_WAIT_HEALTHY_TIMEOUT = 330  # wait_healthy.sh's 300s default + buffer
_SMOKE_TEST_TIMEOUT = 240  # ~60s gateway wait + up to a dozen 10s per-check timeouts under load


async def _with_compose_lock(svc: str, timeout: int = _COMPOSE_LOCK_TIMEOUT):
    """Acquire a per-service lock before touching that service's shared container.

    All worktrees share COMPOSE_PROJECT_NAME=clarion (see run_container_rebuild)
    so containers aren't duplicated across runners — but that means two WOs
    quality-gating the same service concurrently race on `docker compose build`
    + `up -d --no-deps`. One run's `up` can recreate/remove the container out
    from under another run's already-resolved container ID mid-attach, failing
    with "No such container" even though the build itself succeeded. Bit
    WO-433 and WO-444 for real. Same stale-PID self-heal as the CI lock below —
    a lock left by a killed process shouldn't block forever.
    """
    lock_path = Path(f"/tmp/factory-compose-{svc}.lock")
    waited = 0
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock_path
        except FileExistsError:
            try:
                holder_pid = int(lock_path.read_text().strip())
                os.kill(holder_pid, 0)
            except (ValueError, OSError, ProcessLookupError):
                try:
                    lock_path.unlink(missing_ok=True)
                except Exception:
                    pass
                continue
            if waited >= timeout:
                return None  # give up waiting — caller proceeds unlocked rather than hanging forever
            await asyncio.sleep(5)
            waited += 5


async def run_ci(worktree: str) -> tuple[bool, str]:
    """Run make ci-local in the worktree.

    Bootstraps npm install if node_modules is absent — worktrees don't inherit
    the main checkout's node_modules so tsc would fail without this.
    Augments PATH with the repo's Python venvs so tools like black are found
    even when the runner was started by launchd with a minimal PATH.

    Uses a file lock so that multiple parallel runners don't run `make ci-local`
    simultaneously — overlapping Vite builds and pytest suites cause timeouts.
    """
    nm = Path(worktree) / "frontend" / "node_modules"
    tsc_bin = nm / ".bin" / "tsc"
    env = _ci_env(worktree)
    if not tsc_bin.exists():
        await _run(["npm", "install", "--silent", "--prefer-offline"], str(Path(worktree) / "frontend"), timeout=120, env=env)

    # Auto-fix lint before CI — black and ruff are deterministic formatters;
    # auto-fixing prevents formatting-only failures from killing correct implementations.
    for fmt_dir in ["src", "services", "tests"]:
        if (Path(worktree) / fmt_dir).is_dir():
            await _run(["black", "--quiet", fmt_dir], worktree, timeout=60, env=env)
            await _run(["ruff", "check", "--fix", "--quiet", fmt_dir], worktree, timeout=60, env=env)

    # Serialize CI runs across all runner processes via a simple lock file.
    waited = 0
    while True:
        try:
            fd = os.open(str(_CI_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break  # lock acquired
        except FileExistsError:
            # The lock only ever gets released by the finally: block below —
            # a process killed mid-run (daemon restart, crash, kill -9) skips
            # that cleanup and leaves the lock orphaned forever, blocking
            # every future CI run until a human notices and deletes it by
            # hand. This bit for real: a stale lock from a killed daemon sat
            # for ~14 hours, silently failing CI on every WO that touched it.
            # Before waiting, check whether the PID that holds it is even
            # alive — if not, the lock is abandoned and safe to reclaim now.
            try:
                holder_pid = int(_CI_LOCK_PATH.read_text().strip())
                os.kill(holder_pid, 0)  # raises if the process doesn't exist
            except (ValueError, OSError, ProcessLookupError):
                try:
                    _CI_LOCK_PATH.unlink(missing_ok=True)
                except Exception:
                    pass
                continue  # retry acquisition immediately
            if waited >= _CI_LOCK_TIMEOUT:
                return False, "CI lock wait timed out — another CI run held the lock too long"
            await asyncio.sleep(5)
            waited += 5

    try:
        rc, out = await _run(["make", "ci-local"], worktree, timeout=_CI_RUN_TIMEOUT, env=env)
    finally:
        try:
            _CI_LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    return rc == 0, out[-3000:]


async def run_bandit(worktree: str) -> tuple[bool, list[dict], str | None]:
    """Run bandit on Python files changed by this branch only.

    Scanning the whole repo would flag pre-existing issues in lab/ and edge/
    that have nothing to do with the agent's work.

    Third return value is a non-None error string when bandit's output couldn't
    be parsed — kept non-blocking (audit F-04: a scanner crash isn't evidence of
    a real vulnerability, so failing the WO over it would be the wrong default),
    but the caller surfaces this to a human instead of it being indistinguishable
    from "bandit ran clean." Previously this returned (True, []) either way —
    a real scan with zero findings and a scan that never actually completed
    looked identical.
    """
    py_files = await _changed_files(worktree, (".py",))
    if not py_files:
        return True, [], None  # no Python changes — nothing to scan

    rc, out = await _run(
        ["bandit", *py_files, "-f", "json", "-q", "--severity-level", "medium"],
        worktree,
        timeout=120,
    )
    if rc == -1:
        return True, [], None  # bandit not installed — skip
    try:
        data = json.loads(out)
        findings = data.get("results", [])
        blockers = [f for f in findings if f.get("issue_severity") in ("HIGH", "CRITICAL")]
        return len(blockers) == 0, blockers, None
    except Exception as e:
        return True, [], f"bandit output could not be parsed ({e}) — scan may not have completed: {out[-300:]}"


async def run_semgrep(worktree: str) -> tuple[bool, list[dict], str | None]:
    """Run semgrep on files changed by this branch only. See run_bandit for the
    third return value's meaning."""
    # semgrep accepts paths directly; pass only changed Python files
    py_files = await _changed_files(worktree, (".py",))
    if not py_files:
        return True, [], None

    rc, out = await _run(
        ["semgrep", "--json", "--quiet", "--config", "auto", *py_files],
        worktree,
        timeout=180,
    )
    if rc == -1:
        return True, [], None  # semgrep not installed — skip
    try:
        data = json.loads(out)
        findings = data.get("results", [])
        blockers = [
            f for f in findings
            if f.get("extra", {}).get("severity") == "ERROR"
        ]
        return len(blockers) == 0, blockers[:20], None
    except Exception as e:
        return True, [], f"semgrep output could not be parsed ({e}) — scan may not have completed: {out[-300:]}"


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


# Paths that are auto-managed by the doc-writer agent and are left as
# uncommitted noise in every worktree. Exclude them from changed-file detection
# so they don't trigger container rebuilds or pollute validation summaries.
_WORKTREE_NOISE_PREFIXES = ("frontend/public/help/",)


async def _all_changed_files(worktree: str) -> list[str]:
    """Return all changed files — committed on branch + uncommitted — relative to the worktree root.

    Excludes auto-generated help docs that the doc-writer agent leaves unstaged
    in every worktree but never intends to commit as part of WO work.
    """
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

    # Strip noise paths — help docs are managed by the doc-writer and should
    # never drive container rebuilds or appear in validation summaries.
    files = {f for f in files if not any(f.startswith(p) for p in _WORKTREE_NOISE_PREFIXES)}

    return list(files)


def _detect_services(changed: list[str]) -> list[str]:
    """Map changed file paths to the services that need rebuilding."""
    services: set[str] = set()
    for path in changed:
        for pattern, svc in _SERVICE_PATTERNS:
            if re.match(pattern, path):
                services.add(svc)
    return sorted(services)


# ── Improvement #4: PR size gate ─────────────────────────────────────────────

_MAX_FILES_CHANGED = 30
_MAX_LINES_CHANGED = 800


async def run_pr_size_gate(worktree: str) -> tuple[bool, str]:
    """Reject PRs that are too large to review safely in one agent pass.

    Large PRs have a higher defect rate and are harder for reviewers to catch
    all issues in. Agents should split work into focused, reviewable units.
    """
    rc, out = await _run(
        ["git", "diff", "main...HEAD", "--stat"],
        worktree, timeout=15,
    )
    if rc != 0 or not out.strip():
        return True, "could not determine PR size — skipping gate"

    summary = out.strip().splitlines()[-1]
    files_m = re.search(r"(\d+) files? changed", summary)
    ins_m   = re.search(r"(\d+) insertion",       summary)
    del_m   = re.search(r"(\d+) deletion",        summary)

    files_changed = int(files_m.group(1)) if files_m else 0
    lines_changed = (int(ins_m.group(1)) if ins_m else 0) + (int(del_m.group(1)) if del_m else 0)

    if files_changed > _MAX_FILES_CHANGED or lines_changed > _MAX_LINES_CHANGED:
        return False, (
            f"PR too large: {files_changed} files changed, {lines_changed} lines changed. "
            f"Maximum: {_MAX_FILES_CHANGED} files / {_MAX_LINES_CHANGED} lines. "
            f"Split this WO into smaller, focused work orders and implement one piece at a time."
        )
    return True, f"PR size OK: {files_changed} files, {lines_changed} lines"


# ── Improvement #2: Browser smoke test ───────────────────────────────────────

async def run_browser_smoke(worktree: str) -> tuple[bool, str]:
    """Verify the frontend loads without a white screen after a rebuild.

    Only runs when frontend/src/ files changed. Uses two checks:
    1. curl to confirm nginx returns HTML with the React root element
    2. node --check on the built JS bundle to catch syntax errors in emitted code
    """
    changed = await _all_changed_files(worktree)
    if not any(f.startswith("frontend/src/") for f in changed):
        return True, "no frontend/src changes — browser smoke skipped"

    # Check 1: frontend container serves the app shell
    rc, html = await _run(
        ["curl", "-sk", "--max-time", "10", "https://localhost/"],
        worktree, timeout=15,
    )
    if rc != 0:
        return False, "frontend container did not respond to https://localhost/"
    if '<div id="root">' not in html:
        return False, (
            "frontend returned HTML but <div id=\"root\"> is missing — "
            "likely a build error or nginx misconfiguration"
        )

    # Check 2: node syntax check on the built entry-point bundle
    dist = Path(worktree) / "frontend" / "dist" / "assets"
    if dist.exists():
        index_files = sorted(dist.glob("index-*.js"))
        if index_files:
            rc2, out2 = await _run(
                ["node", "--check", str(index_files[0])],
                worktree, timeout=30,
            )
            if rc2 != 0:
                return False, f"Built JS bundle failed syntax check:\n{out2[:800]}"

    return True, "browser smoke passed: app shell loads, bundle syntax OK"


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
        # All worktrees share the same container per service (see COMPOSE_PROJECT_NAME
        # above) — serialize build+up for this specific service so a concurrent WO
        # rebuilding the same service can't recreate the container out from under us.
        lock_path = await _with_compose_lock(svc)
        try:
            # Build the image — use cached base images (--pull=false) to avoid Docker Hub
            # rate-limit timeouts when multiple runners are building simultaneously.
            # Retry up to 3 times: BuildKit metadata resolver intermittently fails with
            # DeadlineExceeded even with --pull=false when Docker Hub is slow.
            build_rc, build_out = 1, ""
            for attempt in range(1, 4):
                build_rc, build_out = await _run(
                    [*compose_cmd, "build", "--pull=false", "--build-arg", f"CACHE_BUST={int(__import__('time').time())}", svc],
                    worktree, timeout=1200, env=env,
                )
                if build_rc == 0:
                    break
                if "DeadlineExceeded" not in build_out or attempt == 3:
                    break
                await asyncio.sleep(10 * attempt)  # 10s, 20s back-off before retry
            rc, out = build_rc, build_out
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
        finally:
            if lock_path is not None:
                try:
                    lock_path.unlink(missing_ok=True)
                except Exception:
                    pass

    # Wait for containers to be healthy
    rc, out = await _run(["make", "wait-healthy"], worktree, timeout=_WAIT_HEALTHY_TIMEOUT, env=env)
    output_lines.append(f"\nwait-healthy: {'ok' if rc == 0 else 'FAILED'}\n{out[-500:]}")

    # Smoke test
    rc, smoke_out = await _run(["make", "smoke-test"], worktree, timeout=_SMOKE_TEST_TIMEOUT, env=env)
    smoke_passed = rc == 0
    output_lines.append(f"\nsmoke-test: {'✅' if smoke_passed else '❌'}\n{smoke_out[-1000:]}")

    return {
        "services": services,
        "rebuilt": True,
        "smoke_passed": smoke_passed,
        "output": "\n".join(output_lines),
    }


async def run_quality_gate(worktree: str) -> dict:
    """Run all quality checks. Returns a structured result dict.

    Order:
      1. PR size gate (fast, fails-fast before expensive checks)
      2. CI + security scans in parallel
      3. Browser smoke (only when frontend/src changed, after CI so dist/ exists)
    """
    # 1. PR size gate — fast check before investing in CI
    size_ok, size_msg = await run_pr_size_gate(worktree)
    if not size_ok:
        return {
            "ci_passed": False,
            "security_passed": False,
            "ci_output": f"PR SIZE GATE FAILED: {size_msg}",
            "bandit_findings": [],
            "semgrep_findings": [],
            "js_findings": [],
            "finding_count": 0,
            "pr_size_msg": size_msg,
            "browser_smoke_passed": True,
            "browser_smoke_msg": "skipped",
            "scan_errors": [],
        }

    # 2. CI + security in parallel
    ci_task      = asyncio.create_task(run_ci(worktree))
    bandit_task  = asyncio.create_task(run_bandit(worktree))
    semgrep_task = asyncio.create_task(run_semgrep(worktree))
    js_task      = asyncio.create_task(run_js_security(worktree))

    ci_passed, ci_output              = await ci_task
    bandit_passed, bandit_findings, bandit_error = await bandit_task
    semgrep_passed, semgrep_findings, semgrep_error = await semgrep_task
    js_passed, js_findings            = await js_task

    # 3. Browser smoke — only when CI passes (dist/ must exist) and frontend changed
    browser_passed, browser_msg = True, "skipped"
    if ci_passed:
        browser_passed, browser_msg = await run_browser_smoke(worktree)

    scan_errors = [e for e in (bandit_error, semgrep_error) if e]

    return {
        "ci_passed": ci_passed and browser_passed,
        "security_passed": bandit_passed and semgrep_passed and js_passed,
        "ci_output": ci_output if ci_passed else ci_output,
        "bandit_findings": bandit_findings,
        "semgrep_findings": semgrep_findings,
        "js_findings": js_findings,
        "finding_count": len(bandit_findings) + len(semgrep_findings) + len(js_findings),
        "pr_size_msg": size_msg,
        "browser_smoke_passed": browser_passed,
        "browser_smoke_msg": browser_msg,
        # Non-blocking by design (F-04) — a scanner crash isn't a finding, but it
        # also shouldn't look identical to a clean scan. Caller surfaces this.
        "scan_errors": scan_errors,
    }
