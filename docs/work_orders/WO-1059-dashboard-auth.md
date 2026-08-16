# WO-1059 — Dashboard authentication (AF-08)

**Created:** 2026-08-15
**Priority:** P0
**Effort:** S
**Services:** status-site, docs
**Depends on:** WO-1058
**Status:** 🟡 In Progress

---

## Background

AF-08: the dashboard is a confused deputy. It holds `API_SECRET` and forwards writes to the loopback-bound orchestrator with the bearer attached.

Loopback bind for `8099` is already in `docker-compose.status.yml` (`127.0.0.1:8099:8099`). The remaining hole is **42 write endpoints with no authentication** in `services/status-site/main.py`. `API_SECRET` is used only as a client credential to the orchestrator.

`API_SECRET` is a machine token (Keychain, agent runner, orchestrator). It is **not** a human password. The operator must be able to open `http://127.0.0.1:8099` with no login form.

Without a write gate, anything that can reach `127.0.0.1:8099` — including a CSRF form from another site the operator has open — can pause/resume the factory, replace GitHub tokens, dispatch WOs, and approve validations.

## What to Build

1. Fail closed if `API_SECRET` is missing (same rule as the orchestrator) so this process cannot proxy unauthenticated.
2. Middleware: **GET/HEAD/OPTIONS** stay open on loopback. **POST/PUT/PATCH/DELETE** require `Authorization: Bearer <API_SECRET>` **or** `Origin`/`Referer` of `http://127.0.0.1:8099` / `http://localhost:8099`.
3. No login page. No session cookie. No pasting `API_SECRET` into the browser.
4. Bind remains loopback. Correct README / wiki claims.

Do **not** start the agent runner, unpause dispatch, or run `make agent-setup`.

## Requirements

```yaml
requires:
  connectors: []
  services: []
```

## Domain Notes

- Browser `fetch()` and HTML forms send `Origin` on writes; the dashboard JS does not need a Bearer header.
- JSON clients (curl, future Oryntra) send the bearer header.
- Conflict-magnet: do not edit `services/orchestrator/orchestrator.py`.

## Acceptance Criteria

- [ ] `GET http://127.0.0.1:8099/` returns 200 with no login
- [ ] `POST /api/factory/resume` with no Origin and no bearer returns 401
- [ ] `POST /api/factory/resume` with `Origin: http://127.0.0.1:8099` is accepted by the gate (do not actually resume)
- [ ] Dashboard still bound to `127.0.0.1:8099`
- [ ] `make ci-local` passes

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/status-site/dashboard_auth.py` | Origin + bearer write gate |
| Create | `tests/unit/test_dashboard_auth.py` | Guards |
| Modify | `services/status-site/main.py` | Install auth, fail closed |
| Modify | `README.md` | Security model |
| Modify | `docs/wiki/Dashboard-Guide.md` | No login |
| Modify | `docs/ORYNTRA_FACTORY_INTEGRATION.md` | Proxy writes require auth |

## Execution

- **Branch:** `wo/1059-dashboard-auth`
- **Risk tier:** P0 — human must approve and merge
- **PR title:** `fix(security): WO-1059 — authenticate the factory dashboard`
- **Pre-PR gate:** `make ci-local`
- **Depends on:** WO-1058
- **PM docs to update:** PROGRESS.md

### UI Verification

1. Open **http://127.0.0.1:8099** — expected: Overview loads, **no sign-in page**
2. Factory tab still shows **paused**
3. Confirm `curl -X POST http://127.0.0.1:8099/api/factory/resume` returns **401**
4. Do not click Resume
