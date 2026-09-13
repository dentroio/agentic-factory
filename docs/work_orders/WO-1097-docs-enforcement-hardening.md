# WO-1097 — Docs enforcement hardening (mandate, parser, Doc Writer)

**Created:** 2026-09-07
**Priority:** P2
**Effort:** S
**Services:** agent-runner, status-site, scripts
**Depends on:** WO-1023
**Status:** 🟡 In Progress

---

## Problem

Documentation enforcement exists but has holes that let wiki / in-app help drift:

1. Coding agents only see `## Documentation Required` buried in the WO markdown — no explicit **DOCUMENTATION MANDATE** (promised by WO-1023 / Customization wiki).
2. `_parse_docs_required` treats `- None` / `N/A` as real checklist items, which can spuriously fail the documentation reviewer.
3. Doc Writer crashes with `StopIteration` when Claude returns a message with no text block (observed 2026-09-05).

Separately (product repo): Clarion `DOC_MAP.json` `new_ui_page` still points at a non-existent `frontend/src/components/help/` path instead of `wiki/docs/` + `inAppHelpMap.ts`.

## What to Build

1. Parse docs-required items in `prompt_builder` and inject a **DOCUMENTATION MANDATE** when non-empty.
2. Harden `_parse_docs_required` (status-site) to skip None/N/A/empty sentinels; share the same skip rules in the prompt parser.
3. Harden `scripts/doc_writer.py` `call_claude` against empty content blocks (log + skip page).
4. Unit tests for parser + mandate presence/absence.
5. Wiki Customization: note DOC_MAP → wiki/docs + help mirror; document None sentinel.

## Out of scope

- Rewriting existing Clarion WO specs to add Documentation Required
- Changing documentation reviewer severity/rules
- Factory dashboard Guide UI (WO-1096)

## Acceptance Criteria

- [x] `build_prompt` includes `DOCUMENTATION MANDATE` when the WO markdown has real docs-required items
- [x] `- None` / `N/A` / empty sections produce no mandate and empty `docs_required` parse
- [x] Doc Writer does not crash on empty Claude responses (returns skip / empty string safely)
- [x] Unit tests cover the above
- [x] Customization wiki updated
- [x] `docs/project_management/BACKLOG.md` — WO-1097 entry
- [ ] `make ci-local` passes

## Documentation Required

- [x] `docs/wiki/Customization.md` — documentation enforcement + DOC_MAP / help mirror note
- [x] `docs/project_management/CAPABILITY_STATUS.md` — note hardening
- [x] `docs/project_management/BACKLOG.md` — WO-1097 entry

## Execution

- **Branch:** `wo/1097-docs-enforcement-hardening`
- **Risk tier:** P2
- **PR title:** `fix(docs): WO-1097 — docs mandate, None parser, Doc Writer resilience`
- **Auto-merge:** yes (after human verifies)
- **PM docs:** CAPABILITY_STATUS.md, BACKLOG.md

**Product follow-up (Clarion, separate PR):** update `docs/factory/DOC_MAP.json` `new_ui_page` to `wiki/docs/` + `frontend/src/lib/inAppHelpMap.ts`.
