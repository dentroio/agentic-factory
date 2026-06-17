# {{PROJECT_NAME}} — Capability Status

_Last updated: {{YYYY-MM-DD}}_

A living registry of what the system can do, at what fidelity, and what's still open.

---

## How to read this doc

| Symbol | Meaning |
|--------|---------|
| ✅ | Production-ready — tested, deployed, verified |
| 🟡 | Partial — works but has known gaps listed |
| 🔵 | Planned — scoped, not yet built |
| ❌ | Removed / descoped |

---

## Capability Dimensions

### Dimension 1: {{Core Feature Area}}

| Capability | Status | Notes | WO |
|------------|--------|-------|----|
| Feature A | ✅ | | WO-001 |
| Feature B | 🟡 | Gap: {{describe gap}} | WO-002 |
| Feature C | 🔵 | Not yet started | WO-003 |

### Dimension 2: {{Infrastructure / Ops}}

| Capability | Status | Notes | WO |
|------------|--------|-------|----|
| CI/CD pipeline | ✅ | GitHub Actions, 4 blocking checks | — |
| AI code review | ✅ | Claude claude-sonnet-4-6, blocking on "Review required" | — |
| Secret detection | ✅ | Gitleaks on every PR | — |
| Unit tests | 🟡 | Coverage: {{X}}% — target 80% | WO-XXX |
| Integration tests | 🔵 | Not yet implemented | WO-XXX |

---

## Open Gaps

_Gaps that are known but not yet assigned a WO:_

1. {{Gap description}} — impact: {{high/medium/low}}
2. {{Gap description}} — impact: {{high/medium/low}}

---

## Recently Completed

_Last 5 capabilities promoted to ✅:_

| Date | Capability | WO |
|------|------------|----|
| {{YYYY-MM-DD}} | Initial project setup | WO-001 |
