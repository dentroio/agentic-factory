"""Product profile loader — Clarion-specific behavior comes from the product worktree.

Reads `factory.yaml` (or `docs/factory/profile.yaml`) from the product repo root.
Until a product ships its own file, a local-only overlay is allowed:

  FACTORY_PROFILE=/path/to/profile.yaml
  FACTORY_LEGACY_PRODUCT=dentroio/clarion   # temporary; enables legacy patterns only
                                            # when GITHUB_REPO matches this value
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover — PyYAML is in runner image; tests may stub
    yaml = None  # type: ignore

_GENERIC_PATTERNS = """## Product codebase patterns

Follow existing patterns in this repository exactly — naming, file layout,
error handling, and abstraction level. Do not invent parallel structures.

### Security & data
- Never hardcode secrets, API keys, or passwords
- Prefer parameterized queries / safe ORM APIs over string-built SQL
- Protect new API routes with the project's existing auth dependencies

### Process
- Read AGENT_PROCESS.md (or docs/adopters/PROCESS.md) in this product repo
- Run only the verify command the quality gate will run — do not invent CI targets
""".strip()

_PROFILE_FILENAMES = ("factory.yaml", "docs/factory/profile.yaml")


@dataclass
class FactoryProfile:
    name: str = ""
    verify: str = "make ci-local"
    ui_url: str = "http://localhost:8765"
    ui_verify_hint: str = "Open the app; confirm the change matches the WO."
    compose_project: str = ""
    patterns_file: str = "docs/factory/patterns.md"
    # Optional product-specific extras (Clarion rebuild map, connectors API, etc.)
    service_patterns: list[tuple[str, str]] = field(default_factory=list)
    api_surface_paths: list[str] = field(default_factory=list)
    ui_paths: list[str] = field(default_factory=lambda: ["frontend/src/"])
    enable_connector_preflight: bool = False
    connector_api_url: str = ""
    source: str = "defaults"  # defaults | file | legacy | env

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        repo = os.getenv("GITHUB_REPO", "").strip()
        if repo:
            return repo.rsplit("/", 1)[-1]
        return "product"


def _github_repo() -> str:
    return os.getenv("GITHUB_REPO", "").strip()


def is_legacy_product() -> bool:
    """True when this factory instance is still on the configured live product."""
    legacy = os.getenv("FACTORY_LEGACY_PRODUCT", "").strip()
    repo = _github_repo()
    if not legacy or not repo:
        return False
    return legacy.lower() == repo.lower()


def _parse_yaml(text: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load factory.yaml")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("factory profile must be a YAML mapping")
    return data


def _coerce_service_patterns(raw: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            pattern = str(item.get("pattern") or item.get("path") or "").strip()
            svc = str(item.get("service") or item.get("svc") or "").strip()
            if pattern and svc:
                out.append((pattern, svc))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            out.append((str(item[0]), str(item[1])))
    return out


def _from_mapping(data: dict[str, Any], source: str) -> FactoryProfile:
    ui_paths = data.get("ui_paths")
    if isinstance(ui_paths, list):
        paths = [str(p) for p in ui_paths if str(p).strip()]
    else:
        paths = ["frontend/src/"]
    api_paths = data.get("api_surface_paths")
    if isinstance(api_paths, list):
        apis = [str(p) for p in api_paths if str(p).strip()]
    else:
        apis = []
    return FactoryProfile(
        name=str(data.get("name") or "").strip(),
        verify=str(data.get("verify") or "make ci-local").strip() or "make ci-local",
        ui_url=str(data.get("ui_url") or "http://localhost:8765").strip(),
        ui_verify_hint=str(
            data.get("ui_verify_hint")
            or "Open the app; confirm the change matches the WO."
        ).strip(),
        compose_project=str(data.get("compose_project") or "").strip(),
        patterns_file=str(data.get("patterns_file") or "docs/factory/patterns.md").strip(),
        service_patterns=_coerce_service_patterns(data.get("service_patterns")),
        api_surface_paths=apis,
        ui_paths=paths or ["frontend/src/"],
        enable_connector_preflight=bool(data.get("enable_connector_preflight", False)),
        connector_api_url=str(data.get("connector_api_url") or "").strip(),
        source=source,
    )


def _legacy_clarion_profile() -> FactoryProfile:
    """Temporary Clarion defaults when FACTORY_LEGACY_PRODUCT matches GITHUB_REPO."""
    return FactoryProfile(
        name="clarion",
        verify="make ci-local",
        ui_url="https://localhost",
        ui_verify_hint="Open the app and verify the UI change. Use your local admin credentials (never paste passwords into prompts or git).",
        compose_project="clarion",
        patterns_file="",  # loaded from engine clarion_patterns.md when present
        service_patterns=[
            (r"^frontend/", "frontend"),
            (r"^services/data-service/|^src/clarion/", "data-service"),
            (r"^services/correlation-service/|^src/clarion/endpoints/correlation_engine", "correlation-service"),
            (r"^services/clustering-service/", "clustering-service"),
            (r"^services/connector-service/", "connector-service"),
            (r"^services/user-service/", "user-service"),
            (r"^services/gateway/", "gateway"),
            (r"^services/ai-service/", "ai-service"),
            (r"^services/monitoring-service/", "monitoring-service"),
            (r"^services/telemetry-ingest-service/", "telemetry-ingest-service"),
            (r"^services/policy-service/", "policy-service"),
        ],
        api_surface_paths=[
            "src/clarion/api/routes/",
            "src/clarion/api/schemas/",
            "services/data-service/routes/",
            "services/gateway/routes/",
        ],
        ui_paths=["frontend/src/"],
        enable_connector_preflight=True,
        connector_api_url=os.getenv("CLARION_API_URL", "http://localhost:8000"),
        source="legacy",
    )


def _generic_service_patterns() -> list[tuple[str, str]]:
    return [
        (r"^frontend/", "frontend"),
        (r"^services/([^/]+)/", r"\1"),  # note: used specially — see detect_services
    ]


def find_profile_path(worktree: str | Path | None) -> Path | None:
    """Resolve profile path: FACTORY_PROFILE env, then worktree factory.yaml."""
    env_path = os.getenv("FACTORY_PROFILE", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_file():
            return p
    if not worktree:
        return None
    root = Path(worktree)
    for name in _PROFILE_FILENAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def load_profile(worktree: str | Path | None = None) -> FactoryProfile:
    """Load product profile for the given worktree (or LOCAL_REPO_PATH)."""
    root = worktree
    if root is None:
        root = os.getenv("LOCAL_REPO_PATH", "").strip() or None

    path = find_profile_path(root)
    if path is not None:
        try:
            data = _parse_yaml(path.read_text(encoding="utf-8"))
            return _from_mapping(data, source=f"file:{path}")
        except Exception as e:
            print(f"[factory_profile] failed to load {path}: {e}")

    if is_legacy_product():
        return _legacy_clarion_profile()

    # Generic defaults — no product-specific rebuild map
    profile = FactoryProfile(source="defaults")
    profile.service_patterns = [
        (r"^frontend/", "frontend"),
        (r"^services/([^/]+)/", "CAPTURE"),  # special marker handled in quality_gate
    ]
    return profile


def load_patterns_text(worktree: str | Path | None, profile: FactoryProfile | None = None) -> str:
    """Return patterns markdown for agent prompts."""
    profile = profile or load_profile(worktree)
    root = Path(worktree) if worktree else None

    # Explicit patterns_file from profile (product-owned)
    if profile.patterns_file and root:
        candidate = root / profile.patterns_file
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8").strip()
            except OSError:
                pass

    # Legacy: engine-bundled clarion_patterns.md only for the live Clarion instance
    if profile.source == "legacy" or is_legacy_product():
        legacy_file = Path(__file__).parent / "clarion_patterns.md"
        if legacy_file.is_file():
            try:
                return legacy_file.read_text(encoding="utf-8").strip()
            except OSError:
                pass

    return _GENERIC_PATTERNS


def verify_argv(profile: FactoryProfile) -> list[str]:
    """Split profile.verify into argv for subprocess."""
    return shlex.split(profile.verify)


def apply_compose_project(env: dict, profile: FactoryProfile) -> dict:
    """Set COMPOSE_PROJECT_NAME only when the profile names one."""
    out = dict(env)
    if profile.compose_project:
        out.setdefault("COMPOSE_PROJECT_NAME", profile.compose_project)
    else:
        out.pop("COMPOSE_PROJECT_NAME", None)
    return out


def detect_services_from_paths(changed: list[str], profile: FactoryProfile) -> list[str]:
    """Map changed paths to compose service names using the profile."""
    import re

    services: set[str] = set()
    patterns = profile.service_patterns or [
        (r"^frontend/", "frontend"),
        (r"^services/([^/]+)/", "CAPTURE"),
    ]
    for path in changed:
        for pattern, svc in patterns:
            m = re.match(pattern, path)
            if not m:
                continue
            if svc == "CAPTURE":
                services.add(m.group(1))
            elif "\\" in svc or svc.startswith(r"\1"):
                services.add(m.expand(svc) if hasattr(m, "expand") else m.group(1))
            else:
                services.add(svc)
    return sorted(services)
