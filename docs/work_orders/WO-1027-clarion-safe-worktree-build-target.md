# WO-1027 — Clarion: Safe Worktree Container Build Makefile Target

**Created:** 2026-07-18
**Priority:** P2
**Effort:** S
**Services:** clarion/Makefile, clarion/scripts/
**Depends on:** none
**Status:** ✅ Done

---

## Background

When an agent works in a worktree (`.worktrees/wo-NNN-slug/`) and needs to rebuild a container to test their changes, there is no safe Makefile target. The standard `make build-svc SVC=frontend` reads the primary directory, not the worktree — so it builds the wrong code.

The workaround is to manually run:
```bash
docker build -f .worktrees/wo-NNN/frontend/Dockerfile -t clarion-frontend .worktrees/wo-NNN/frontend/
docker compose -p clarion up -d --no-build --force-recreate --no-deps frontend
```

This has caused two categories of accidents this week:

1. **Wrong build context**: `docker build -f worktree/frontend/Dockerfile -t clarion-frontend worktree/` (forgot the context path is `frontend/` not root) — build fails silently or uses wrong COPY paths.
2. **Missing `--no-deps`**: `docker compose up --force-recreate frontend` without `--no-deps` caused Docker to recreate vault and connector-service as dependencies, wiping the `CLARION_MIGRATIONS_DONE` vault flag and taking data-service down for several minutes.

Agents should never have to know the correct incantation. The Makefile should encode it.

---

## What to Build

### 1. Add `build-svc-wt` target to Clarion's Makefile

```makefile
# Build and hot-swap a single service from the current worktree.
# Usage (from inside a worktree):  make -C /path/to/primary build-svc-wt SVC=frontend
# Or from the worktree itself:     make build-svc-wt SVC=frontend
#
# Detects the worktree root automatically from the current directory.
# Replaces only the named container — never restarts dependencies.
build-svc-wt:
ifndef SVC
	$(error SVC is required. Usage: make build-svc-wt SVC=frontend)
endif
	$(eval WT_ROOT := $(shell git worktree list --porcelain | grep "$(CURDIR)" | head -1 | awk '{print $$2}' || echo "$(CURDIR)"))
	$(eval SVC_DIR := $(WT_ROOT)/$(call _svc_subdir,$(SVC)))
	$(eval IMG_NAME := $(call _image_name,$(SVC)))
	@echo "→ Building $(IMG_NAME) from $(SVC_DIR)"
	docker build -f $(SVC_DIR)/Dockerfile -t $(IMG_NAME) $(SVC_DIR)
	@echo "→ Hot-swapping $(SVC) container (no-deps, force-recreate)"
	docker compose -p clarion up -d --no-build --force-recreate --no-deps $(SVC)
	@echo "✅ $(SVC) rebuilt and swapped"

# Map service names to their subdirectory and image name
_svc_subdir = $(if $(filter frontend,$(1)),frontend,services/$(1))
_image_name  = $(if $(filter frontend,$(1)),clarion-frontend,clarion-$(1))
```

### 2. Add service-to-context mapping for services with non-standard build contexts

Some services (like `frontend`) use the subdirectory as their Docker build context, not the repo root. The mapping in `_svc_subdir` handles this. Add entries for any service where the Dockerfile context differs from the directory:

| Service | Dockerfile location | Build context |
|---------|-------------------|---------------|
| `frontend` | `frontend/Dockerfile` | `frontend/` |
| `data-service` | `services/data-service/Dockerfile` | `.` (repo root, needs `src/`) |
| All others | `services/<name>/Dockerfile` | `services/<name>/` |

For `data-service` and any service needing the repo root as context, adjust `_svc_subdir` accordingly.

### 3. Update `AGENT_PROCESS.md` in Clarion

Replace the manual docker command in the "Files you changed → frontend" row with:

```
make build-svc-wt SVC=frontend   # from inside the worktree
```

Add a warning box:
> ⚠️ **Never run `docker compose up` from a worktree without `--no-deps`.** It will recreate dependency containers (vault, pgbouncer) and may wipe shared state. Always use `make build-svc-wt` instead.

### 4. Update `wo_start.sh` to print the correct build command

At the end of `wo_start.sh`, update the "Next steps" output to show `make build-svc-wt` instead of `make build-svc`:

```bash
echo "  make build-svc-wt SVC=<service>   # rebuild from this worktree (safe)"
```

---

## Acceptance Criteria

- [ ] `make build-svc-wt SVC=frontend` from inside a worktree builds the frontend image from the worktree's `frontend/` directory
- [ ] `make build-svc-wt SVC=frontend` restarts only the frontend container — no other containers are touched
- [ ] `make build-svc-wt SVC=data-service` builds from the worktree with the correct build context (repo root)
- [ ] Running without `SVC=` prints a clear error message
- [ ] `AGENT_PROCESS.md` updated with the new target and the no-deps warning
- [ ] `wo_start.sh` "Next steps" shows `make build-svc-wt`

## Documentation Required

- [ ] `AGENT_PROCESS.md` in Clarion — replace manual docker commands with `make build-svc-wt`; add `--no-deps` warning
