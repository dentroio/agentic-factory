#!/usr/bin/env python3
"""
Scan docs/wiki/ for pages that need documentation review.

Exit codes:
  0 — no issues found
  1 — stale or uncovered pages found

Usage:
  python scripts/docs_stale_check.py            # default: 90-day threshold
  python scripts/docs_stale_check.py --days 60  # stricter threshold
  python scripts/docs_stale_check.py --json     # machine-readable output
  python scripts/docs_stale_check.py --gha      # GitHub Actions step summary
"""

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

WIKI_DOCS = Path("docs/wiki")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def parse_frontmatter(content: str) -> dict:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}
    fields: dict = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields


def check_page(path: Path, stale_days: int) -> dict | None:
    content = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)
    issues = []

    last_verified_raw = fm.get("last_verified", "").strip()
    if not last_verified_raw:
        issues.append("missing last_verified")
        age_days = None
    else:
        try:
            lv = datetime.strptime(last_verified_raw, "%Y-%m-%d").date()
            age_days = (date.today() - lv).days
            if age_days > stale_days:
                issues.append(f"stale ({age_days}d since last_verified)")
        except ValueError:
            issues.append(f"invalid last_verified format: {last_verified_raw!r}")
            age_days = None

    covers_raw = fm.get("covers_wos", "[]").strip()
    if covers_raw in ("[]", "", "- []"):
        issues.append("covers_wos is empty")

    if not issues:
        return None

    return {
        "path": str(path.relative_to(WIKI_DOCS)),
        "issues": issues,
        "age_days": age_days,
        "last_verified": last_verified_raw or None,
        "doc_owner": fm.get("doc_owner", "").strip() or "unassigned",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan docs/wiki for stale pages.")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--gha", action="store_true")
    parser.add_argument("--ignore-empty-wos", action="store_true")
    args = parser.parse_args()

    if not WIKI_DOCS.exists():
        print(f"ERROR: {WIKI_DOCS} not found. Run from the repo root.", file=sys.stderr)
        sys.exit(1)

    pages = sorted(p for p in WIKI_DOCS.rglob("*.md") if not p.name.startswith("_"))
    problems: list[dict] = []

    for page in pages:
        result = check_page(page, args.days)
        if result:
            if args.ignore_empty_wos:
                result["issues"] = [i for i in result["issues"] if "covers_wos" not in i]
            if result["issues"]:
                problems.append(result)

    problems.sort(key=lambda x: (
        0 if any("stale" in i for i in x["issues"]) else 1,
        -(x["age_days"] or 0),
    ))

    if args.json:
        print(json.dumps({"threshold_days": args.days, "problems": problems}, indent=2))
        sys.exit(1 if problems else 0)

    if args.gha:
        import os
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "/dev/stdout")
        with open(summary_path, "a") as f:
            f.write(f"## Factory Docs Stale Check — {date.today()}\n\n")
            if not problems:
                f.write("✅ All wiki pages are up to date.\n")
            else:
                stale = [p for p in problems if any("stale" in i for i in p["issues"])]
                empty = [p for p in problems if all("stale" not in i for i in p["issues"])]
                if stale:
                    f.write(f"### ⚠️ Stale pages ({len(stale)}) — last_verified > {args.days} days ago\n\n")
                    f.write("| Page | Age | Owner |\n|---|---|---|\n")
                    for p in stale:
                        f.write(f"| `{p['path']}` | {p['age_days']}d | {p['doc_owner']} |\n")
                    f.write("\n")
                if empty and not args.ignore_empty_wos:
                    f.write(f"### ℹ️ Pages with no WO coverage listed ({len(empty)})\n\n")
                    f.write("| Page | Owner |\n|---|---|\n")
                    for p in empty:
                        f.write(f"| `{p['path']}` | {p['doc_owner']} |\n")
        sys.exit(1 if [p for p in problems if any("stale" in i for i in p["issues"])] else 0)

    if not problems:
        print(f"✓ All {len(pages)} wiki pages are within the {args.days}-day threshold.")
        sys.exit(0)

    stale = [p for p in problems if any("stale" in i for i in p["issues"])]
    empty = [p for p in problems if all("stale" not in i for i in p["issues"])]

    if stale:
        print(f"\nSTALE ({len(stale)} pages — last_verified > {args.days} days ago):")
        for p in stale:
            print(f"  {p['age_days']:>4}d  {p['path']}  [{p['doc_owner']}]")

    if empty and not args.ignore_empty_wos:
        print(f"\nEMPTY covers_wos ({len(empty)} pages):")
        for p in empty:
            print(f"        {p['path']}  [{p['doc_owner']}]")

    print(f"\n{len(stale)} stale, {len(empty)} without WO coverage, out of {len(pages)} total pages.")
    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()
