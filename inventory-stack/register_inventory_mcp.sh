#!/bin/bash
set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 <profile_name>"
    exit 1
fi

PROFILE="$1"
CONFIG_PATH="$HOME/.hermes/profiles/${PROFILE}/config.yaml"

# Create backup first
cp "$CONFIG_PATH" "${CONFIG_PATH}.bak"

cat >> "$CONFIG_PATH" << 'EOF'

mcp_servers:
  inventory-mcp:
    url: http://localhost:8001/mcp
    transport: streamable-http
    auth:
      headers:
        Authorization: Bearer ***

EOF

chmod 600 "$CONFIG_PATH"
