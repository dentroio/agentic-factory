# WO-1023 — Documentation Completeness Enforcement

**Created:** 2026-07-09
**Priority:** P1
**Effort:** M
**Status:** ✅ Complete
**Services:** orchestrator, agent-runner
**Depends on:** WO-1021 (SQLite queue), WO-1022 (PM situational awareness — DOC_MAP injection)

---

## Background

A WO is currently marked "done" when its code merges. No step in the runner workflow verifies that documentation was updated. The result is documentation debt accumulating silently with every WO:

- New API endpoints appear without entries in the architecture overview
- New env vars appear without README entries
- New UI pages ship without in-app help content
- Architecture changes happen without corresponding doc updates

The PM agent (after WO-1022) will emit a `Documentation Required` checklist in acceptance criteria when it detects relevant triggers from `DOC_MAP.json`. But nothing enforces that the coding agent actually fulfilled those items before requesting human validation.

This WO adds two enforcement layers:
1. A `docs_required` field in the queue DB (tracks what docs a WO must update)
2. A documentation reviewer step that runs as part of the review chain, verifying doc updates before human validation is requested

---

## What to Build

### 1. Add `docs_required` column to the `queue` table

```sql
ALTER TABLE queue ADD COLUMN docs_required TEXT DEFAULT '[]';  -- JSON array of {file, action} objects
```

When a WO spec is created (via `create_wo()`), parse the `Documentation Required` section from the spec markdown and store it as JSON in `docs_required`. The runner reads this when executing the WO.

### 2. Parse `Documentation Required` from WO specs

In `prompt_builder.py` or `runner.py`, add `_parse_docs_required(spec_markdown: str) -> list[dict]`:

```python
def _parse_docs_required(markdown: str) -> list[dict]:
    """Extract Documentation Required checklist items from a WO spec."""
    m = re.search(
        r"^## Documentation Required\s*\n(.*?)(?=\n^##|\Z)",
        markdown, re.MULTILINE | re.DOTALL
    )
    if not m:
        return []
    items = []
    for line in m.group(1).splitlines():
        line = line.strip().lstrip("- [ ]").strip()
        if line:
            items.append({"item": line, "completed": False})
    return items
```

### 3. Add a documentation reviewer to the review chain

In `review_chain.py`, add a fifth reviewer role: `"documentation"`. It runs after the four existing reviewers (security, architecture, correctness, performance) for all non-P3 WOs.

The documentation reviewer has a different job from the others: it doesn't look for code bugs — it checks whether the diff includes updates to the documentation files listed in `docs_required`.

```python
DOC_REVIEWER_PROMPT = """You are a documentation completeness reviewer.

You have been given:
- The WO specification's Documentation Required section: {docs_required}
- A git diff of all changes made

Your ONLY job: for each item in Documentation Required, check whether the diff contains a meaningful update to the specified file or section.

For each item NOT addressed in the diff, output:
FINDING: {"severity": "HIGH", "file": "<file from docs_required>", "line": 0, "issue": "Documentation Required item not completed: <item text>", "fix": "Update <file> as specified in the WO's Documentation Required section"}

If all items are addressed, or if Documentation Required is empty, output:
VERDICT: LGTM — all documentation requirements fulfilled.

Do not flag stylistic issues or suggest improvements beyond what was explicitly required.
"""
```

Blocking severity for documentation reviewer: `HIGH` only (missing a doc update is HIGH, not CRITICAL — a missing README entry doesn't break production, but it shouldn't be ignored).

### 4. Pass `docs_required` into the review chain

Update `run_review_chain()` signature:

```python
async def run_review_chain(
    wo_spec: dict,
    diff: str,
    monitor: ThreadMonitor,
    previous_findings: list[dict],
    coding_backend: str = "",
    docs_required: list[dict] | None = None,
) -> tuple[bool, list[dict]]:
```

The documentation reviewer prompt is built using the `docs_required` list. If `docs_required` is empty or None, the documentation reviewer step is skipped.

### 5. Update `runner.py` to pass `docs_required`

The runner already fetches the WO spec from the orchestrator. After WO-1021, it can also fetch `docs_required` from `GET /api/queue/{wo}`. Pass it into `run_review_chain()`.

### 6. Update the agent prompt to include `Documentation Required`

In `prompt_builder.py`, if the WO spec has a `Documentation Required` section, add it explicitly to the prompt mandate:

```
DOCUMENTATION MANDATE
The following documentation files must be updated as part of this WO:
{docs_required items}
Do not call POST /api/validate until all items above are checked off.
```

This ensures the coding agent knows about and acts on documentation requirements — not just reads them and ignores them.

---

## Acceptance Criteria

- [ ] `queue` table has `docs_required` column; `create_wo()` populates it by parsing the spec
- [ ] `_parse_docs_required()` correctly extracts items from `## Documentation Required` sections
- [ ] Documentation reviewer runs after the 4 existing reviewers for P0/P1/P2 WOs
- [ ] Documentation reviewer returns HIGH finding for each unfulfilled `docs_required` item
- [ ] HIGH finding from documentation reviewer blocks the chain (agent must fix before human review)
- [ ] Documentation reviewer is skipped when `docs_required` is empty
- [ ] Coding agent prompt includes the `docs_required` list as a mandatory checklist
- [ ] `make smoke-test` passes after rebuild

## Documentation Required

- [ ] Update `docs/TECHNICAL_ARCHITECTURE.md` — add documentation reviewer to the review chain table; update execution flow diagram; add `docs_required` column to the queue DB schema section
- [ ] Update `docs/TECHNICAL_ARCHITECTURE.md` — update agent mandate section to include documentation mandate
