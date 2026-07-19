# WO-1032 — AGENT_PROCESS.md Condensation and Agent-Readability Pass

**Created:** 2026-07-18
**Priority:** P2
**Effort:** M
**Services:** clarion/docs (no code change)
**Depends on:** WO-1027, WO-1028
**Status:** ✅ Done

---

## Background

`AGENT_PROCESS.md` is the single source of truth for how agents operate in the Clarion repository. Agents are instructed to read it at the start of every task. The problem: it has grown to several thousand words with dense sections on risk tiers, branch workflow, PR lifecycle, build patterns, and code patterns. A fresh agent context window reading it in full pays a significant cost, and key facts are buried.

This session surfaced two cases where agents (Claude Code) missed critical facts that were in `AGENT_PROCESS.md` but overlooked:
1. `--no-deps` requirement when force-recreating containers from a worktree
2. The double-rebuild requirement when editing `correlation_engine.py`

The doc is also structured for human authoring convenience (narrative prose) rather than agent parsing (short, imperative blocks). It mixes "why" explanations (useful once) with "what to do" rules (needed every time).

---

## What to Build

### 1. Split AGENT_PROCESS.md into two files

**`AGENT_PROCESS.md`** (the "what to do" cheatsheet — keep short):
- Risk tiers table
- Branch/PR workflow (as a numbered list, no prose)
- Container rebuild table (SVC → make target → verify command)
- Critical code patterns (bulleted, no explanation)
- "Stop and ask user" rule
- Emergency ops reference (who to page, where logs are)

**`AGENT_PROCESS_DETAIL.md`** (the "why" reference — optional reading):
- Detailed explanation of the worktree system
- Why `db.commit()` is always required
- Why `correlation_engine.py` lives in two containers
- Why `--no-deps` is required
- Migration registration explanation
- Role guard explanation

Agent prompt (in CLAUDE.md): *"Read `AGENT_PROCESS.md` before starting any implementation task. If you need the reasoning behind a rule, see `AGENT_PROCESS_DETAIL.md`."*

### 2. Convert all "what to do" sections to imperative command lists

Replace every prose paragraph in `AGENT_PROCESS.md` with a short command or rule. For example:

Before:
> When you are working in a worktree and need to rebuild a container, you must be careful not to use the standard `make build-svc` target because it reads the primary directory, not the worktree. Instead, use...

After:
> **Rebuild from worktree:** `make build-svc-wt SVC=<service>` — never `make build-svc` from inside a worktree.

### 3. Move the "critical patterns" table to the top of the file

Agents miss things at the bottom of long docs. The five must-not-forget patterns (db.commit, migration registration, require_role, correlation_engine double-rebuild, claim file first commit) should be within the first 30 lines of the file with a `## ⚠️ You must know these` header.

### 4. Add a "Container danger zones" section

Explicitly list the operations that have caused incidents this week:

```
## ⚠️ Container danger zones (do not skip)

| Dangerous command | Safe replacement | What goes wrong |
|---|---|---|
| `docker compose up -d --force-recreate <svc>` | `make build-svc-wt SVC=<svc>` | Recreates vault/pgbouncer as deps — wipes migrations flag |
| `docker start <container>` after re-tagging image | `docker compose up -d --no-build --force-recreate --no-deps <svc>` | Uses old image — change not visible |
| `make build-svc SVC=X` from a worktree | `make build-svc-wt SVC=X` | Builds from main tree, not worktree — no change |
```

### 5. Add step numbers to the WO workflow

Replace the current unlabeled workflow steps with explicit numbered steps (Step 1 through Step 8) so agents can reference them unambiguously in status updates and log lines.

---

## Acceptance Criteria

- [ ] `AGENT_PROCESS.md` is under 200 lines
- [ ] `AGENT_PROCESS_DETAIL.md` exists and contains all moved explanations
- [ ] Critical patterns section is within the first 30 lines of `AGENT_PROCESS.md`
- [ ] Container danger zones table is present
- [ ] All prose paragraphs in `AGENT_PROCESS.md` replaced with imperative lists
- [ ] WO workflow has explicit step numbers
- [ ] `CLAUDE.md` updated to reference both files appropriately
- [ ] No factual content is lost in the condensation

## Documentation Required

- [ ] This WO is itself documentation work — no code docs needed
- [ ] After merge, update factory prompt template to reference the new two-file structure
