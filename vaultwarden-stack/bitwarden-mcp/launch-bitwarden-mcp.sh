#!/usr/bin/env bash
# launch-bitwarden-mcp.sh — HOST-LOCAL shim that wraps the @bitwarden/mcp-server.
#
# BACKLOG #49 — bitwarden/mcp-server installed on the AIAMSBS host (per its
# own README warning: "designed exclusively for local use and must never be
# hosted publicly"). Hermes launches this as the MCP server entrypoint in
# `~/.hermes/config.yaml` under mcp_servers.bitwarden-mcp.
#
# Flow (run on every Hermes startup of the MCP server):
#
#   1. Source BW_CLIENTID / BW_CLIENTSECRET / BW_API_BASE_URL / BW_IDENTITY_URL
#      from /etc/bitwarden-mcp.env (root-only, mode 0600). These are the
#      customer's org-scoped machine-account API key (BACKLOG #49 choice B
#      — there is no master password on disk; the API key scope is the gate).
#   2. If a previously-persisted BW_SESSION exists in $HOME/.local/share/bitwarden-cli/
#      and bw status reports "unlocked"/"authenticated", reuse it.
#   3. Otherwise: bw login --apikey (env BW_CLIENTID/BW_CLIENTSECRET) and
#      persist the raw BW_SESSION to the cache file (mode 0600).
#   4. exec mcp-server-bitwarden "$@" — the MCP server inherits BW_SESSION
#      + BW_CLIENTID/SECRET and runs as PID 1 (clean signal handling).
#
# Why client_credentials / API-key auth (not username+password):
#   - No master password to leak. Compromising the env file = ONLY the items
#     the org-scoped machine account can see (customer controls this scope).
#   - Bitwarden's API key is short-lived-rotatable via vault UI; rotating
#     the key does NOT require updating stored device passwords.
#   - Same posture as HashiCorp Vault's AppRole / Kubernetes service accounts.
set -euo pipefail

ENV_FILE="${BITWARDEN_MCP_ENV:-/etc/bitwarden-mcp.env}"
SESSION_DIR="${BITWARDEN_MCP_SESSION_DIR:-$HOME/.local/share/bitwarden-cli}"
SESSION_FILE="${SESSION_DIR}/bw.session"
LOG_PREFIX="[bitwarden-mcp]"

log() { echo "$LOG_PREFIX $*" >&2; }

# Source the env file so BW_CLIENTID/BW_CLIENTSECRET are populated. The env
# file is mode 0600 root; the launch shim is invoked by Hermes as the user
# running the gateway. If the file isn't readable, fail loudly so the operator
# fixes perms (chmod 600 / chown root) instead of silently mis-attributing.
if [ ! -r "${ENV_FILE}" ]; then
    log "FATAL: cannot read env file ${ENV_FILE} (does it exist? perms?)"
    log "Fix on the AIAMSBS host:  sudo chmod 600 ${ENV_FILE} && sudo chown root:root ${ENV_FILE}"
    exit 1
fi
set +u
. "${ENV_FILE}"
set -u

# Required env from /etc/bitwarden-mcp.env
for v in BW_CLIENTID BW_CLIENTSECRET BW_API_BASE_URL BW_IDENTITY_URL; do
    if [ -z "${!v:-}" ]; then
        log "FATAL: $v is not set in ${ENV_FILE}"
        log "The customer needs to create a machine account in the vault UI"
        log "and populate ${ENV_FILE} with the resulting client_id + client_secret."
        log "See vaultwarden-stack/README.md 'Customer onboarding (client_credentials model)'."
        exit 1
    fi
done

# Point bw at the local vaultwarden (idempotent — persists in $SESSION_DIR/config).
bw config server "$BW_API_BASE_URL" >/dev/null

# Try a previously-persisted session first (avoids re-login on every Hermes MCP launch).
mkdir -p "$SESSION_DIR"
chmod 700 "$SESSION_DIR"
if [ -f "$SESSION_FILE" ]; then
    export BW_SESSION
    BW_SESSION="$(cat "$SESSION_FILE")"
    if bw status 2>/dev/null | grep -q '"status": "unlocked"\|"status": "authenticated"\|"userAtOrganization":'; then
        log "Reusing persisted BW_SESSION (still valid)"
    else
        log "Persisted BW_SESSION expired or invalid — re-authenticating"
        unset BW_SESSION
        rm -f "$SESSION_FILE"
    fi
fi

# No valid session — do a fresh API-key login. No master password involved.
if [ -z "${BW_SESSION:-}" ]; then
    log "Logging in via API key (client_credentials flow)..."
    # `bw login --apikey` reads BW_CLIENTID/BW_CLIENTSECRET from env, returns raw session key.
    BW_SESSION="$(bw login --apikey --raw 2>/dev/null)" || {
        log "bw login --apikey failed — check BW_CLIENTID/BW_CLIENTSECRET in ${ENV_FILE}"
        exit 1
    }
    export BW_SESSION

    # Persist for next launch (mode 0600 in $SESSION_DIR — which is 0700).
    echo -n "$BW_SESSION" > "$SESSION_FILE"
    chmod 600 "$SESSION_FILE"
    log "Persisted new BW_SESSION to $SESSION_FILE"
fi

log "Handing off to mcp-server-bitwarden $*"
exec mcp-server-bitwarden "$@"
