#!/usr/bin/env python3
"""
pre_pr_check.py — Static pre-PR checks (no API call, no cost).

Catches the most common issues that the Claude AI reviewer flags, so agents
fix them before pushing rather than after seeing a "Needs attention" verdict.
Each review→fix→re-review cycle costs money and time; this catches the
obvious issues before the first push.

Run automatically as part of `make ci-local`. Also available standalone:
    python3 scripts/pre_pr_check.py

Checks the git diff of HEAD vs origin/main. Clean working tree recommended.

Extending with project-specific checks:
    Create scripts/pre_pr_checks_project.py and define:
        def project_checks(diff: str) -> list[CheckResult]: ...
    The runner imports it automatically if the file exists.

Exit codes:
    0 — all checks pass (safe to push)
    1 — one or more error-level checks failed (fix before pushing)
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_diff() -> str:
    """Return the git diff of HEAD vs origin/main (falls back to HEAD~1)."""
    result = subprocess.run(
        ["git", "diff", "origin/main...HEAD", "--unified=3"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        result = subprocess.run(
            ["git", "diff", "HEAD~1...HEAD", "--unified=3"],
            capture_output=True, text=True,
        )
    return result.stdout


def added_lines(diff: str, filename_pattern: str) -> list[tuple[str, int, str]]:
    """Return (filename, lineno, line) for added lines in files matching pattern."""
    results: list[tuple[str, int, str]] = []
    current_file = ""
    lineno = 0
    pat = re.compile(filename_pattern)
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            current_file = line.split(" b/")[-1]
        elif line.startswith("@@ "):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            if pat.search(current_file):
                results.append((current_file, lineno, line[1:]))
            lineno += 1
        elif not line.startswith("-"):
            lineno += 1
    return results


def new_files_in_diff(diff: str, filename_pattern: str) -> list[str]:
    """Return filenames of newly created files matching pattern."""
    files = []
    pat = re.compile(filename_pattern)
    current = ""
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            current = line.split(" b/")[-1]
        elif line.startswith("new file mode") and pat.search(current):
            files.append(current)
    return files


@dataclass
class Issue:
    check: str
    file: str
    line: int
    detail: str
    severity: str = "error"  # "error" blocks push; "warning" is advisory


@dataclass
class CheckResult:
    name: str
    issues: list[Issue] = field(default_factory=list)

    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


# ── Universal checks (apply to every project) ─────────────────────────────────

def check_hardcoded_secrets(diff: str) -> CheckResult:
    """No obvious hardcoded secrets in added lines."""
    result = CheckResult("No hardcoded secrets")
    patterns = [
        (re.compile(r'(?i)(api_key|secret|password|token|private_key)\s*=\s*["\'][^"\']{8,}["\']'), "possible hardcoded secret — use environment variable or secrets manager"),
        (re.compile(r'sk-ant-[A-Za-z0-9_-]{20,}'), "Anthropic API key in source"),
        (re.compile(r'ghp_[A-Za-z0-9]{36}'), "GitHub personal access token in source"),
        (re.compile(r'AKIA[0-9A-Z]{16}'), "AWS access key ID in source"),
    ]
    skip = re.compile(r'\.(md|txt|example|sample|env\.example)$|fixtures/|test.*data/|__snapshots__/')
    for fname, lineno, content in added_lines(diff, r".*"):
        if skip.search(fname):
            continue
        stripped = content.strip()
        if stripped.startswith(("#", "//", "*", "<!--")):
            continue
        for pat, msg in patterns:
            if pat.search(content):
                result.issues.append(Issue("No hardcoded secrets", fname, lineno, msg))
    return result


def check_sql_injection(diff: str) -> CheckResult:
    """SQL queries must use parameterized placeholders, not f-strings or concatenation."""
    result = CheckResult("No SQL injection")
    patterns = [
        (re.compile(r'execute\s*\(\s*f["\'].*\{'), "f-string in SQL query — use %s or $1 placeholders"),
        (re.compile(r'execute\s*\(\s*["\'].*\+\s*\w'), "string concatenation in SQL query — use parameterized query"),
    ]
    for fname, lineno, content in added_lines(diff, r"\.py$"):
        for pat, msg in patterns:
            if pat.search(content):
                result.issues.append(Issue("No SQL injection", fname, lineno, msg))
    return result


def check_bare_except(diff: str) -> CheckResult:
    """No bare except: or except Exception: pass — errors must be logged or re-raised."""
    result = CheckResult("No bare except / swallowed errors")

    file_lines: dict[str, list[tuple[int, str]]] = {}
    for fname, lineno, content in added_lines(diff, r"\.py$"):
        file_lines.setdefault(fname, []).append((lineno, content))

    bare_except = re.compile(r'^\s*except\s*:\s*$')
    except_broad = re.compile(r'^\s*except\s+(Exception|BaseException)\s*:\s*$')
    pass_body = re.compile(r'^\s*pass\s*$')

    for fname, lines in file_lines.items():
        for i, (lineno, content) in enumerate(lines):
            if bare_except.search(content):
                result.issues.append(Issue(
                    "No bare except", fname, lineno,
                    "bare except: catches SystemExit and KeyboardInterrupt — use a specific exception type",
                ))
            elif except_broad.search(content):
                # Only flag if the body is just 'pass' — return/raise/log are acceptable
                next_lines = [c for _, c in lines[i+1:i+3]]
                if next_lines and pass_body.search(next_lines[0]):
                    result.issues.append(Issue(
                        "No bare except", fname, lineno,
                        "except Exception: pass silently swallows all errors — log or re-raise",
                    ))
            elif re.search(r'^\s*except.*:\s*pass\s*$', content):
                result.issues.append(Issue(
                    "No bare except", fname, lineno,
                    "except: pass silently swallows the error",
                ))
    return result


def check_shell_true_bypass(diff: str) -> CheckResult:
    """No || true in shell scripts, CI workflows, or Makefiles."""
    result = CheckResult("No shell || true bypasses")
    pattern = re.compile(r'\|\|\s*true\b')
    for fname, lineno, content in added_lines(diff, r"\.(sh|yml|yaml)$|Makefile"):
        if content.strip().startswith("#"):
            continue
        if pattern.search(content):
            result.issues.append(Issue(
                "No shell || true bypasses", fname, lineno,
                "|| true silences failures — broken steps become invisible in CI",
            ))
    return result


def check_typescript_any(diff: str) -> CheckResult:
    """Avoid 'as any' and ': any' type annotations in TypeScript."""
    result = CheckResult("TypeScript type safety")
    patterns = [
        (re.compile(r'\bas\s+any\b'), "as any cast removes compile-time type safety"),
        (re.compile(r':\s*any\b'), ": any annotation — use a specific type or unknown"),
    ]
    for fname, lineno, content in added_lines(diff, r"\.(ts|tsx)$"):
        if fname.endswith(".d.ts"):
            continue
        stripped = content.strip()
        if stripped.startswith(("//", "*")):
            continue
        for pat, msg in patterns:
            if pat.search(content):
                result.issues.append(Issue(
                    "TypeScript type safety", fname, lineno, msg, severity="warning",
                ))
    return result


def check_missing_error_handling(diff: str) -> CheckResult:
    """External API calls and file I/O in new code should handle failures."""
    result = CheckResult("Error handling at boundaries")
    # Flag async fetch/axios calls or open() calls that appear without try/except nearby
    # This is heuristic — just flags bare awaits on network calls with no surrounding try
    patterns = [
        re.compile(r'^\s*await\s+fetch\s*\('),
        re.compile(r'^\s*response\s*=\s*requests\.(get|post|put|delete|patch)\s*\('),
    ]
    file_lines: dict[str, list[tuple[int, str]]] = {}
    for fname, lineno, content in added_lines(diff, r"\.(py|ts|tsx)$"):
        file_lines.setdefault(fname, []).append((lineno, content))

    for fname, lines in file_lines.items():
        for i, (lineno, content) in enumerate(lines):
            for pat in patterns:
                if pat.search(content):
                    # Check surrounding 6 lines for try/catch
                    window_start = max(0, i - 3)
                    window = [c for _, c in lines[window_start:i+4]]
                    window_text = "\n".join(window)
                    if "try" not in window_text and "catch" not in window_text and "except" not in window_text:
                        result.issues.append(Issue(
                            "Error handling at boundaries", fname, lineno,
                            "external API call without visible try/except or try/catch — handle network failures",
                            severity="warning",
                        ))
    return result


# ── Runner ────────────────────────────────────────────────────────────────────

def main() -> int:
    diff = get_diff()
    if not diff.strip():
        print("pre-pr-check: no diff vs origin/main — nothing to check")
        return 0

    checks: list[CheckResult] = [
        check_hardcoded_secrets(diff),
        check_sql_injection(diff),
        check_bare_except(diff),
        check_shell_true_bypass(diff),
        check_typescript_any(diff),
        check_missing_error_handling(diff),
    ]

    # Project-specific checks (optional — add scripts/pre_pr_checks_project.py)
    try:
        import importlib.util, os
        project_checks_path = os.path.join(os.path.dirname(__file__), "pre_pr_checks_project.py")
        if os.path.exists(project_checks_path):
            spec = importlib.util.spec_from_file_location("pre_pr_checks_project", project_checks_path)
            mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            checks.extend(mod.project_checks(diff))
    except Exception as e:
        print(f"Warning: could not load pre_pr_checks_project.py: {e}", file=sys.stderr)

    errors   = [i for c in checks for i in c.issues if i.severity == "error"]
    warnings = [i for c in checks for i in c.issues if i.severity == "warning"]

    GREEN  = "\033[32m"
    RED    = "\033[31m"
    YELLOW = "\033[33m"
    BOLD   = "\033[1m"
    NC     = "\033[0m"

    print(f"\n{BOLD}Pre-PR Static Check{NC}")
    print("=" * 50)

    for check in checks:
        errs  = [i for i in check.issues if i.severity == "error"]
        warns = [i for i in check.issues if i.severity == "warning"]
        if errs:
            symbol = f"{RED}❌{NC}"
        elif warns:
            symbol = f"{YELLOW}⚠️ {NC}"
        else:
            symbol = f"{GREEN}✅{NC}"
        print(f"  {symbol}  {check.name}")
        for issue in check.issues:
            loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
            color = RED if issue.severity == "error" else YELLOW
            print(f"     {color}→ {loc}: {issue.detail}{NC}")

    print()
    if errors:
        print(f"{RED}{BOLD}❌ {len(errors)} error(s) found — fix before pushing.{NC}")
        if warnings:
            print(f"{YELLOW}⚠️  {len(warnings)} warning(s) — review before pushing.{NC}")
        print()
        print("These are the same issues the Claude AI reviewer will flag.")
        print("Fix them now to avoid a review → fix → re-review loop.")
        return 1
    elif warnings:
        print(f"{YELLOW}⚠️  {len(warnings)} warning(s) — review before pushing.{NC}")
        print(f"{GREEN}No blocking errors — safe to push.{NC}")
        return 0
    else:
        print(f"{GREEN}{BOLD}✅ All checks passed — safe to push.{NC}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
