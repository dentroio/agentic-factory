# WO-1031 — Clarion: Move MIGRATIONS_DONE Flag from Vault to Database

**Created:** 2026-07-18
**Priority:** P2
**Effort:** S
**Services:** clarion/services/data-service
**Depends on:** none
**Status:** ✅ Done

---

## Background

Clarion's data-service uses a boolean flag (`CLARION_MIGRATIONS_DONE`) stored in HashiCorp Vault at `secret/clarion/migrations_done` to determine whether database migrations have already run. If this flag is missing (e.g. Vault is recreated, or `docker compose up` without `--no-deps` triggers a Vault container recreation), data-service tries to re-run all migrations. Against a live database with existing tables, this either errors out or hangs in a restart loop.

This happened twice this week:
1. `docker compose up --force-recreate frontend` without `--no-deps` caused Vault to be recreated as a dependency. Flag was lost. data-service crashed.
2. After a full `docker compose down`, the flag was missing on restart until manually re-injected.

The flag is purely a database concern — it has nothing to do with secrets management. Storing it in Vault adds fragility (Vault downtime = data-service can't start), complexity (requires Vault to be healthy before data-service can even check if it should run migrations), and confusion (agents and operators don't know to check Vault when data-service won't start).

The correct place for this flag is the database itself — a `schema_meta` table or the existing migrations table — which is always available when data-service needs to check it.

---

## What to Build

### 1. Create a `_schema_meta` table in the database

Add a migration that creates a lightweight key-value table for internal schema tracking:

```sql
-- migrations/add_schema_meta.sql
CREATE TABLE IF NOT EXISTS _schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    set_at TIMESTAMPTZ DEFAULT NOW()
);
```

Register this migration in `adapter.py` (must run first, before all other migrations).

### 2. Replace Vault flag check with DB check

In `data-service/app.py` (or wherever migrations are gated), replace:

```python
# OLD — reads from Vault
migrations_done = vault_client.read("secret/clarion/migrations_done")
if migrations_done and migrations_done.get("data", {}).get("value") == "1":
    return  # skip migrations
```

With:

```python
# NEW — reads from DB
with db.connect() as conn:
    result = conn.execute(
        "SELECT value FROM _schema_meta WHERE key = 'migrations_done'"
    ).fetchone()
    if result and result[0] == "1":
        return  # skip migrations
```

### 3. Write the flag to DB after migrations complete

After all migrations run successfully, write to the table:

```python
with db.connect() as conn:
    conn.execute(
        "INSERT INTO _schema_meta (key, value) VALUES ('migrations_done', '1') "
        "ON CONFLICT (key) DO UPDATE SET value = '1', set_at = NOW()"
    )
    conn.commit()
print("[data-service] migrations complete — flag written to DB")
```

### 4. Remove the Vault dependency for this flag

After the above is deployed and verified, remove the Vault read for `migrations_done` entirely. The flag value in Vault can be left in place (harmless) or cleaned up with `vault kv delete secret/clarion/migrations_done`.

Update `docker-compose.yml` to remove the Vault dependency from `data-service` if `migrations_done` was the only reason data-service needed Vault at startup. (Data-service may still need Vault for other secrets — check before removing the dependency entirely.)

### 5. Update runbook and CLAUDE.md

Remove the `docker exec clarion-vault vault kv put secret/clarion/migrations_done value=1` step from the disaster-recovery runbook (in `docs/ops/RUNBOOK.md` if it exists) and from CLAUDE.md's troubleshooting notes. Replace with: "If data-service restarts trying to re-run migrations, check: `SELECT * FROM _schema_meta WHERE key = 'migrations_done'` — if missing, the DB flag was lost; contact the team."

---

## Acceptance Criteria

- [ ] `_schema_meta` table exists after a fresh database setup
- [ ] data-service reads `migrations_done` from DB, not Vault
- [ ] After migrations run, flag is written to `_schema_meta`
- [ ] Recreating the Vault container does not cause data-service to try re-running migrations
- [ ] `make smoke-test` passes after Vault is `docker stop`ped (proves no Vault dependency for migration gate)
- [ ] CLAUDE.md and runbook updated

## Documentation Required

- [ ] `docs/ops/RUNBOOK.md` — update disaster recovery section; remove `vault kv put migrations_done` step
- [ ] `CLAUDE.md` — remove Vault flag from troubleshooting section; replace with DB query
