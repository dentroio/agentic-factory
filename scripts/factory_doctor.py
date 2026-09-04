#!/usr/bin/env python3
"""Factory doctor — validate engine prefs + product wiring for adoption.

Run:
    make doctor
    python3 scripts/factory_doctor.py
    python3 scripts/factory_doctor.py --product /path/to/app

Exit codes:
    0 — hard checks passed (warnings allowed)
    1 — one or more hard checks failed
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PREFS = Path.home() / ".config" / "factory-agent" / "prefs"
WO_DIR_DEFAULT = "docs/project_management/work_orders"
PROFILE_CANDIDATES = ("factory.yaml", "docs/factory/profile.yaml")

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1m"

PASS = f"{GREEN}ok{RESET}"
WARN = f"{YELLOW}warn{RESET}"
FAIL = f"{RED}fail{RESET}"


@dataclass
class CheckResult:
    ok: bool
    label: str
    detail: str = ""
    warn: bool = False


@dataclass
class DoctorReport:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def hard_failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.ok and not r.warn]

    @property
    def passed(self) -> bool:
        return not self.hard_failures


def load_prefs(prefs_path: Path | None = None) -> dict[str, str]:
    """Load KEY=VALUE prefs; env wins over file for known keys."""
    path = prefs_path or Path(os.environ.get("FACTORY_PREFS", str(DEFAULT_PREFS)))
    data: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            data[key.strip()] = val.strip().strip("'\"")
    for key in ("GITHUB_REPO", "LOCAL_REPO_PATH", "PREFERRED_AGENT", "WO_PATH"):
        if os.environ.get(key):
            data[key] = os.environ[key].strip()
    return data


def _git(cwd: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _remote_owner_repo(product: Path) -> str | None:
    code, out = _git(product, "remote", "get-url", "origin")
    if code != 0 or not out:
        return None
    url = out.splitlines()[0].strip()
    # git@github.com:owner/repo.git or https://github.com/owner/repo.git
    m = re.search(r"[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def _find_profile(product: Path) -> Path | None:
    env_path = os.environ.get("FACTORY_PROFILE", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_file():
            return p
    for name in PROFILE_CANDIDATES:
        candidate = product / name
        if candidate.is_file():
            return candidate
    return None


def _parse_verify(profile_path: Path) -> str:
    text = profile_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("verify:"):
            return stripped.split(":", 1)[1].strip().strip("'\"")
    return "make ci-local"


def _verify_command_ok(product: Path, verify: str) -> tuple[bool, str]:
    parts = verify.split()
    if not parts:
        return False, "verify command is empty"
    cmd = parts[0]
    if cmd == "make":
        if len(parts) < 2:
            return False, "verify is 'make' without a target"
        target = parts[1]
        makefile = product / "Makefile"
        if not makefile.is_file():
            return False, f"no Makefile for verify target '{target}'"
        body = makefile.read_text(encoding="utf-8")
        # Accept "target:" or ".PHONY: ... target"
        if re.search(rf"(?m)^{re.escape(target)}\s*:", body):
            return True, f"Makefile has target '{target}'"
        return False, f"Makefile missing target '{target}'"
    if shutil.which(cmd):
        return True, f"'{cmd}' found on PATH"
    # Relative script in product
    script = product / cmd
    if script.is_file() and os.access(script, os.X_OK):
        return True, f"executable {cmd} in product"
    return False, f"'{cmd}' not found on PATH or as product executable"


def _print_section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")
    print("─" * 50)


def _print_result(r: CheckResult) -> None:
    icon = PASS if r.ok else (WARN if r.warn else FAIL)
    suffix = f" — {r.detail}" if r.detail else ""
    print(f"  [{icon}] {r.label}{suffix}")


def run_doctor(
    *,
    product_path: Path | None = None,
    prefs_path: Path | None = None,
    skip_network: bool = False,
) -> DoctorReport:
    report = DoctorReport()
    prefs = load_prefs(prefs_path)

    _print_section("Engine prefs")
    github_repo = (prefs.get("GITHUB_REPO") or "").strip()
    local_path = (prefs.get("LOCAL_REPO_PATH") or "").strip()

    if product_path is not None:
        product = product_path.expanduser().resolve()
        # Product-only mode: prefs optional
        if not github_repo:
            github_repo = "(product-only)"
            report.add(
                CheckResult(
                    True,
                    "GITHUB_REPO",
                    "skipped in --product mode (no prefs repo required)",
                    warn=True,
                )
            )
        else:
            report.add(
                CheckResult(
                    bool(re.match(r"^[^/\s]+/[^/\s]+$", github_repo)),
                    "GITHUB_REPO",
                    github_repo
                    if re.match(r"^[^/\s]+/[^/\s]+$", github_repo)
                    else "expected owner/name",
                )
            )
    else:
        shape_ok = bool(re.match(r"^[^/\s]+/[^/\s]+$", github_repo))
        report.add(
            CheckResult(
                shape_ok,
                "GITHUB_REPO",
                github_repo
                if shape_ok
                else (github_repo or "missing — set in Settings → Authentication (or make agent-setup)"),
            )
        )
        if not local_path:
            report.add(
                CheckResult(
                    False,
                    "LOCAL_REPO_PATH",
                    "missing — set in Settings → Authentication (Product checkout)",
                )
            )
            for r in report.results:
                _print_result(r)
            return report
        product = Path(local_path).expanduser().resolve()

    if product_path is None:
        exists = product.is_dir()
        report.add(
            CheckResult(
                exists,
                "LOCAL_REPO_PATH exists",
                str(product) if exists else f"not a directory: {product}",
            )
        )
        if not exists:
            for r in report.results:
                _print_result(r)
            return report
    elif not product.is_dir():
        report.add(CheckResult(False, "product path", f"not a directory: {product}"))
        for r in report.results:
            _print_result(r)
        return report
    else:
        report.add(CheckResult(True, "product path", str(product)))

    for r in report.results:
        _print_result(r)

    _print_section("Product git")
    git_dir_ok = (product / ".git").exists() or _git(product, "rev-parse", "--is-inside-work-tree")[0] == 0
    git_result = CheckResult(
        git_dir_ok,
        "git worktree",
        "ok" if git_dir_ok else "not a git repository — clone the product first",
    )
    report.add(git_result)
    _print_result(git_result)

    if git_dir_ok and github_repo and github_repo != "(product-only)":
        remote = _remote_owner_repo(product)
        if remote is None:
            mismatch = CheckResult(
                True,
                "origin matches GITHUB_REPO",
                "could not parse git remote origin",
                warn=True,
            )
        else:
            match = remote.lower() == github_repo.lower()
            # --product mode: prefs/env repo may be unrelated; warn only.
            # Full prefs mode: mismatch is a hard failure (agents would PR the wrong repo).
            soft = product_path is not None
            mismatch = CheckResult(
                match or soft,
                "origin matches GITHUB_REPO",
                f"origin={remote} prefs={github_repo}"
                if not match
                else f"{remote}",
                warn=soft and not match,
            )
        report.add(mismatch)
        _print_result(mismatch)

    _print_section("Product profile")
    profile = _find_profile(product)
    if profile is None:
        missing = CheckResult(
            False,
            "factory.yaml",
            "missing — run: make init  (or copy docs/wiki/Product-Profile.md example)",
        )
        report.add(missing)
        _print_result(missing)
    else:
        found = CheckResult(True, "factory.yaml", str(profile.relative_to(product)))
        report.add(found)
        _print_result(found)
        verify = _parse_verify(profile)
        vok, vdetail = _verify_command_ok(product, verify)
        vres = CheckResult(vok, f"verify ({verify})", vdetail)
        report.add(vres)
        _print_result(vres)

    wo_rel = prefs.get("WO_PATH") or os.environ.get("WO_PATH") or WO_DIR_DEFAULT
    wo_dir = product / wo_rel
    wo_ok = wo_dir.is_dir()
    wo_res = CheckResult(
        wo_ok,
        "WO specs dir",
        str(wo_dir.relative_to(product))
        if wo_ok
        else f"missing {wo_rel} — run make init or create the folder",
    )
    report.add(wo_res)
    _print_result(wo_res)

    runs = product / "docs" / "factory" / "runs"
    runs_res = CheckResult(
        runs.is_dir(),
        "claim runs dir",
        "docs/factory/runs"
        if runs.is_dir()
        else "missing docs/factory/runs — run make init",
        warn=not runs.is_dir(),
    )
    # Missing runs dir is a warning (agents create claims) but recommend it
    if not runs.is_dir():
        runs_res.ok = True  # warn-only
        runs_res.warn = True
    report.add(runs_res)
    _print_result(runs_res)

    process = product / "AGENT_PROCESS.md"
    proc_res = CheckResult(
        process.is_file(),
        "AGENT_PROCESS.md",
        "present" if process.is_file() else "missing — make init copies docs/adopters/PROCESS.md",
        warn=not process.is_file(),
    )
    if not process.is_file():
        proc_res.ok = True
        proc_res.warn = True
    report.add(proc_res)
    _print_result(proc_res)

    _print_section("Legacy / leakage")
    legacy = os.environ.get("FACTORY_LEGACY_PRODUCT", "").strip()
    if legacy and github_repo and github_repo != "(product-only)":
        matched = legacy.lower() == github_repo.lower()
        leg = CheckResult(
            True,
            "FACTORY_LEGACY_PRODUCT",
            f"matches {github_repo}"
            if matched
            else f"set to {legacy} but GITHUB_REPO is {github_repo} — legacy patterns will not load",
            warn=not matched,
        )
        report.add(leg)
        _print_result(leg)
    else:
        leg = CheckResult(True, "FACTORY_LEGACY_PRODUCT", "unset (generic product path)")
        report.add(leg)
        _print_result(leg)

    if not skip_network and github_repo and github_repo != "(product-only)" and shutil.which("gh"):
        _print_section("GitHub (optional)")
        try:
            proc = subprocess.run(
                ["gh", "api", f"repos/{github_repo}", "--jq", ".full_name"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            reachable = proc.returncode == 0 and proc.stdout.strip()
            gh_res = CheckResult(
                True if reachable else True,
                "repo reachable",
                proc.stdout.strip()
                if reachable
                else (proc.stderr.strip() or "gh api failed — check token scopes"),
                warn=not bool(reachable),
            )
            report.add(gh_res)
            _print_result(gh_res)

            lab = subprocess.run(
                ["gh", "label", "list", "-R", github_repo, "--limit", "50"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            labels = lab.stdout if lab.returncode == 0 else ""
            needed = ["new-wo", "agent-pr", "pm-sync"]
            missing = [n for n in needed if n not in labels]
            lab_res = CheckResult(
                True,
                "product labels",
                "all present" if not missing else f"missing: {', '.join(missing)}",
                warn=bool(missing) or lab.returncode != 0,
            )
            report.add(lab_res)
            _print_result(lab_res)
        except (OSError, subprocess.TimeoutExpired) as exc:
            net = CheckResult(True, "GitHub checks", str(exc), warn=True)
            report.add(net)
            _print_result(net)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate factory engine + product wiring")
    parser.add_argument(
        "--product",
        type=Path,
        help="Doctor this product tree (skips requiring LOCAL_REPO_PATH)",
    )
    parser.add_argument(
        "--prefs",
        type=Path,
        help="Prefs file path (default ~/.config/factory-agent/prefs)",
    )
    parser.add_argument(
        "--skip-network",
        action="store_true",
        help="Skip gh API / label checks",
    )
    args = parser.parse_args(argv)

    print(f"\n{BOLD}Factory doctor{RESET}")
    print("=" * 52)

    report = run_doctor(
        product_path=args.product,
        prefs_path=args.prefs,
        skip_network=args.skip_network,
    )

    print(f"\n{'─' * 52}")
    if report.passed:
        warns = sum(1 for r in report.results if r.warn)
        if warns:
            print(f"{YELLOW}{BOLD}Passed with {warns} warning(s).{RESET}")
        else:
            print(f"{GREEN}{BOLD}All checks passed — product wiring looks good.{RESET}")
        print("Next: open http://localhost:8099 and dispatch a sample WO.")
        return 0

    print(f"{RED}{BOLD}{len(report.hard_failures)} hard failure(s).{RESET}")
    print("Fix hints:")
    print("  Dashboard: Settings → Get Started — GitHub, product checkout, agent/LLM")
    print("  make init PRODUCT=/path/to/app   # CLI scaffold fallback")
    print("  make agent-setup                # first-time secrets (optional if using UI)")
    print("  Docs: docs/wiki/Getting-Started.md")
    return 1


if __name__ == "__main__":
    sys.exit(main())
