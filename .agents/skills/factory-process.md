# Skill: Factory Process

> Canonical source of truth: `AGENT_PROCESS.md`. This skill is a compact reference for Antigravity agents.

## Risk tiers

| Tier | Scope | Branch | Merge |
|------|-------|--------|-------|
| P0 | Auth, security, breaking contracts | `fix/` or `wo/` | Human only |
| P1 | DB migrations, new API routes, cross-service interfaces | `wo/` | Human only |
| P2 | Features, UI, tests, refactors | `wo/` | Auto-merge after CI |
| P3 | Docs, PM files, comments | None (direct to main) | Direct push |

## Branch naming

```
wo/NNN-short-description     # Work Order
fix/short-description        # Hotfix
feat/short-description       # Feature without WO
```

## Commit message format

```
type(scope): WO-NNN — Short description

Optional body.

Co-Authored-By: Gemini <noreply@google.com>
```

Types: `feat`, `fix`, `docs`, `chore`, `test`, `refactor`

## Local CI gate

Run before every PR:

```bash
make ci-local
```

## Parallel agent coordination

- **One agent per service** — branch existence means claimed
- **Sequential-only files:** migration runner, route registry, PROGRESS.md, Makefile
- Check active branches before starting: `git branch -r | grep wo/`

## After merge

```bash
make sync   # pull latest main + rebuild containers
```
