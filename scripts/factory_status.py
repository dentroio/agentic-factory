#!/usr/bin/env python3
"""
Factory status check — shows what's configured and what's missing.

Run:
    python3 scripts/factory_status.py

Exit codes:
    0 — all checks pass
    1 — one or more checks failed or are incomplete
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1m"

PASS = f"{GREEN}✅{RESET}"
WARN = f"{YELLOW}⚠️ {RESET}"
FAIL = f"{RED}❌{RESET}"


def run(cmd: str, capture: bool = True) -> tuple[int, str]:
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def check(label: str, ok: bool, warn: bool = False, detail: str = "") -> bool:
    icon = PASS if ok else (WARN if warn else FAIL)
    suffix = f"  {detail}" if detail else ""
    print(f"  {icon} {label}{suffix}")
    return ok


def section(title: str):
    print(f"\n{BOLD}{title}{RESET}")
    print("─" * 50)


def get_repo() -> str | None:
    code, out = run("gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null")
    return out.strip() if code == 0 and out.strip() else None


# ── Checks ────────────────────────────────────────────────────────────────────

def check_project_identity() -> bool:
    section("Project Identity")
    files = ["CLAUDE.md", "AGENTS.md", ".cursor/rules/agent-process.mdc"]
    all_ok = True
    for f in files:
        path = ROOT / f
        if not path.exists():
            check(f, False, detail="file missing")
            all_ok = False
            continue
        content = path.read_text()
        has_placeholder = "{{PROJECT_NAME}}" in content
        ok = check(f, not has_placeholder,
                   warn=False,
                   detail="⚠️  still contains {{PROJECT_NAME}}" if has_placeholder else "")
        if not ok:
            all_ok = False
    return all_ok


def check_makefile() -> bool:
    section("Makefile")
    path = ROOT / "Makefile"
    if not path.exists():
        check("Makefile", False, detail="not found — copy from Makefile.template")
        return False
    content = path.read_text()
    has_placeholder = "{{FILL IN}}" in content or "{{" in content
    return check("Makefile", not has_placeholder,
                 detail="still contains unfilled placeholders" if has_placeholder else "")


def check_ci_workflow() -> bool:
    section("CI Workflow")
    path = ROOT / ".github/workflows/ci.yml"
    if not path.exists():
        check("ci.yml", False, detail="not found — copy from ci.yml.template")
        return False
    content = path.read_text()
    has_placeholder = "{{" in content
    return check("ci.yml", not has_placeholder,
                 detail="still contains unfilled placeholders" if has_placeholder else "")


def check_cd_workflow() -> bool:
    section("CD Workflow")
    path = ROOT / ".github/workflows/deploy.yml"
    if not path.exists():
        check("deploy.yml", False, warn=True,
              detail="not configured (copy from deploy.yml.template when ready)")
        return True  # warn but don't fail — CD is optional until the project is deployed
    content = path.read_text()
    has_placeholder = "{{" in content
    return check("deploy.yml", not has_placeholder,
                 detail="still contains unfilled placeholders" if has_placeholder else "")


def check_secret() -> bool:
    section("GitHub Secrets")
    code, out = run("gh secret list 2>/dev/null")
    if code != 0:
        check("ANTHROPIC_API_KEY", False, warn=True, detail="gh CLI not authenticated or no repo access")
        return True
    has_key = "ANTHROPIC_API_KEY" in out
    return check("ANTHROPIC_API_KEY", has_key,
                 detail="" if has_key else "not set — add in Settings → Secrets → Actions")


def check_labels() -> bool:
    section("GitHub Labels")
    code, out = run("gh label list 2>/dev/null")
    if code != 0:
        check("new-wo label", False, warn=True, detail="gh CLI not authenticated or no repo access")
        return True
    has_label = "new-wo" in out
    fix = 'run: gh label create new-wo --color "#0075ca"' if not has_label else ""
    return check("new-wo label", has_label, detail=fix)


def check_ruleset() -> bool:
    section("Branch Ruleset")
    code, out = run("gh api repos/{owner}/{repo}/rulesets 2>/dev/null")
    if code != 0:
        # Try with explicit repo
        repo = get_repo()
        if repo:
            code, out = run(f"gh api repos/{repo}/rulesets 2>/dev/null")
    if code != 0:
        check("main-protection ruleset", False, warn=True,
              detail="gh CLI not authenticated or no repo access")
        return True
    try:
        rulesets = json.loads(out)
        names = [r.get("name", "") for r in rulesets]
        has_ruleset = "main-protection" in names
        return check("main-protection ruleset", has_ruleset,
                     detail="" if has_ruleset else
                     "not found — create in Settings → Rules → Rulesets")
    except json.JSONDecodeError:
        check("main-protection ruleset", False, warn=True, detail="could not parse API response")
        return True


def check_review_context() -> bool:
    section("AI Review Context")
    path = ROOT / "scripts/review_context.txt"
    if not path.exists():
        check("review_context.txt", False, detail="file missing")
        return False
    content = path.read_text()
    is_placeholder = (
        "Add your project-specific checks here" in content
        or len(content.strip()) < 50
    )
    return check("review_context.txt", not is_placeholder,
                 detail="still contains placeholder text — add real project checks" if is_placeholder else "")


def check_memory() -> bool:
    section("Memory System")
    memory_dir = ROOT / "memory"
    index = memory_dir / "MEMORY.md"

    if not index.exists():
        check("memory/MEMORY.md", False, detail="missing")
        return False

    content = index.read_text()
    is_placeholder = "[Project Overview]" in content or len(content.strip()) < 100

    # Count non-example memory files
    real_files = [
        f for f in memory_dir.rglob("*.md")
        if "examples" not in str(f) and f.name != "MEMORY.md"
    ]

    index_ok = check("memory/MEMORY.md", not is_placeholder,
                     detail="still has placeholder content" if is_placeholder else "")
    files_ok = check(f"memory files ({len(real_files)} found)", len(real_files) > 0,
                     warn=len(real_files) == 0,
                     detail="no project memory files yet — seed with project_overview.md" if not real_files else "")
    return index_ok and files_ok


def check_observability() -> bool:
    section("Observability")
    thresholds_path = ROOT / "scripts/observability_thresholds.json"
    if not thresholds_path.exists():
        check("observability_thresholds.json", False, detail="file missing")
        return False

    # Check for METRICS_ENDPOINT variable
    code, out = run("gh variable list 2>/dev/null")
    if code != 0:
        check("METRICS_ENDPOINT variable", False, warn=True,
              detail="gh CLI not authenticated or no repo access")
        return True

    has_endpoint = "METRICS_ENDPOINT" in out
    return check("METRICS_ENDPOINT variable", has_endpoint,
                 warn=not has_endpoint,
                 detail="" if has_endpoint else
                 "not set — add in Settings → Variables → Actions")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    repo = get_repo()
    name = repo.split("/")[-1] if repo else "this project"

    print(f"\n{BOLD}Factory Status — {name}{RESET}")
    print("=" * 52)

    results = [
        check_project_identity(),
        check_makefile(),
        check_ci_workflow(),
        check_cd_workflow(),
        check_secret(),
        check_labels(),
        check_ruleset(),
        check_review_context(),
        check_memory(),
        check_observability(),
    ]

    passed = sum(results)
    total = len(results)

    print(f"\n{'─' * 52}")
    if passed == total:
        print(f"{GREEN}{BOLD}All {total} checks passed — factory is fully operational.{RESET}")
    else:
        missing = total - passed
        print(f"{YELLOW}{BOLD}{missing} item(s) need attention.{RESET}")
        print(f"Ask the Project Engineer to walk you through them:")
        print(f'  "Read ENGINEER.md and help me finish setting up the factory."\n')

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
