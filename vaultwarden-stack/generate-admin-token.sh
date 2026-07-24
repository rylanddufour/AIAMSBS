#!/usr/bin/env bash
# generate-admin-token.sh
# Generates a 256-bit (32-byte) hex-encoded admin token for the vaultwarden
# admin panel. Idempotent: if /etc/vaultwarden/admin-token already exists,
# does nothing (preserves an existing token across re-runs of bootstrap.sh).
#
# BACKLOG #48 — vaultwarden admin token management.
#
# Output:
#   /etc/vaultwarden/admin-token    mode 0600, root:root
#   Prints the token once on first generation (so the customer can copy it).
set -euo pipefail

TOKEN_DIR="/etc/vaultwarden"
TOKEN_FILE="${TOKEN_DIR}/admin-token"

if [ -f "${TOKEN_FILE}" ]; then
    echo "Vaultwarden admin token already exists at ${TOKEN_FILE} (preserving)" >&2
    exit 0
fi

mkdir -p "${TOKEN_DIR}"
chmod 700 "${TOKEN_DIR}"

# 32 bytes = 256 bits = 64 hex chars. vaultwarden accepts any length but
# this matches the upstream Bitwarden convention.
TOKEN=$(openssl rand -hex 32)

printf '%s' "${TOKEN}" > "${TOKEN_FILE}"
chmod 600 "${TOKEN_FILE}"
chown root:root "${TOKEN_FILE}" 2>/dev/null || true

echo "Generated vaultwarden admin token at ${TOKEN_FILE}" >&2
echo "TOKEN: ${TOKEN}"
