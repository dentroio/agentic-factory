---
name: factory-instance-namespacing
description: FACTORY_INSTANCE env var namespaces prefs path, Keychain service, log dir, and ports across the factory stack; all new instance-dependent code must route through scripts/factory_instance.sh / Makefile vars, not hardcode defaults.
metadata:
  type: project
---

FACTORY_INSTANCE (WO-1108) is a cross-cutting namespace variable: when set, it suffixes the Keychain service name (`dentroio-factory-<instance>`), prefs config dir (`~/.config/factory-agent-<instance>/prefs`), log dir (`~/Library/Logs/factory-agent-<instance>`), launchd label, and port numbers (via FACTORY_PORT_OFFSET added to each service's default port). When unset, every derived value must equal the historical default exactly (tested in tests/unit/test_factory_instance.py) — this is a hard backward-compat invariant, not just a convenience.

**Why:** Multiple factory instances (e.g. for different products like "aegisflux") need to run side-by-side on one machine without colliding on secrets, ports, or log files. The namespacing logic is scattered across many files (draft_server.py, product_setup.py, factory_doctor.py, github_token.py, orchestrator.py, dashboard_auth.py, Makefile, docker-compose.status.yml) rather than centralized, so it's easy to add a new instance-dependent value and forget to namespace it.

**How to apply:** Any new code that hardc