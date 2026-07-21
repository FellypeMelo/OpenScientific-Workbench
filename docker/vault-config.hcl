# HashiCorp Vault server configuration for the `vault` service in
# `docker-compose.yml` (the `advanced` Compose profile).
#
# FILE storage backend (not `-dev`/inmem): data written here survives
# container restarts, backed by the `vault_data` named volume mounted at
# /vault/data. This is the deliberate tradeoff for this project's locked
# architecture (single local server, no external cluster) -- a real HA
# backend (Consul/Raft) would be overkill for one trusted box.
storage "file" {
  path = "/vault/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  # TLS is intentionally disabled: this listener is only reachable inside the
  # Compose network (or via the operator's own local port-forward) on a
  # single trusted host, matching this project's locked "single local
  # server" architecture. Do not reuse this config as-is on a shared network.
  tls_disable = 1
}

# Advertised inside the Compose network under the `vault` service name.
api_addr = "http://vault:8200"

# Containers commonly cannot lock memory pages without the extra `IPC_LOCK`
# capability; rather than require that capability on the container, disable
# mlock here (Vault's own documented option for containerized deployments).
disable_mlock = true

ui = true
