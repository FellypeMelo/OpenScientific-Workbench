#!/bin/sh
# Entrypoint for the `vault` service in `docker-compose.yml` (the `advanced`
# Compose profile -- HashiCorp Vault, only used by the dormant Slurm-SSH HPC
# path). Replaces the image's default entrypoint entirely (see
# `docker-compose.yml`'s `entrypoint:` override).
#
# What this does, every time the container boots:
#   1. Starts `vault server` (FILE storage backend, see `vault-config.hcl`)
#      in the background, sealed.
#   2. Waits for its local HTTP API to come up.
#   3. FIRST BOOT ONLY: runs `vault operator init` (a single key share/
#      threshold -- see the note below on why) and writes the unseal key +
#      initial root token to `/vault/creds/root-credentials.txt`
#      (`chmod 600`), inside the `vault_creds` named volume.
#   4. EVERY BOOT: reads that same file and runs `vault operator unseal`
#      with the key in it, so the server comes up usable without a human
#      re-entering an unseal key by hand after every restart.
#   5. Hands off to the already-running `vault server` process (waits on it,
#      forwarding SIGTERM/SIGINT so `docker stop`/`docker compose down`
#      shut it down cleanly).
#
# ============================================================================
# IMPORTANT -- `/vault/creds/root-credentials.txt` is REAL, LIVE CREDENTIAL
# MATERIAL: the Vault unseal key AND the initial root token (full admin
# access to this Vault instance) both live in that one file, in plaintext,
# for as long as the `vault_creds` volume exists. This is a deliberate
# simplification for this project's locked architecture -- ONE trusted local
# server, ONE operator, no external cluster -- not something to copy into a
# shared or multi-tenant deployment. Whoever administers this host should
# treat that file (and the `vault_creds` volume) exactly like a root
# password: back it up somewhere safe, and rotate the root token
# (`vault token create` a scoped token for day-to-day use, then
# `vault token revoke` the initial root token) instead of using the root
# token itself for the app's `VAULT_TOKEN`.
#
# `-key-shares=1 -key-threshold=1` (a single unseal key, not Vault's usual
# Shamir's-Secret-Sharing split across multiple key holders) is the same
# single-trusted-operator tradeoff: Shamir splitting exists to require
# multiple humans to cooperate to unseal Vault, which has no purpose when
# there is only one operator and one server to begin with, and would only
# turn "auto-unseal on boot" back into a manual multi-person ceremony.
# ============================================================================

set -eu

CREDS_DIR="/vault/creds"
CREDS_FILE="$CREDS_DIR/root-credentials.txt"

mkdir -p "$CREDS_DIR"

export VAULT_ADDR="http://127.0.0.1:8200"

# Forward termination signals to the real `vault server` process so
# `docker stop`/`docker compose down` shut it down cleanly instead of
# killing this wrapper script and leaving Vault orphaned.
term_handler() {
  echo "[vault-entrypoint] received TERM/INT, stopping vault server (pid $VAULT_PID)..."
  kill -TERM "$VAULT_PID" 2>/dev/null || true
  wait "$VAULT_PID" 2>/dev/null || true
  exit 0
}
trap term_handler TERM INT

echo "[vault-entrypoint] starting vault server (file storage backend)..."
vault server -config=/vault/config/vault-config.hcl &
VAULT_PID=$!

echo "[vault-entrypoint] waiting for the Vault HTTP API to come up..."
i=0
while [ "$i" -lt 60 ]; do
  set +e
  vault status >/dev/null 2>&1
  status_code=$?
  set -e
  # `vault status` exits 0 (unsealed) or 2 (sealed) once the API is actually
  # reachable; it exits 1 on a connection error, i.e. "not up yet" here.
  if [ "$status_code" != "1" ]; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

if [ "$i" -ge 60 ]; then
  echo "[vault-entrypoint] FATAL: vault server did not come up within 60s" >&2
  exit 1
fi

if [ ! -s "$CREDS_FILE" ]; then
  echo "[vault-entrypoint] first boot: running 'vault operator init' (single key share -- see this script's header comment)"
  vault operator init -key-shares=1 -key-threshold=1 > "$CREDS_FILE"
  chmod 600 "$CREDS_FILE"
  echo "[vault-entrypoint] wrote unseal key + root token to $CREDS_FILE (chmod 600)"
fi

UNSEAL_KEY=$(grep '^Unseal Key 1:' "$CREDS_FILE" | awk '{print $NF}')
if [ -z "$UNSEAL_KEY" ]; then
  echo "[vault-entrypoint] FATAL: could not read the unseal key from $CREDS_FILE" >&2
  exit 1
fi

echo "[vault-entrypoint] auto-unsealing..."
vault operator unseal "$UNSEAL_KEY" >/dev/null

echo "[vault-entrypoint] Vault is unsealed and ready at $VAULT_ADDR"
echo "[vault-entrypoint] root token + unseal key: $CREDS_FILE (inside the vault_creds volume) -- treat as a root password, see this script's header comment"

wait "$VAULT_PID"
