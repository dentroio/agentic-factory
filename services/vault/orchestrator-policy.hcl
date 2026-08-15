# Orchestrator may only read/write the factory secrets KV v2 path (AF-10).
path "secret/data/factory/secrets" {
  capabilities = ["create", "read", "update"]
}

path "secret/metadata/factory/secrets" {
  capabilities = ["read"]
}
