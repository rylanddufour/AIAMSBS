#!/usr/bin/env bash
# launch-bitwarden-mcp.sh — runs inside the bitwarden-mcp container.
#
# Handles login + unlock + session persistence before exec'ing the actual
# mcp-server-bitwarden binary. Flow:
#
#   1. Source BW_USER/BW_PASSWORD from /etc/bitwarden-mcp.env (mounted
#      via env_file in docker-compose).
#   2. If a saved BW_SESSION exists in the persistent volume, use it.
#   3. Otherwise: bw login (sets session), bw unlock (saves session),
#      persist BW_SESSION to the persistent volume.
#   4. exec mcp-server-bitwarden "$@" so the MCP server inherits our
#      BW_SESSION and runs as PID 1 (clean signal handling).
#
# Why this wrapper: bw needs an interactive-ish setup on first launch.
# mcp-server-bitwarden expects a valid session to be present. We bridge
# the gap so the container can start unattended.
set -euo pipefail

SESSION_FILE="/var/lib/bitwarden-cli/bw.session"
LOG_PREFIX="[launch-bitwarden-mcp]"

log() { echo "$LOG_PREFIX $*" >&2; }

# Required env: BW_USER, BW_PASSWORD, BW_API_BASE_URL, BW_IDENTITY_URL.
# All four come from /etc/bitwarden-mcp.env on the host (mounted as
# env_file in docker-compose).
for v in BW_USER BW_PASSWORD BW_API_BASE_URL BW_IDENTITY_URL; do
    if [ -z "${!v:-}" ]; then
        log "FATAL: $v is not set in /etc/bitwarden-mcp.env"
        log "Create the first user via the vaultwarden admin panel,"
        log "then populate /etc/bitwarden-mcp.env with BW_USER and BW_PASSWORD."
        log "See vaultwarden-stack/README.md 'First-run UX' for details."
        exit 1
    fi
done

# Configure bw to talk to vaultwarden (idempotent).
bw config server "$BW_API_BASE_URL" >/dev/null

# Try to use a previously-persisted session first.
if [ -f "$SESSION_FILE" ]; then
    export BW_SESSION="$(cat "$SESSION_FILE")"
    if bw status 2>/dev/null | grep -q '"status": "unlocked"'; then
        log "Reusing persisted BW_SESSION (still valid)"
    else
        log "Persisted BW_SESSION expired or invalid, re-unlocking"
        unset BW_SESSION
        rm -f "$SESSION_FILE"
    fi
fi

# No valid session — do a fresh login + unlock.
if [ -z "${BW_SESSION:-}" ]; then
    log "Logging in as $BW_USER..."
    # `bw login --passwordenv` reads BW_PASSWORD from env (no prompt).
    bw login "$BW_USER" --passwordenv BW_PASSWORD --raw 2>/dev/null || {
        log "bw login failed — check BW_USER/BW_PASSWORD in /etc/bitwarden-mcp.env"
        exit 1
    }

    log "Unlocking vault..."
    BW_SESSION="$(bw unlock --passwordenv BW_PASSWORD --raw)"
    export BW_SESSION

    # Persist for next container restart.
    echo -n "$BW_SESSION" > "$SESSION_FILE"
    chmod 600 "$SESSION_FILE"
    log "Persisted new BW_SESSION to $SESSION_FILE"
fi

log "Handing off to mcp-server-bitwarden $*"
exec mcp-server-bitwarden "$@"
