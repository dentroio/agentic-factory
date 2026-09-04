#!/usr/bin/env python3
"""Factory init — scaffold BYO product folders and factory.yaml.

Run from the engine checkout:
    make init PATH=/path/to/your-app
    python3 scripts/factory_init.py --path /path/to/your-app --name my-app --non-interactive

Does not touch the engine repo itself unless --path points here (discouraged).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
PROCESS_SRC = ENGINE_ROOT / "docs" / "adopters" / "PROCESS.md"

DEFAULT_PATTERNS = """## Product codebase patterns

Follow existing patterns in this repository exactly — naming, file layout,
error handling, and abstraction level. Do not invent parallel structures.

### Security & data
- Never hardcode secrets, API keys, or passwords
- Prefer parameterized queries / safe ORM APIs over string-built SQL
- Protect new API routes with the project's existing auth dependencies

### Process
- Read AGENT_PROCESS.md before starting a Work Order
- Run only the verify command in factory.yaml — do not invent CI targets
"""

SAMPLE_WO = """# WO-001 — Hello factory

**Status:** Open
**Priority:** P3
**Effort:** XS
**Services:** none
**Depends on:** —

## Problem

Smoke Work Order so a new factory adoption can prove claim → PR without touching app logic.

## What to Build

Add a one-line note to `docs/factory/patterns.md` under a `## Factory smoke` heading
confirming the factory can open a docs-only PR.

## Out of scope

Application code, CI changes, dependency bumps.

## Acceptance Criteria

- [ ] `docs/factory/patterns.md` contains a `## Factory smoke` section
- [ ] PR title contains `WO-001`

## Execution

- **Branch:** `wo/001-hello-factory`
- **Risk tier:** P3
- **PR title:** `docs(factory): WO-001 — hello factory`
- **Pre-PR gate:** verify command from factory.yaml
- **User verification required:** No
"""


def _factory_yaml(name: str, verify: str, ui_url: str, ui_hint: str) -> str:
    return (
        f"name: {name}\n"
        f'verify: "{verify}"\n'
        f'ui_url: "{ui_url}"\n'
        f'ui_verify_hint: "{ui_hint}"\n'
        'compose_project: ""\n'
        'patterns_file: "docs/factory/patterns.md"\n'
    )


def init_product(
    path: Path,
    *,
    name: str,
    verify: str = "make ci-local",
    ui_url: str = "http://localhost:8765",
    ui_verify_hint: str = "Open the app; confirm the change matches the WO.",
    force: bool = False,
    sample_wo: bool = False,
) -> list[str]:
    """Create adopter scaffolding. Returns list of created/updated relative paths."""
    root = path.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    created: list[str] = []

    def write(rel: str, content: str, *, executable: bool = False) -> None:
        dest = root / rel
        if dest.exists() and not force:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
        if executable:
            dest.chmod(dest.stat().st_mode | 0o111)
        created.append(rel)

    write(
        "factory.yaml",
        _factory_yaml(name, verify, ui_url, ui_verify_hint),
    )
    write("docs/factory/patterns.md", DEFAULT_PATTERNS)
    write("docs/factory/runs/.gitkeep", "")
    (root / "docs" / "project_management" / "work_orders").mkdir(parents=True, exist_ok=True)
    if not any((root / "docs" / "project_management" / "work_orders").iterdir()) or force:
        # Ensure directory exists; track it for reporting when empty
        wo_marker = root / "docs" / "project_management" / "work_orders" / ".gitkeep"
        if not wo_marker.exists() or force:
            wo_marker.write_text("", encoding="utf-8")
            created.append("docs/project_management/work_orders/.gitkeep")

    if PROCESS_SRC.is_file():
        write("AGENT_PROCESS.md", PROCESS_SRC.read_text(encoding="utf-8"))
    else:
        write(
            "AGENT_PROCESS.md",
            "# AGENT_PROCESS.md\n\nCopy docs/adopters/PROCESS.md from agentic-factory.\n",
        )

    if sample_wo:
        write(
            "docs/project_management/work_orders/WO-001-hello-factory.md",
            SAMPLE_WO,
        )

    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold factory adopter files into a product repository",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path.cwd(),
        help="Product repo root (default: cwd)",
    )
    parser.add_argument("--name", default="", help="Product short name for factory.yaml")
    parser.add_argument("--verify", default="make ci-local", help="Quality-gate command")
    parser.add_argument("--ui-url", default="http://localhost:8765")
    parser.add_argument(
        "--ui-verify-hint",
        default="Open the app; confirm the change matches the WO.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument(
        "--sample-wo",
        action="store_true",
        help="Write docs-only WO-001 smoke spec",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt; require --name (or derive from path)",
    )
    args = parser.parse_args(argv)

    name = (args.name or "").strip()
    if not name:
        if args.non-interactive:
            name = args.path.expanduser().resolve().name
        else:
            try:
                entered = input(f"Product name [{args.path.resolve().name}]: ").strip()
            except EOFError:
                entered = ""
            name = entered or args.path.resolve().name

    if args.path.resolve() == ENGINE_ROOT.resolve() and not args.force:
        print(
            "Refusing to scaffold into the agentic-factory engine checkout.\n"
            "Pass --path /path/to/your-product (or --force if you really mean it).",
            file=sys.stderr,
        )
        return 2

    created = init_product(
        args.path,
        name=name,
        verify=args.verify,
        ui_url=args.ui_url,
        ui_verify_hint=args.ui_verify_hint,
        force=args.force,
        sample_wo=args.sample_wo,
    )

    root = args.path.expanduser().resolve()
    print(f"Scaffolded factory adopter files in {root}")
    if created:
        for rel in created:
            print(f"  + {rel}")
    else:
        print("  (nothing written — files already exist; pass --force to overwrite)")

    print(
        "\nNext steps:\n"
        "  1. Create GitHub labels on the product: new-wo, agent-pr, pm-sync\n"
        "  2. Point the engine: GITHUB_REPO=owner/repo and LOCAL_REPO_PATH="
        f"{root}\n"
        "  3. From the engine checkout: make doctor DOCTOR_ARGS=\"--product "
        f"{root} --skip-network\"\n"
        "  4. Docs: docs/wiki/Getting-Started.md / docs/adopters/BYO.md\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
