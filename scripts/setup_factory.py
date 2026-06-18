#!/usr/bin/env python3
"""
Interactive factory setup wizard.

Walks through every configuration step, executes what it can automatically,
and gives clear instructions for steps that require the GitHub UI.

Run:
    python3 scripts/setup_factory.py          # interactive wizard
    python3 scripts/setup_factory.py --status # same as factory_status.py

State is saved to .factory_setup.json so you can resume if interrupted.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
STATE_FILE = ROOT / ".factory_setup.json"

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"
BOLD = "\033[1m"


def run(cmd: str, check_: bool = False) -> tuple[int, str]:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def ask(prompt: str, default: str = "") -> str:
    default_hint = f" [{default}]" if default else ""
    try:
        val = input(f"{CYAN}{prompt}{default_hint}: {RESET}").strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)


def confirm(prompt: str, default: bool = True) -> bool:
    hint = " [Y/n]" if default else " [y/N]"
    try:
        val = input(f"{CYAN}{prompt}{hint}: {RESET}").strip().lower()
        if not val:
            return default
        return val.startswith("y")
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)


def ok(msg: str):
    print(f"  {GREEN}✅{RESET} {msg}")


def warn(msg: str):
    print(f"  {YELLOW}⚠️ {RESET} {msg}")


def info(msg: str):
    print(f"  {CYAN}ℹ️ {RESET} {msg}")


def step(n: int, title: str):
    print(f"\n{BOLD}Step {n}: {title}{RESET}")
    print("─" * 50)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_repo() -> str | None:
    code, out = run("gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null")
    return out.strip() if code == 0 and out.strip() else None


# ── Setup phases ──────────────────────────────────────────────────────────────

def phase_project_identity(state: dict) -> bool:
    step(1, "Project Identity")

    files_to_update = []
    for f in ["CLAUDE.md", "AGENTS.md", ".cursor/rules/agent-process.mdc",
              "AGENT_PROCESS.md", "README.md"]:
        path = ROOT / f
        if path.exists() and "{{PROJECT_NAME}}" in path.read_text():
            files_to_update.append(path)

    if not files_to_update:
        ok("Project name already set — no placeholders found")
        state["identity"] = True
        return True

    current = state.get("project_name", "")
    name = ask("What is your project name?", current)
    if not name:
        warn("Skipped — project name not set")
        return False

    state["project_name"] = name
    for path in files_to_update:
        content = path.read_text()
        path.write_text(content.replace("{{PROJECT_NAME}}", name))
        ok(f"Updated {path.relative_to(ROOT)}")

    state["identity"] = True
    return True


def phase_makefile(state: dict) -> bool:
    step(2, "Makefile")

    makefile = ROOT / "Makefile"
    if makefile.exists() and "{{FILL IN}}" not in makefile.read_text() and "{{" not in makefile.read_text():
        ok("Makefile already configured")
        state["makefile"] = True
        return True

    if not makefile.exists():
        import shutil
        shutil.copy(ROOT / "Makefile.template", makefile)
        ok("Copied Makefile.template → Makefile")

    content = makefile.read_text()
    placeholders = re.findall(r"\{\{[^}]+\}\}", content)
    unique = list(dict.fromkeys(placeholders))

    if not unique:
        ok("Makefile has no unfilled placeholders")
        state["makefile"] = True
        return True

    info(f"Found {len(unique)} placeholder(s) to fill:")
    for p in unique:
        print(f"    {p}")

    print()
    info("Common patterns:")
    info("  Python:  lint=`ruff check .`  test=`pytest tests/`  build=`pip install -e .`")
    info("  Node:    lint=`npm run lint`   test=`npm test`       build=`npm run build`")
    info("  Go:      lint=`go vet ./...`   test=`go test ./...`  build=`go build ./...`")
    print()

    for placeholder in unique:
        replacement = ask(f"  Value for {placeholder}")
        if replacement:
            content = content.replace(placeholder, replacement)

    makefile.write_text(content)
    ok("Makefile updated")
    state["makefile"] = True
    return True


def phase_ci_workflow(state: dict) -> bool:
    step(3, "CI Workflow")

    ci_path = ROOT / ".github/workflows/ci.yml"
    if ci_path.exists() and "{{" not in ci_path.read_text():
        ok("ci.yml already configured")
        state["ci"] = True
        return True

    if not ci_path.exists():
        import shutil
        shutil.copy(ROOT / ".github/workflows/ci.yml.template", ci_path)
        ok("Copied ci.yml.template → ci.yml")

    content = ci_path.read_text()
    placeholders = re.findall(r"\{\{[^}]+\}\}", content)
    unique = list(dict.fromkeys(placeholders))

    if not unique:
        ok("ci.yml has no unfilled placeholders")
        state["ci"] = True
        return True

    info(f"Found {len(unique)} placeholder(s):")
    for p in unique:
        print(f"    {p}")

    print()
    for placeholder in unique:
        replacement = ask(f"  Value for {placeholder}")
        if replacement:
            content = content.replace(placeholder, replacement)

    ci_path.write_text(content)
    ok("ci.yml configured")
    state["ci"] = True
    return True


def phase_cd_workflow(state: dict) -> bool:
    step(4, "CD Workflow (Continuous Deployment)")

    deploy_path = ROOT / ".github/workflows/deploy.yml"
    if deploy_path.exists() and "{{" not in deploy_path.read_text():
        ok("deploy.yml already configured")
        state["cd"] = True
        return True

    if not confirm("Do you have a deploy process ready to configure?", default=False):
        warn("Skipped — you can set this up later by copying deploy.yml.template → deploy.yml")
        state["cd"] = "deferred"
        return True

    if not deploy_path.exists():
        import shutil
        shutil.copy(ROOT / ".github/workflows/deploy.yml.template", deploy_path)
        ok("Copied deploy.yml.template → deploy.yml")

    content = deploy_path.read_text()
    placeholders = re.findall(r"\{\{[^}]+\}\}", content)
    unique = list(dict.fromkeys(placeholders))

    info(f"Found {len(unique)} placeholder(s):")
    for p in unique:
        print(f"    {p}")

    print()
    info("Examples:")
    info("  Deploy command:  'docker compose pull && docker compose up -d'")
    info("  Health endpoint: 'https://api.yourproject.com/health'")
    info("  Environment:     'production'")
    print()

    for placeholder in unique:
        replacement = ask(f"  Value for {placeholder}")
        if replacement:
            content = content.replace(placeholder, replacement)

    deploy_path.write_text(content)
    ok("deploy.yml configured")
    state["cd"] = True
    return True


def phase_github_secret(state: dict) -> bool:
    step(5, "GitHub Secret — ANTHROPIC_API_KEY")

    code, out = run("gh secret list 2>/dev/null")
    if code == 0 and "ANTHROPIC_API_KEY" in out:
        ok("ANTHROPIC_API_KEY is set")
        state["secret"] = True
        return True

    repo = get_repo()
    print()
    info("ANTHROPIC_API_KEY is required for AI code review, planning agent,")
    info("merge advisor, and observability agent.")
    print()
    if repo:
        info(f"Go to: https://github.com/{repo}/settings/secrets/actions")
    else:
        info("Go to: GitHub repo → Settings → Secrets and variables → Actions")
    info("Click 'New repository secret'")
    info("  Name:  ANTHROPIC_API_KEY")
    info("  Value: your key from console.anthropic.com")
    print()

    if confirm("Have you added the secret?"):
        ok("Marked as done — AI features will activate on next PR")
        state["secret"] = True
        return True
    else:
        warn("Skipped — add before opening your first PR")
        return False


def phase_github_label(state: dict) -> bool:
    step(6, "GitHub Label — new-wo")

    code, out = run("gh label list 2>/dev/null")
    if code == 0 and "new-wo" in out:
        ok("'new-wo' label exists")
        state["label"] = True
        return True

    if code != 0:
        warn("gh CLI not authenticated — skipping label creation")
        return True

    print()
    info("The 'new-wo' label triggers the planning agent when applied to an issue.")
    code2, out2 = run('gh label create new-wo --color "#0075ca" --description "Triggers the planning agent to draft a WO spec"')
    if code2 == 0:
        ok("Created 'new-wo' label")
        state["label"] = True
        return True
    else:
        warn(f"Could not create label: {out2}")
        info('Create manually: gh label create new-wo --color "#0075ca"')
        return False


def phase_github_ruleset(state: dict) -> bool:
    step(7, "GitHub Branch Ruleset")

    repo = get_repo()
    if repo:
        code, out = run(f"gh api repos/{repo}/rulesets 2>/dev/null")
        if code == 0:
            try:
                rulesets = json.loads(out)
                names = [r.get("name", "") for r in rulesets]
                if "main-protection" in names:
                    ok("'main-protection' ruleset exists")
                    state["ruleset"] = True
                    return True
            except Exception:
                pass

    print()
    info("The branch ruleset requires status checks to pass before merging to main.")
    info("This is what blocks auto-merge when CI or AI review fails.")
    print()
    if repo:
        info(f"Go to: https://github.com/{repo}/settings/rules")
    else:
        info("Go to: GitHub repo → Settings → Rules → Rulesets")
    info("Click 'New branch ruleset'")
    info("  Name: main-protection")
    info("  Target branches: main")
    info("  Required status checks (add each by name):")
    info("    • Claude Code Review")
    info("    • Lint")
    info("    • Unit Tests")
    info("    • Build")
    info("    • Secret Detection (Gitleaks)")
    info()
    warn("The names must match the 'name:' fields in ci.yml and ai-review.yml exactly.")
    print()

    if confirm("Have you created the ruleset?"):
        ok("Marked as done")
        state["ruleset"] = True
        return True
    else:
        warn("Skipped — PRs won't be blocked by CI failures until this is set up")
        return False


def phase_review_context(state: dict) -> bool:
    step(8, "AI Review Context")

    path = ROOT / "scripts/review_context.txt"
    if not path.exists():
        warn("review_context.txt missing — skipping")
        return False

    content = path.read_text()
    if "Add your project-specific checks here" not in content and len(content.strip()) > 100:
        ok("review_context.txt has project-specific checks")
        state["review_context"] = True
        return True

    print()
    info("Add checks that the AI reviewer should always flag for this project.")
    info("Examples:")
    info("  1. Every database write must call db.commit() afterward")
    info("  2. Every new API route needs an authentication middleware dependency")
    info("  3. All secrets must be read from Vault, never from os.environ")
    info("  4. Migration files must be registered in the migration runner")
    print()

    checks = []
    info("Enter your project-specific checks one at a time (blank line to finish):")
    i = 1
    while True:
        check_text = ask(f"  Check {i}", "").strip()
        if not check_text:
            break
        checks.append(f"{i}. {check_text}")
        i += 1

    if checks:
        new_content = "\n".join(checks) + "\n"
        path.write_text(new_content)
        ok(f"Saved {len(checks)} check(s) to review_context.txt")
        state["review_context"] = True
        return True
    else:
        warn("No checks entered — review_context.txt unchanged")
        return False


def phase_memory_seed(state: dict) -> bool:
    step(9, "Memory System Seed")

    memory_dir = ROOT / "memory"
    index = memory_dir / "MEMORY.md"
    real_files = [
        f for f in memory_dir.rglob("*.md")
        if "examples" not in str(f) and f.name != "MEMORY.md"
    ]

    if real_files:
        ok(f"Memory system has {len(real_files)} file(s)")
        state["memory"] = True
        return True

    print()
    info("The memory system lets agents carry context across conversations.")
    info("Let's create your first project overview memory file.")
    print()

    project_name = state.get("project_name") or ask("Project name")
    stack = ask("Tech stack (e.g., Python/FastAPI + PostgreSQL + React)")
    description = ask("One sentence describing what the project does")
    deploy = ask("Where does it run? (e.g., AWS ECS, docker-compose, Heroku)")

    if not any([project_name, stack, description]):
        warn("Skipped — no info provided")
        return False

    content = f"""---
name: project-overview
description: What {project_name} is, its tech stack, and deployment environment
metadata:
  type: project
---

**Project:** {project_name}
**Stack:** {stack}
**Description:** {description}
**Deployment:** {deploy}

## Architecture notes

> Add key architectural decisions, critical invariants, and gotchas here.
> This is the first thing agents read when starting a new conversation.
"""

    overview_path = memory_dir / "project_overview.md"
    overview_path.write_text(content)
    ok(f"Created memory/project_overview.md")

    # Update MEMORY.md index
    if index.exists():
        index_content = index.read_text()
        if "project_overview.md" not in index_content:
            index_content += f"\n- [Project Overview](project_overview.md) — {description}"
            index.write_text(index_content)
            ok("Updated memory/MEMORY.md index")

    state["memory"] = True
    return True


def phase_observability(state: dict) -> bool:
    step(10, "Observability")

    # Check for METRICS_ENDPOINT
    code, out = run("gh variable list 2>/dev/null")
    if code == 0 and "METRICS_ENDPOINT" in out:
        ok("METRICS_ENDPOINT variable is set")
        state["observability"] = True
        return True

    print()
    info("The observability agent polls your app's health endpoint every 15 minutes")
    info("and creates a GitHub issue if it detects an anomaly.")
    print()

    endpoint = ask("Health endpoint URL (e.g., https://api.yourproject.com/health)", "")
    if not endpoint:
        warn("Skipped — set METRICS_ENDPOINT in Settings → Variables → Actions when ready")
        state["observability"] = "deferred"
        return True

    repo = get_repo()
    if repo:
        code2, _ = run(f'gh variable set METRICS_ENDPOINT --body "{endpoint}" --repo {repo}')
        if code2 == 0:
            ok(f"Set METRICS_ENDPOINT = {endpoint}")
        else:
            warn(f"Could not set variable — add manually in Settings → Variables → Actions")
            info(f"  Name: METRICS_ENDPOINT")
            info(f"  Value: {endpoint}")
    else:
        info(f"Add manually in Settings → Variables → Actions:")
        info(f"  Name: METRICS_ENDPOINT")
        info(f"  Value: {endpoint}")

    # Update thresholds
    thresholds_path = ROOT / "scripts/observability_thresholds.json"
    if thresholds_path.exists():
        thresholds = json.loads(thresholds_path.read_text())
        print()
        error_rate = ask("Acceptable error rate % (default: 1.0)", str(thresholds.get("error_rate_pct", 1.0)))
        latency = ask("Acceptable p99 latency ms (default: 2000)", str(thresholds.get("p99_latency_ms", 2000)))
        try:
            thresholds["error_rate_pct"] = float(error_rate)
            thresholds["p99_latency_ms"] = int(latency)
            thresholds_path.write_text(json.dumps(thresholds, indent=2) + "\n")
            ok("Updated observability_thresholds.json")
        except ValueError:
            pass

    state["observability"] = True
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Factory setup wizard")
    parser.add_argument("--status", action="store_true", help="Run status check only")
    parser.add_argument("--reset", action="store_true", help="Reset saved state and start over")
    args = parser.parse_args()

    if args.status:
        os.execv(sys.executable, [sys.executable, str(ROOT / "scripts/factory_status.py")])
        return

    state = {} if args.reset else load_state()

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        print("State reset.")

    repo = get_repo()
    project = state.get("project_name") or (repo.split("/")[-1] if repo else "your project")

    print(f"\n{BOLD}Agentic Factory Setup — {project}{RESET}")
    print("=" * 52)
    print("I'll walk you through each configuration step.")
    print("Progress is saved — you can stop and resume at any time.")
    print()

    phases = [
        ("identity", phase_project_identity),
        ("makefile", phase_makefile),
        ("ci", phase_ci_workflow),
        ("cd", phase_cd_workflow),
        ("secret", phase_github_secret),
        ("label", phase_github_label),
        ("ruleset", phase_github_ruleset),
        ("review_context", phase_review_context),
        ("memory", phase_memory_seed),
        ("observability", phase_observability),
    ]

    completed = 0
    for key, fn in phases:
        if state.get(key) in (True, "deferred"):
            completed += 1
            continue
        try:
            result = fn(state)
            save_state(state)
            if result:
                completed += 1
        except Exception as e:
            warn(f"Error in {key}: {e}")
            save_state(state)

    print(f"\n{'─' * 52}")
    total = len(phases)
    if completed == total:
        print(f"{GREEN}{BOLD}✅ Factory setup complete! ({completed}/{total} steps done){RESET}")
        print()
        print("Next steps:")
        print("  1. Commit and push the configured files to main")
        print("  2. Write your first work order: copy WO-000-template.md → WO-001-*.md")
        print("  3. Label any GitHub issue 'new-wo' to have the planning agent draft a WO spec")
        print("  4. Run 'make ci-local' to verify the local gate works")
    else:
        remaining = total - completed
        print(f"{YELLOW}{BOLD}{remaining} step(s) remaining.{RESET} Run this script again to continue.")

    print()


if __name__ == "__main__":
    main()
