---
name: dashboard-auth-model-status-site
description: Factory status-site dashboard auth model — bearer token OR same-origin loopback Origin, no login page, fails closed on missing API_SECRET
metadata:
  type: project
---

The status-site dashboard (services/status-site) gates mutating requests (non-GET/HEAD/OPTIONS) via `dashboard_auth.py`, authorizing either `Authorization: Bearer <API_SECRET>` or a same-origin `Origin`/`Referer` matching `http://127.0.0.1:8099` / `http://localhost:8099`. There is intentionally no login page/session — the human operator uses the browser UI unauthenticated (relying on same-origin), while scripts/agents/orchestrator use the bearer secret. The app now fails closed at import time (`dashboard_auth.require_secret`) if `API_SECRET` is unset, so the service won't boot without it — this is a deliberate behavior change (previously `API_SECRET` was optional).

**Why:** Avoids forcing operators to paste API_SECRET into a browser (which would leak it via history/logs) while still preventing CSRF from other origins and unauthenticated curl access. `docker-compose.status.yml` binds the port to `127.0.0.1:8099` only, not `0.0.0.0`, as a second layer of defense — origin checks alone aren't enough if the port is publicly exposed.

**How to apply:** If touching status-site auth, port bindings, or adding new mutating routes: (1) don't add