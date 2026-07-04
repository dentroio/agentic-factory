# WO-371 — Quality Gate: Mandatory CI + Security Before Human Review

**Status:** ✅ Complete
**Priority:** P1
**Effort:** S (half day)
**Services:** orchestrator, agent-runner
**Depends on:** WO-365

---

## Problem

The agent runner calls `/api/validate` to request human sign-off, but there was
nothing preventing an agent from submitting broken or insecure code for review.
Humans would see a "needs review" badge without knowing whether CI had even run.

Code quality and security are 100% non-negotiable factory goals. Every WO must
pass CI and a security scan before a human ever sees it.

---

## What Was Done

### Orchestrator — enforce the gate at the API boundary

`ValidateRequest` gained three new fields:

```
ci_passed: bool = True
security_passed: bool = True
thread_summary: str = ""
```

`/api/validate` now returns **HTTP 422** if either gate fails:

```json
{
  "detail": "Quality gate not met: CI checks failed; security scan found CRITICAL or HIGH findings"
}
```

Both fields are stored in the validation record so the status site can display
CI ✅ / Security ✅ badges on the review queue card.

### Agent runner — `quality_gate.py`

New module runs three checks **in parallel** before calling `/api/validate`:

| Check | Tool | Blocks on |
|-------|------|-----------|
| CI | `make ci-local` (600 s timeout) | non-zero exit |
| Python security | `bandit -r . -f json` | CRITICAL or HIGH findings |
| Multi-language | `semgrep --config auto` (skipped if not installed) | ERROR or WARNING findings |

`run_quality_gate(worktree)` returns:

```python
{
    "ci_passed": bool,
    "security_passed": bool,   # bandit AND semgrep
    "ci_output": str,          # last 3000 chars
    "bandit_findings": list,
    "semgrep_findings": list,
    "finding_count": int,
}
```

### `runner.py` — gate before validate

```
agent run complete
  → run_quality_gate()         ← new step
  → if gate fails: checkin("quality gate failed: ..."), return
  → request_validate(ci_passed=..., security_passed=...)
  → poll for human decision
```

If the gate fails the runner logs the failure, updates the checkin step, and
returns without calling `/api/validate`. The WO stays in `in_progress` state
and the agent must be re-run after fixes.

### Bandit added to agent-runner `requirements.txt`

`bandit>=1.7.0` is installed in the Docker image. `semgrep` is optional — if
not installed the check is silently skipped (pass).

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| 1 | `POST /api/validate` with `ci_passed: false` returns HTTP 422 |
| 2 | `POST /api/validate` with `security_passed: false` returns HTTP 422 |
| 3 | `POST /api/validate` with both `true` returns HTTP 200 |
| 4 | `quality_gate.py` runs bandit; CRITICAL/HIGH findings set `security_passed=False` |
| 5 | `run_quality_gate()` runs CI + bandit + semgrep in parallel |
| 6 | Runner calls gate before validate; gate failure stops the validate call |
| 7 | `bandit` installed in agent-runner Docker image |

---

## Execution

- **Branch:** `wo/371-quality-gate` (agentic-factory)
- **PR:** see GitHub
- **Risk tier:** P2 — modifies orchestrator API (backwards-compatible: defaults preserve existing behaviour)
