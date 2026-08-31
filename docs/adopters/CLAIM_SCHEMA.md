# Claim file schema — `docs/factory/runs/WO-{NNN}.json`

Every agent that claims a WO writes this file **before** product code. The factory status site reads it from the branch.

## File naming

```
docs/factory/runs/WO-{NNN}.json
```

## Schema

```json
{
  "wo": 1,
  "title": "Title from the spec heading",
  "agent": "cursor",
  "agent_platform": "cursor-ide",
  "status": "in_progress",
  "step": "starting",
  "started_at": "2026-08-30T12:00:00Z",
  "last_updated": "2026-08-30T12:00:00Z",
  "branch": "wo/1-short-slug",
  "notes": ""
}
```

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `wo` | integer | Yes | WO number |
| `title` | string | Yes | From the spec heading |
| `agent` | string | Yes | `claude-code`, `cursor`, `codex`, `human` |
| `agent_platform` | string | Yes | e.g. `claude-code-cli`, `cursor-ide`, `github-actions` |
| `status` | enum | Yes | `in_progress`, `blocked`, `complete`, `abandoned` |
| `step` | string | Yes | kebab-case: `starting`, `implementing`, `writing-tests`, `fixing-ci`, `waiting-for-review`, `done` |
| `started_at` | ISO 8601 | Yes | UTC claim time |
| `last_updated` | ISO 8601 | Yes | Update on each phase change |
| `branch` | string | Yes | Full branch name |
| `notes` | string | If blocked/abandoned | Why |

## Status values

| Value | Meaning |
|-------|---------|
| `in_progress` | Agent is working |
| `blocked` | Stuck; `notes` required |
| `complete` | Set on the implementation PR (before merge) |
| `abandoned` | Stopped; `notes` required |

First commit message: `docs(factory): claim WO-NNN`.
