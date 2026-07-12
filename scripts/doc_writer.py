#!/usr/bin/env python3
"""
Doc Writer Agent — keeps the Clarion wiki automatically up to date.

Runs every 6 hours via GitHub Actions. Finds stale or WO-uncovered wiki pages,
reads relevant WO specs and design docs, and uses Claude to write updated content.
Commits changes directly to the Clarion repo.

This is an AI Factory tool — it runs OUTSIDE the Clarion product stack.
Customers deploying Clarion never run or see this.

Usage:
    python3 scripts/doc_writer.py --clarion-path ./clarion
    python3 scripts/doc_writer.py --clarion-path ./clarion --dry-run
    python3 scripts/doc_writer.py --clarion-path ./clarion --max-pages 3
    python3 scripts/doc_writer.py --clarion-path ./clarion --page operator/secure/groups.md

Setup:
    export ANTHROPIC_API_KEY=sk-ant-...
    (GH_PAT handled by the workflow for commits)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

MAX_PAGES_DEFAULT = 5
STALE_DAYS = 90
MAX_FILE_BYTES = 64_000
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


# ── Frontmatter helpers ───────────────────────────────────────────────────────


def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, m.group(2).lstrip("\n")


def build_frontmatter(fm: dict[str, str]) -> str:
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


def is_stale(fm: dict[str, str], days: int = STALE_DAYS) -> bool:
    lv = fm.get("last_verified", "")
    if not lv:
        return True
    try:
        age = (date.today() - date.fromisoformat(lv)).days
        return age > days
    except ValueError:
        return True


# ── File scanning ─────────────────────────────────────────────────────────────


def find_stale_pages(wiki_root: Path, max_pages: int) -> list[Path]:
    """Return up to max_pages wiki pages that are stale or have empty covers_wos."""
    severely_stale, uncovered = [], []
    for p in sorted(wiki_root.rglob("*.md")):
        content = p.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)
        lv = fm.get("last_verified", "")
        covers = fm.get("covers_wos", "[]").strip()
        age = None
        if lv:
            try:
                age = (date.today() - date.fromisoformat(lv)).days
            except ValueError:
                pass

        if age is not None and age > 180:
            severely_stale.append(p)
        elif covers in ("[]", "", "- []"):
            uncovered.append(p)

    candidates = severely_stale + uncovered
    return candidates[:max_pages]


def find_unlinked_wos(wo_dir: Path, wiki_root: Path) -> list[Path]:
    """Return completed WO specs whose WO number doesn't appear in any wiki page covers_wos."""
    all_wiki_text = " ".join(
        p.read_text(encoding="utf-8") for p in wiki_root.rglob("*.md")
    )
    unlinked = []
    for wo_path in sorted(wo_dir.glob("WO-*.md")):
        content = wo_path.read_text(encoding="utf-8")
        if "✅" not in content and "Complete" not in content:
            continue
        wo_num = re.search(r"WO-(\d+)", wo_path.stem)
        if not wo_num:
            continue
        tag = f"WO-{wo_num.group(1)}"
        if tag not in all_wiki_text:
            unlinked.append(wo_path)
    return unlinked


def read_file(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    if len(content.encode()) > MAX_FILE_BYTES:
        return content[:MAX_FILE_BYTES] + "\n\n[truncated — file too large]"
    return content


# ── Claude call ───────────────────────────────────────────────────────────────


def call_claude(system: str, user: str) -> str:
    try:
        import anthropic
    except ImportError:
        logger.error("Run: pip install anthropic")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


SYSTEM_PROMPT = f"""You are the Clarion Documentation Writer. You update wiki pages for Clarion,
a network security and policy enforcement platform.

Today's date: {date.today().isoformat()}

Rules:
- Return ONLY the complete updated wiki page — full markdown including frontmatter, no preamble
- frontmatter MUST include: title, description, last_verified ({date.today().isoformat()}), covers_wos (list of WO numbers this page documents), doc_owner: clarion-team
- Set last_verified to exactly {date.today().isoformat()}
- covers_wos must be a YAML list: covers_wos:\\n  - WO-NNN
- Never document Open WOs — only features that have shipped (marked ✅ Complete)
- Never invent facts — only write what's confirmed in the WO specs or design docs provided
- Preserve correct existing content; only update sections that are stale or missing
- Keep pages concise and operator-focused — what it does, how to use it, key settings
- Never remove headings the page already has unless they're completely wrong
- If no changes are needed, return the original content exactly"""


def update_wiki_page(
    page_path: Path,
    wiki_root: Path,
    relevant_wos: list[Path],
    relevant_docs: list[Path],
) -> str | None:
    """Call Claude to update a wiki page. Returns new content or None if unchanged."""
    current = page_path.read_text(encoding="utf-8")
    rel = str(page_path.relative_to(wiki_root))

    wo_context = ""
    for wo in relevant_wos[:5]:
        wo_context += f"\n\n### {wo.name}\n{read_file(wo)}"

    doc_context = ""
    for doc in relevant_docs[:3]:
        doc_context += f"\n\n### {doc.name}\n{read_file(doc)}"

    user_msg = f"""Update this wiki page to be accurate and current.

## Current page: wiki/docs/{rel}
{current}

## Relevant WO specs (completed features to document){wo_context if wo_context else chr(10) + "None provided — preserve existing content and just update last_verified."}

## Relevant design docs{doc_context if doc_context else chr(10) + "None provided."}

Return the complete updated page."""

    logger.info("Calling Claude for %s ...", rel)
    updated = call_claude(SYSTEM_PROMPT, user_msg)

    # Validate the response has frontmatter
    if not updated.startswith("---"):
        logger.warning("Claude returned content without frontmatter for %s — skipping", rel)
        return None

    fm, _ = parse_frontmatter(updated)
    if fm.get("last_verified") != date.today().isoformat():
        logger.warning("Claude did not set last_verified correctly for %s — skipping", rel)
        return None

    # Skip if effectively unchanged (same content modulo whitespace)
    if updated.strip() == current.strip():
        logger.info("No changes for %s", rel)
        return None

    return updated


# ── Page → WO relevance matching ─────────────────────────────────────────────


def find_relevant_wos(page_path: Path, wiki_root: Path, wo_dir: Path) -> list[Path]:
    """Find WO specs likely relevant to this wiki page by keyword matching."""
    rel = str(page_path.relative_to(wiki_root)).lower()
    content = page_path.read_text(encoding="utf-8").lower()

    keywords = set(re.findall(r"\b[a-z]{4,}\b", rel + " " + content[:2000]))

    scored: list[tuple[int, Path]] = []
    for wo_path in sorted(wo_dir.glob("WO-*.md"), reverse=True):
        wo_text = wo_path.read_text(encoding="utf-8").lower()
        if "open" in wo_text[:500] and "complete" not in wo_text[:500]:
            continue
        score = sum(1 for kw in keywords if kw in wo_text[:3000])
        if score > 2:
            scored.append((score, wo_path))

    scored.sort(reverse=True)
    return [p for _, p in scored[:5]]


def find_relevant_docs(page_path: Path, wiki_root: Path, docs_root: Path) -> list[Path]:
    """Find design/architecture docs relevant to this wiki page."""
    rel = str(page_path.relative_to(wiki_root)).lower()
    keywords = set(re.findall(r"\b[a-z]{5,}\b", rel))

    candidates = list((docs_root / "design").glob("*.md")) + list(
        (docs_root / "architecture").glob("*.md")
    )
    scored: list[tuple[int, Path]] = []
    for doc in candidates:
        name_lower = doc.stem.lower()
        score = sum(1 for kw in keywords if kw in name_lower)
        if score > 0:
            scored.append((score, doc))

    scored.sort(reverse=True)
    return [p for _, p in scored[:3]]


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Update stale Clarion wiki pages using Claude")
    parser.add_argument("--clarion-path", required=True, help="Path to Clarion repo checkout")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES_DEFAULT, help=f"Max pages to update per run (default {MAX_PAGES_DEFAULT})")
    parser.add_argument("--page", help="Update a specific wiki page (relative to wiki/docs/)")
    parser.add_argument("--stale-days", type=int, default=STALE_DAYS)
    args = parser.parse_args()

    clarion = Path(args.clarion_path).resolve()
    wiki_root = clarion / "wiki" / "docs"
    wo_dir = clarion / "docs" / "project_management" / "work_orders"
    docs_root = clarion / "docs"

    if not wiki_root.exists():
        logger.error("wiki/docs not found at %s", wiki_root)
        sys.exit(1)
    if not wo_dir.exists():
        logger.error("WO specs dir not found at %s", wo_dir)
        sys.exit(1)

    # Determine which pages to process
    if args.page:
        target = wiki_root / args.page
        if not target.exists():
            logger.error("Page not found: %s", target)
            sys.exit(1)
        pages = [target]
    else:
        pages = find_stale_pages(wiki_root, args.max_pages)

    if not pages:
        logger.info("All wiki pages are current — nothing to update.")
        return

    logger.info("Pages to process: %d", len(pages))
    for p in pages:
        logger.info("  %s", p.relative_to(wiki_root))

    unlinked_wos = find_unlinked_wos(wo_dir, wiki_root)
    if unlinked_wos:
        logger.info("Completed WOs with no wiki coverage: %d", len(unlinked_wos))
        for w in unlinked_wos[:5]:
            logger.info("  %s", w.name)

    updated_pages: list[tuple[Path, str]] = []

    for page_path in pages:
        rel = str(page_path.relative_to(wiki_root))
        relevant_wos = find_relevant_wos(page_path, wiki_root, wo_dir)
        # Also include unlinked WOs that match this page
        for uw in unlinked_wos[:3]:
            if uw not in relevant_wos:
                relevant_wos.append(uw)
        relevant_docs = find_relevant_docs(page_path, wiki_root, docs_root)

        if args.dry_run:
            logger.info("[dry-run] would update %s (relevant WOs: %s)",
                        rel, [w.stem for w in relevant_wos[:3]])
            continue

        new_content = update_wiki_page(page_path, wiki_root, relevant_wos, relevant_docs)
        if new_content:
            updated_pages.append((page_path, new_content))
            logger.info("Updated: %s", rel)
        else:
            logger.info("Skipped (no changes): %s", rel)

    if args.dry_run:
        logger.info("[dry-run] complete — no files written")
        return

    if not updated_pages:
        logger.info("No pages needed updating this run.")
        return

    # Write updated pages to disk (workflow handles git commit + push)
    for page_path, content in updated_pages:
        page_path.write_text(content, encoding="utf-8")
        logger.info("Written: %s", page_path.relative_to(wiki_root))

    # Write summary for the workflow step
    summary_lines = [f"Updated {len(updated_pages)} wiki page(s):"]
    for page_path, _ in updated_pages:
        summary_lines.append(f"  - wiki/docs/{page_path.relative_to(wiki_root)}")
    print("\n".join(summary_lines))

    # Write GitHub step summary if available
    step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as f:
            f.write("## Doc Writer Agent\n\n")
            for line in summary_lines:
                f.write(line.strip() + "\n")


if __name__ == "__main__":
    main()
