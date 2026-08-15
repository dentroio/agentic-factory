#!/usr/bin/env python3
"""Classify and store the factory GitHub token (AF-11 / WO-1058).

Only fine-grained PATs (github_pat_...) may go in the factory Keychain.
Classic PATs (ghp_) and GitHub CLI OAuth tokens (gho_) are rejected.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

FINE_GRAINED = "fine_grained"
CLASSIC = "classic"
OAUTH = "oauth"
USER_TO_SERVER = "user_to_server"
UNKNOWN = "unknown"

_PREFIXES = (
    ("github_pat_", FINE_GRAINED),
    ("ghp_", CLASSIC),
    ("gho_", OAUTH),
    ("ghu_", USER_TO_SERVER),
)


def classify(token: str) -> str:
    value = (token or "").strip()
    for prefix, kind in _PREFIXES:
        if value.startswith(prefix):
            return kind
    return UNKNOWN


def require_fine_grained(token: str) -> str:
    """Return the stripped token, or raise ValueError."""
    value = (token or "").strip()
    kind = classify(value)
    if kind == FINE_GRAINED:
        return value
    if kind == CLASSIC:
        raise ValueError(
            "classic PAT (ghp_) rejected — factory requires a fine-grained "
            "github_pat_ token scoped to specific repositories (AF-11)"
        )
    if kind == OAUTH:
        raise ValueError(
            "GitHub CLI OAuth token (gho_) rejected — that token has repo+gist; "
            "store a fine-grained github_pat_ token instead (AF-11)"
        )
    raise ValueError(
        "unrecognized GitHub token — factory requires a fine-grained "
        "github_pat_ token (AF-11)"
    )


def _store_keychain(token: str) -> None:
    scripts = Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import keychain_set as ks  # noqa: WPS433

    ks.set_generic_password("dentroio-factory", "GITHUB_TOKEN", token.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--require-fine-grained",
        action="store_true",
        help="read token from stdin; exit 0 only if it is github_pat_",
    )
    group.add_argument(
        "--store",
        action="store_true",
        help="read token from stdin, validate, write Keychain (no argv)",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    raw = sys.stdin.read()
    try:
        token = require_fine_grained(raw)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.store:
        _store_keychain(token)
        print("Stored fine-grained GitHub PAT in Keychain (dentroio-factory / GITHUB_TOKEN).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
