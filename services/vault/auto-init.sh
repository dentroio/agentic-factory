#!/bin/sh
# Auto-initialize Vault on first run and unseal on every start.
# Runs as CMD inside the vault container.
# Issues a policy-scoped orchestrator token onto a separate volume (AF-10).

export VAULT_ADDR="http://127.0.0.1:8200"
KEYS_DIR="/vault/keys"
ORCH_DIR="/vault/orch"
POLICY_FILE="/vault/config/orchestrator-policy.hcl"
mkdir -p "$KEYS_DIR" "$ORCH_DIR"

# Start Vault server in the background
vault server -config=/vault/config/config.hcl &
VAULT_PID=$!

# Wait until the Vault API is reachable.
# vault status exit codes: 0=active, 1=error/no-connection, 2=sealed/not-initialized
# We loop until we get 0 or 2 (meaning the API is up).
echo "[vault] Waiting for API..."
TRIES=0
while true; do
    vault status >/dev/null 2>&1
    EC=$?
    [ "$EC" = "0" ] || [ "$EC" = "2" ] && break
    TRIES=$((TRIES+1))
    if [ $TRIES -gt 30 ]; then
        echo "[vault] ERROR: API did not start within 30s"
        exit 1
    fi
    sleep 1
done

issue_orchestrator_token() {
    if [ ! -f "$KEYS_DIR/root_token" ]; then
        echo "[vault] ERROR: root token missing; cannot issue orchestrator token"
        exit 1
    fi
    if [ ! -f "$POLICY_FILE" ]; then
        echo "[vault] ERROR: policy file missing at $POLICY_FILE"
        exit 1
    fi
    VAULT_TOKEN=$(cat "$KEYS_DIR/root_token")
    export VAULT_TOKEN
    vault policy write orchestrator "$POLICY_FILE" >/dev/null \
        || { echo "[vault] ERROR: policy write failed"; unset VAULT_TOKEN; exit 1; }
    TOKEN=$(vault token create -policy=orchestrator -period=768h -orphan -field=token) \
        || { echo "[vault] ERROR: orchestrator token create failed"; unset VAULT_TOKEN; exit 1; }
    unset VAULT_TOKEN
    if [ -z "$TOKEN" ]; then
        echo "[vault] ERROR: empty orchestrator token"
        exit 1
    fi
    printf '%s' "$TOKEN" > "$ORCH_DIR/orchestrator_token"
    chmod 600 "$ORCH_DIR/orchestrator_token"
    echo "[vault] Orchestrator token issued (policy=orchestrator)."
}

# Check init status: 0=initialized, 2=not-initialized
vault operator init -status >/dev/null 2>&1
INIT_EC=$?

if [ "$INIT_EC" = "0" ]; then
    echo "[vault] Already initialized — unsealing..."
    if [ -f "$KEYS_DIR/unseal_key" ]; then
        vault operator unseal "$(cat "$KEYS_DIR/unseal_key")" >/dev/null \
            || { echo "[vault] ERROR: unseal failed"; exit 1; }
        echo "[vault] Unsealed."
    else
        echo "[vault] ERROR: No unseal key at $KEYS_DIR/unseal_key"
        exit 1
    fi
else
    echo "[vault] Initializing..."
    INIT_OUT=$(vault operator init -key-shares=1 -key-threshold=1) \
        || { echo "[vault] ERROR: init failed"; exit 1; }
    UNSEAL_KEY=$(echo "$INIT_OUT" | grep "Unseal Key 1:" | awk '{print $NF}')
    ROOT_TOKEN=$(echo "$INIT_OUT" | grep "Initial Root Token:" | awk '{print $NF}')

    if [ -z "$UNSEAL_KEY" ] || [ -z "$ROOT_TOKEN" ]; then
        echo "[vault] ERROR: could not parse init output"
        exit 1
    fi

    printf '%s' "$UNSEAL_KEY" > "$KEYS_DIR/unseal_key"
    printf '%s' "$ROOT_TOKEN" > "$KEYS_DIR/root_token"
    chmod 600 "$KEYS_DIR/unseal_key" "$KEYS_DIR/root_token"

    vault operator unseal "$UNSEAL_KEY" >/dev/null \
        || { echo "[vault] ERROR: initial unseal failed"; exit 1; }

    export VAULT_TOKEN="$ROOT_TOKEN"
    vault secrets enable -path=secret kv-v2 >/dev/null 2>&1 \
        || echo "[vault] KV v2 mount already exists — continuing"
    unset VAULT_TOKEN

    echo "[vault] Initialized and unsealed. Keys written to $KEYS_DIR/"
fi

issue_orchestrator_token

echo "[vault] Ready."
wait $VAULT_PID
