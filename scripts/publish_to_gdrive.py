#!/usr/bin/env python3
"""
Publish Agentic Factory docs to Google Drive.

This is an internal factory tool — it is NOT part of any customer-facing product.

Categories:
  architecture  → GDRIVE_FOLDER_ARCHITECTURE folder (technical docs)
  executive     → GDRIVE_FOLDER_EXECUTIVE folder (executive/investor docs)

Auth (OAuth2 — required for personal Gmail):
  Run once locally:
    python scripts/publish_to_gdrive.py --auth
  Store the printed token as GitHub secret GDRIVE_REFRESH_TOKEN.
  Also set GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET.

Drive map:
  docs/google_drive_map.json — maps local file paths → Drive Doc IDs
  Committed back to the repo so IDs persist across runs.

Usage:
  python scripts/publish_to_gdrive.py --auth             # one-time setup
  python scripts/publish_to_gdrive.py                    # sync all
  python scripts/publish_to_gdrive.py --dry-run
  python scripts/publish_to_gdrive.py --category executive
  python scripts/publish_to_gdrive.py --show-map
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIVE_MAP_PATH = REPO_ROOT / "docs" / "google_drive_map.json"

CATEGORY_PREFIXES: dict[str, list[str]] = {
    "architecture": [
        "docs/TECHNICAL_ARCHITECTURE.md",
        "docs/CD_IMPLEMENTATION_PLAN.md",
        "docs/GITHUB_ACTIONS_GUIDE.md",
        "docs/ENGINEER_OVERVIEW.md",
    ],
    "executive": [
        "docs/EXECUTIVE_BRIEF.md",
    ],
}

FOLDER_ENV: dict[str, str] = {
    "architecture": "GDRIVE_FOLDER_ARCHITECTURE",
    "executive": "GDRIVE_FOLDER_EXECUTIVE",
}


def category_for(path: Path) -> str | None:
    rel = str(path.relative_to(REPO_ROOT))
    for cat, prefixes in CATEGORY_PREFIXES.items():
        for prefix in prefixes:
            if rel == prefix or rel.startswith(prefix):
                return cat
    return None


def all_target_files() -> list[tuple[Path, str]]:
    results: list[tuple[Path, str]] = []
    for cat, prefixes in CATEGORY_PREFIXES.items():
        for prefix in prefixes:
            p = REPO_ROOT / prefix
            if p.is_dir():
                for f in sorted(p.rglob("*.md")):
                    if not any(part.startswith(".") for part in f.parts):
                        results.append((f, cat))
            elif p.is_file():
                results.append((p, cat))
    return results


def md_to_html(content: str, title: str) -> str:
    try:
        import markdown  # type: ignore[import]
        body = markdown.markdown(
            content,
            extensions=["tables", "fenced_code", "toc", "nl2br"],
        )
    except ImportError:
        escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body = f"<pre>{escaped}</pre>"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body>{body}</body></html>"""


def load_drive_map() -> dict[str, str]:
    if DRIVE_MAP_PATH.exists():
        return json.loads(DRIVE_MAP_PATH.read_text())
    return {}


def save_drive_map(mapping: dict[str, str]) -> None:
    DRIVE_MAP_PATH.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n")
    logger.info("Drive map saved → %s", DRIVE_MAP_PATH)


SCOPES = ["https://www.googleapis.com/auth/drive"]


def _build_credentials_oauth2():
    try:
        from google.oauth2.credentials import Credentials  # type: ignore[import]
        from google.auth.transport.requests import Request  # type: ignore[import]
    except ImportError:
        logger.error("Run: pip install google-api-python-client google-auth-oauthlib markdown")
        sys.exit(1)

    refresh_token = os.getenv("GDRIVE_REFRESH_TOKEN", "")
    client_id = os.getenv("GDRIVE_CLIENT_ID", "")
    client_secret = os.getenv("GDRIVE_CLIENT_SECRET", "")

    if not all([refresh_token, client_id, client_secret]):
        logger.error(
            "Requires GDRIVE_REFRESH_TOKEN, GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET.\n"
            "Run:  python scripts/publish_to_gdrive.py --auth  to generate a refresh token."
        )
        sys.exit(1)

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def _run_auth_flow():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import]
    except ImportError:
        logger.error("Run: pip install google-auth-oauthlib")
        sys.exit(1)

    client_id = os.getenv("GDRIVE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GDRIVE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print(
            "\nRequires a GCP OAuth2 Desktop App client.\n"
            "Set GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET and re-run --auth.\n"
        )
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n" + "=" * 60)
    print("OAuth2 authorized successfully!")
    print("\nAdd these as GitHub Actions secrets on dentroio/agentic-factory:\n")
    print(f"  GDRIVE_REFRESH_TOKEN  =  {creds.refresh_token}")
    print(f"  GDRIVE_CLIENT_ID      =  {client_id}")
    print(f"  GDRIVE_CLIENT_SECRET  =  {client_secret}")
    print("\nAlso add folder IDs:")
    print("  GDRIVE_FOLDER_ARCHITECTURE  =  <Drive folder ID for technical docs>")
    print("  GDRIVE_FOLDER_EXECUTIVE     =  <Drive folder ID for executive docs>")
    print("=" * 60 + "\n")


def _build_drive_service():
    from googleapiclient.discovery import build  # type: ignore[import]
    return build("drive", "v3", credentials=_build_credentials_oauth2(), cache_discovery=False)


def publish_file(
    path: Path,
    category: str,
    drive_map: dict[str, str],
    service: Any,
    dry_run: bool = False,
) -> dict[str, str]:
    rel = str(path.relative_to(REPO_ROOT))
    existing_id = drive_map.get(rel)

    if dry_run:
        action = "update" if existing_id else "create"
        logger.info("[dry-run] would %s '%s' → Drive/%s/", action, rel, category)
        return {"path": rel, "action": action, "dry_run": True}

    from googleapiclient.http import MediaIoBaseUpload  # type: ignore[import]

    folder_id = os.getenv(FOLDER_ENV[category], "")
    if not folder_id:
        raise ValueError(
            f"Env var {FOLDER_ENV[category]} not set — cannot publish to '{category}' folder."
        )

    title = path.stem.replace("_", " ").replace("-", " ").title()
    content = path.read_text(encoding="utf-8")
    html_bytes = md_to_html(content, title).encode("utf-8")

    media = MediaIoBaseUpload(io.BytesIO(html_bytes), mimetype="text/html", resumable=False)

    if existing_id:
        service.files().update(fileId=existing_id, media_body=media).execute()
        doc_id = existing_id
        action = "updated"
    else:
        file_metadata: dict[str, Any] = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id],
        }
        result = service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()
        doc_id = result["id"]
        action = "created"

    drive_map[rel] = doc_id
    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    logger.info("%s  %s  →  %s", action.upper(), rel, url)
    return {"path": rel, "action": action, "doc_id": doc_id, "url": url}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Factory docs to Google Drive")
    parser.add_argument("--auth", action="store_true", help="One-time OAuth2 browser flow")
    parser.add_argument("--path", help="Publish a single file (relative to repo root)")
    parser.add_argument("--category", choices=list(CATEGORY_PREFIXES), help="Publish one category")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--show-map", action="store_true")
    args = parser.parse_args()

    if args.auth:
        _run_auth_flow()
        return

    drive_map = load_drive_map()

    if args.show_map:
        print(json.dumps(drive_map, indent=2))
        return

    service = None if args.dry_run else _build_drive_service()

    if args.path:
        target_path = (REPO_ROOT / args.path).resolve()
        if not target_path.exists():
            logger.error("File not found: %s", target_path)
            sys.exit(1)
        cat = args.category or category_for(target_path)
        if not cat:
            logger.error("Could not determine category for %s. Use --category.", target_path)
            sys.exit(1)
        targets = [(target_path, cat)]
    elif args.category:
        targets = [(p, c) for p, c in all_target_files() if c == args.category]
    else:
        targets = all_target_files()

    if not targets:
        logger.warning("No files matched.")
        return

    results, errors = [], []
    for path, cat in targets:
        try:
            r = publish_file(path, cat, drive_map, service, dry_run=args.dry_run)
            results.append(r)
        except Exception as exc:
            logger.error("FAILED  %s: %s", path.relative_to(REPO_ROOT), exc)
            errors.append({"path": str(path.relative_to(REPO_ROOT)), "error": str(exc)})

    if not args.dry_run and results:
        save_drive_map(drive_map)

    created = sum(1 for r in results if r.get("action") == "created")
    updated = sum(1 for r in results if r.get("action") == "updated")
    logger.info("\nDone — %d created, %d updated, %d failed", created, updated, len(errors))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
