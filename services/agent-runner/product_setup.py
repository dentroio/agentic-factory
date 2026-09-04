"""Host-side product wiring: prefs, local path, clone, and factory init.

The agent-runner runs on the Mac host (not in Docker), so it is the only
process that can safely write ~/.config/factory-agent/prefs, validate a
local checkout path, git-clone into the user's home, and scaffold
factory.yaml. The dashboard reaches this via the orchestrator proxy.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PREFS_PATH = Path(
    os.environ.get("FACTORY_PREFS", str(Path.home() / ".config" / "factory-agent" / "prefs"))
)
_REPO_RE = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")

# Prefer cloning under ~/src when that directory exists; otherwise ~/Projects or ~.
_DEFAULT_PARENTS = ("src", "Projects", "Developer", "code", "workspace")


class ProductSetupError(ValueError):
    """User-facing configuration error (safe for HTTP 400 detail)."""


def prefs_path() -> Path:
    return PREFS_PATH


def read_prefs(path: Path | None = None) -> dict[str, str]:
    target = path or PREFS_PATH
    data: dict[str, str] = {}
    if not target.is_file():
        return data
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        data[key.strip()] = val.strip().strip("'\"")
    return data


def write_prefs(updates: dict[str, str], path: Path | None = None) -> dict[str, str]:
    """Merge updates into prefs. Empty string values delete the key."""
    target = path or PREFS_PATH
    current = read_prefs(target)
    for key, value in updates.items():
        if value is None:
            continue
        value = str(value).strip()
        if not value:
            current.pop(key, None)
        else:
            current[key] = value
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}\n" for k, v in sorted(current.items())]
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    tmp.replace(target)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return current


def normalize_repo(repo: str) -> str:
    value = (repo or "").strip()
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/").removesuffix(".git")
    if value.startswith("git@github.com:"):
        value = value.removeprefix("git@github.com:").removesuffix(".git")
    if not _REPO_RE.match(value):
        raise ProductSetupError("GITHUB_REPO must look like owner/name")
    return value


def resolve_local_path(raw: str, *, must_exist: bool = False) -> Path:
    """Expand and validate a local product path.

    Paths must be absolute after expanduser. By default they must stay under
    the user's home directory (FACTORY_ALLOW_ANY_PATH=1 relaxes this for tests).
    """
    if not (raw or "").strip():
        raise ProductSetupError("LOCAL_REPO_PATH is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ProductSetupError("LOCAL_REPO_PATH must be an absolute path")
    path = path.resolve(strict=False)
    allow_any = os.environ.get("FACTORY_ALLOW_ANY_PATH", "").strip() in {"1", "true", "yes"}
    home = Path.home().resolve()
    if not allow_any:
        try:
            path.relative_to(home)
        except ValueError as exc:
            raise ProductSetupError(
                f"LOCAL_REPO_PATH must be under your home directory ({home})"
            ) from exc
    if must_exist and not path.exists():
        raise ProductSetupError(f"path does not exist: {path}")
    return path


def default_clone_dest(repo: str) -> Path:
    owner, name = normalize_repo(repo).split("/", 1)
    home = Path.home()
    for folder in _DEFAULT_PARENTS:
        parent = home / folder
        if parent.is_dir():
            return parent / name
    # Prefer ~/src even if it does not exist yet
    return home / "src" / name


def path_status(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "exists": False,
            "is_git": False,
            "has_factory_yaml": False,
            "has_wo_dir": False,
            "has_agent_process": False,
        }
    wo = path / "docs" / "project_management" / "work_orders"
    return {
        "exists": path.exists(),
        "is_git": (path / ".git").exists()
        or _git_ok(path, "rev-parse", "--is-inside-work-tree"),
        "has_factory_yaml": (path / "factory.yaml").is_file()
        or (path / "docs" / "factory" / "profile.yaml").is_file(),
        "has_wo_dir": wo.is_dir(),
        "has_agent_process": (path / "AGENT_PROCESS.md").is_file(),
    }


def product_status(prefs: dict[str, str] | None = None) -> dict[str, Any]:
    data = dict(prefs or read_prefs())
    # Env wins for live process (same as runner)
    for key in ("GITHUB_REPO", "LOCAL_REPO_PATH", "PREFERRED_AGENT", "WO_PATH"):
        if os.environ.get(key):
            data[key] = os.environ[key].strip()
    repo = (data.get("GITHUB_REPO") or "").strip()
    local_raw = (data.get("LOCAL_REPO_PATH") or "").strip()
    local: Path | None = None
    local_error = ""
    if local_raw:
        try:
            local = resolve_local_path(local_raw)
        except ProductSetupError as exc:
            local_error = str(exc)
    status = path_status(local)
    return {
        "github_repo": repo,
        "local_repo_path": str(local) if local else local_raw,
        "local_path_error": local_error,
        "preferred_agent": data.get("PREFERRED_AGENT", ""),
        "wo_path": data.get("WO_PATH", "docs/project_management/work_orders"),
        "prefs_file": str(PREFS_PATH),
        **status,
        "ready_for_agents": bool(
            repo
            and local
            and status["exists"]
            and status["is_git"]
            and status["has_factory_yaml"]
        ),
        "restart_hint": (
            "After changing LOCAL_REPO_PATH, run `make restart` so Docker remounts "
            "the product checkout, then `make agent-stop && make agent-start`."
        ),
    }


def configure_product(
    *,
    github_repo: str | None = None,
    local_repo_path: str | None = None,
    preferred_agent: str | None = None,
    scaffold: bool = False,
    force_scaffold: bool = False,
    prefs_file: Path | None = None,
) -> dict[str, Any]:
    """Write prefs and optionally scaffold factory adopter files."""
    updates: dict[str, str] = {}
    repo = ""
    if github_repo is not None and github_repo.strip():
        repo = normalize_repo(github_repo)
        updates["GITHUB_REPO"] = repo

    local: Path | None = None
    if local_repo_path is not None and local_repo_path.strip():
        local = resolve_local_path(local_repo_path)
        updates["LOCAL_REPO_PATH"] = str(local)

    if preferred_agent is not None and str(preferred_agent).strip():
        agent = str(preferred_agent).strip().lower()
        if agent not in {"claude", "cursor", "codex", "gemini", "claude-api"}:
            raise ProductSetupError(
                "preferred_agent must be one of claude, cursor, codex, gemini, claude-api"
            )
        updates["PREFERRED_AGENT"] = agent

    if not updates and not scaffold:
        raise ProductSetupError("nothing to update")

    prefs = write_prefs(updates, prefs_file) if updates else read_prefs(prefs_file)
    if not repo:
        repo = (prefs.get("GITHUB_REPO") or "").strip()
    if local is None:
        raw = (prefs.get("LOCAL_REPO_PATH") or "").strip()
        if raw:
            local = resolve_local_path(raw)

    created: list[str] = []
    if scaffold:
        if local is None:
            raise ProductSetupError("LOCAL_REPO_PATH required to scaffold")
        created = _run_factory_init(
            local,
            name=repo.split("/")[-1] if repo else local.name,
            force=force_scaffold,
        )

    result = product_status(prefs)
    result["updated"] = sorted(updates.keys())
    result["scaffolded"] = created
    result["restart_required"] = "LOCAL_REPO_PATH" in updates
    return result


def clone_product(
    github_repo: str,
    dest: str | None = None,
    *,
    token: str = "",
    prefs_file: Path | None = None,
    scaffold: bool = True,
) -> dict[str, Any]:
    """Clone owner/name into dest (or a default under ~) and point prefs at it."""
    repo = normalize_repo(github_repo)
    target = resolve_local_path(dest) if dest else default_clone_dest(repo)
    if target.exists() and any(target.iterdir()):
        if not (target / ".git").exists():
            raise ProductSetupError(
                f"destination exists and is not a git repo: {target}"
            )
        # Already cloned — just point prefs at it
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{repo}.git"
        env = os.environ.copy()
        # Prefer gh when available (uses user login); else git with optional token.
        if shutil.which("gh"):
            cmd = ["gh", "repo", "clone", repo, str(target)]
        else:
            if token.startswith("github_pat_"):
                url = f"https://x-access-token:{token}@github.com/{repo}.git"
            cmd = ["git", "clone", url, str(target)]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProductSetupError(f"clone failed: {exc}") from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "clone failed").strip()
            raise ProductSetupError(err[:500])

    result = configure_product(
        github_repo=repo,
        local_repo_path=str(target),
        scaffold=scaffold,
        force_scaffold=False,
        prefs_file=prefs_file,
    )
    result["cloned_to"] = str(target)
    return result


def _git_ok(cwd: Path, *args: str) -> bool:
    if not cwd.exists():
        return False
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _run_factory_init(path: Path, *, name: str, force: bool) -> list[str]:
    """Call scripts/factory_init.init_product without requiring a package install."""
    engine_root = Path(__file__).resolve().parents[2]
    scripts = engine_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import factory_init as finit  # noqa: WPS433

    path.mkdir(parents=True, exist_ok=True)
    # factory_init refuses to scaffold the engine itself
    return finit.init_product(
        path,
        name=name or path.name,
        force=force,
        sample_wo=True,
    )
