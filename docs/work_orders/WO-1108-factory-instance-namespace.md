# WO-1108 — Run more than one factory on a machine (instance namespace)

**Status:** In Progress (part 1: secrets, prefs, ports, compose, Make)
**Priority:** P1
**Effort:** M
**Services:** scripts | docker-compose | agent-runner | status-site | orchestrator
**Depends on:** none (separate from WO-1107, product Work Order Protocol support)

## Problem

A second factory checkout on the same Mac shares the first one's state:
`~/.config/factory-agent/prefs`, the Keychain service `dentroio-factory`, the
launchd labels `com.dentroio.factory-agent*`, the log directory and the published
ports. `make agent-setup` in a second checkout overwrites the first factory's
GitHub token, `API_SECRET` and prefs. Running AegisFlux beside Clarion needs
separate instances.

## What to Build

1. `scripts/factory_instance.sh`: `FACTORY_INSTANCE` (empty by default) derives
   the Keychain service, prefs path and log dir; `FACTORY_PORT_OFFSET` moves the
   published ports. Explicit `FACTORY_PREFS`, `FACTORY_KEYCHAIN_SERVICE` and
   `FACTORY_PORT_*` still win.
2. Use it in `factory-env.sh`, `agent-setup.sh`, `compose-with-env.sh`,
   `github_token.py`, `factory_doctor.py`, `product_setup.py`, `draft_server.py`
   (prefs), the Makefile, and the compose port mappings.
3. Allowed browser origins in status-site and the orchestrator follow
   `FACTORY_PORT_STATUS`.

## Part 2 (separate PR)

Per-instance launchd labels and draft-server ports (`agent-install.sh`,
`draft_server.py` `_AGENT_META`, `health_agent.py` `RUNNER_PORTS`, orchestrator
runner candidates, `run-*.sh` orchestrator URLs). Until then a second instance
runs containers only; native agents stay with the first instance.

## Do NOT change

- Any value when `FACTORY_INSTANCE` and `FACTORY_PORT_OFFSET` are unset.
- The Clarion instance's Keychain entries, prefs or launchd jobs.

## Acceptance

- With nothing set, every derived name and port equals today's.
- `FACTORY_INSTANCE=aegisflux FACTORY_PORT_OFFSET=100` uses
  `dentroio-factory-aegisflux`, `~/.config/factory-agent-aegisflux/prefs`,
  ports 8199 / 8200 / 8301.
- `tests/unit/test_factory_instance.py` passes; `make ci-local` passes.
