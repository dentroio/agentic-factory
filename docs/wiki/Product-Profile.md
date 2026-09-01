---
title: "Product Profile (factory.yaml)"
description: "How the engine loads verify, UI hints, Compose, and patterns from the product repo"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Product Profile (`factory.yaml`)

The engine is product-agnostic. **Product-specific** behavior (how to verify, which UI to open, Docker Compose project name, codebase patterns) lives in the **product** repository as `factory.yaml` at the repo root (or `docs/factory/profile.yaml`).

The agent runner and orchestrator read that file from the product worktree (`LOCAL_REPO_PATH` / claim worktree). They do **not** hardcode another company’s app.

## Minimal example

```yaml
name: my-app
verify: "make ci-local"
ui_url: "http://localhost:8765"
ui_verify_hint: "Open the app; confirm the change matches the WO."
compose_project: ""          # empty = do not set COMPOSE_PROJECT_NAME
patterns_file: "docs/factory/patterns.md"
```

Ship this in every product you point the factory at. The [template](https://github.com/dentroio/agentic-factory-template) already includes one.

## Fields

| Field | Required | Meaning |
|-------|----------|---------|
| `name` | Recommended | Short product name in PM prompts |
| `verify` | Recommended | Shell command the quality gate runs (default `make ci-local`) |
| `ui_url` | Recommended | Where humans verify UI changes |
| `ui_verify_hint` | Recommended | Plain-English verify steps — **never put passwords here** |
| `compose_project` | Optional | If set, `COMPOSE_PROJECT_NAME` for shared Compose; leave empty for simple apps |
| `patterns_file` | Optional | Markdown path (relative to product root) injected into agent prompts |
| `ui_paths` | Optional | Path prefixes treated as UI (default `frontend/src/`) |
| `api_surface_paths` | Optional | Path prefixes treated as API contract surface |
| `service_patterns` | Optional | List of `{pattern, service}` regex → Compose service for rebuilds |
| `enable_connector_preflight` | Optional | If true, orchestrator may query `connector_api_url` before dispatch |
| `connector_api_url` | Optional | Base URL for connector preflight (only when enabled) |

## Behavior when the file is missing

- Generic prompts (no product-specific patterns file).
- Verify defaults to `make ci-local` if a Makefile exists; otherwise the gate fails with a message pointing at `factory.yaml`.
- No `COMPOSE_PROJECT_NAME` unless you set `compose_project`.

## Patterns file

Create `docs/factory/patterns.md` (or the path in `patterns_file`) with **copy-these-exactly** rules for your codebase: auth helpers, migration registration, commit conventions, conflict magnets. Keep it short and falsifiable.

Example (demo template):

```markdown
## Demo app patterns
Follow `demo/`. Greeting text lives in `demo/public/index.html`.
Keep `make ci-local` green.
```

## Advanced: local overlay

For a one-off machine without committing yaml yet:

```bash
export FACTORY_PROFILE=/absolute/path/to/profile.yaml
```

Prefer committing `factory.yaml` to the product so every clone behaves the same.

## Related

- [Getting Started](Getting-Started) — setup including `LOCAL_REPO_PATH`
- [BYO](../adopters/BYO.md) — existing apps
- [CONTRACT.md](../adopters/CONTRACT.md) — paths and labels
- [Customization](Customization) — review rules and paste-in Actions
