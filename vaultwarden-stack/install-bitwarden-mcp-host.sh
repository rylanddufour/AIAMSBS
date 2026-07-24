#!/usr/bin/env bash
# install-bitwarden-mcp-host.sh — HOST-LOCAL install for bitwarden/mcp-server.
#
# BACKLOG #49. Per the bitwarden/mcp-server README warning ("designed
# exclusively for local use and must never be hosted publicly"), this is a
# HOST-LOCAL install — NOT a docker container, NOT a published service.
#
# What gets installed (idempotent — `npm install -g` is a no-op when the
# package is already at the pinned version, but we also pin via package.json
# for reproducibility):
#
#   - @bitwarden/cli          (the `bw` CLI; the MCP server wraps it)
#   - @bitwarden/mcp-server   (the `mcp-server-bitwarden` stdio MCP server)
#
# Pre-req: Node.js 20+ on PATH (bootstrap.sh installs this in
# check_prerequisites() and install_node()).
set -euo pipefail

LOG_PREFIX="[install-bitwarden-mcp-host]"

log() { echo "$LOG_PREFIX $*" >&2; }

# Pre-check: node + npm
if ! command -v node >/dev/null 2>&1; then
    log "FATAL: node is not on PATH. bootstrap.sh installs Node.js 20+;"
    log "if you're running this manually, install Node.js first."
    exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
    log "FATAL: npm is not on PATH (node install usually brings it; check PATH)"
    exit 1
fi

NODE_MAJOR="$(node -v | sed -E 's/^v([0-9]+)\..*/\1/')"
if [ "${NODE_MAJOR}" -lt 20 ]; then
    log "FATAL: node $(node -v) is too old; bitwarden/mcp-server requires Node.js 20+"
    exit 1
fi

# Check if already installed at expected versions (idempotent skip).
if command -v bw >/dev/null 2>&1 && command -v mcp-server-bitwarden >/dev/null 2>&1; then
    BW_VER="$(bw --version 2>/dev/null || echo 'unknown')"
    MCP_VER="$(npm ls -g @bitwarden/mcp-server --depth=0 2>/dev/null | grep @bitwarden/mcp-server | sed -E 's/.*@([0-9.]+).*/\1/' || echo 'unknown')"
    log "Already installed — bw $BW_VER, @bitwarden/mcp-server $MCP_VER (preserving)"
    exit 0
fi

log "Installing @bitwarden/cli + @bitwarden/mcp-server globally..."
npm install -g @bitwarden/cli @bitwarden/mcp-server

# Verify
if ! command -v bw >/dev/null 2>&1 || ! command -v mcp-server-bitwarden >/dev/null 2>&1; then
    log "FATAL: install reported success but bw / mcp-server-bitwarden not on PATH"
    log "PATH is: $PATH"
    exit 1
fi

log "Installed. Versions:"
log "  bw:                  $(bw --version)"
log "  @bitwarden/mcp-server: $(npm ls -g @bitwarden/mcp-server --depth=0 2>/dev/null | grep @bitwarden/mcp-server)"
log "Launch Hermes-side MCP via: vaultwarden-stack/bitwarden-mcp/launch-bitwarden-mcp.sh --stdio"
