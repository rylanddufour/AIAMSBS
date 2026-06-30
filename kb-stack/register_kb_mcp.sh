#!/bin/bash
# Standalone kb-mcp registration. Mirrors the register_kb_mcp() function in
# bootstrap.sh for users who want to wire kb-mcp into a profile without
# re-running the full bootstrap. Idempotent.
set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 <profile_name>"
    exit 1
fi

PROFILE="$1"

# BACKLOG #24: default profile's config IS the global ~/.hermes/config.yaml.
# ~/.hermes/profiles/default/config.yaml is a dead location Hermes ignores.
if [ "$PROFILE" = "default" ]; then
    CONFIG_PATH="$HOME/.hermes/config.yaml"
else
    CONFIG_PATH="$HOME/.hermes/profiles/${PROFILE}/config.yaml"
fi

mkdir -p "$(dirname "$CONFIG_PATH")"
[ -f "$CONFIG_PATH" ] || touch "$CONFIG_PATH"

# Idempotent: skip if already registered.
if grep -q '^  kb-mcp:' "$CONFIG_PATH" 2>/dev/null; then
    echo "kb-mcp already registered in profile '$PROFILE' ($CONFIG_PATH)"
    exit 0
fi

# Append in DICT format (Hermes CLI tools_config.py:1365 expects a dict).
cp "$CONFIG_PATH" "${CONFIG_PATH}.bak"
cat >> "$CONFIG_PATH" << 'EOF'

mcp_servers:
  kb-mcp:
    url: http://localhost:8002/mcp
    transport: streamable-http
EOF

chmod 600 "$CONFIG_PATH"
echo "kb-mcp registered in profile '$PROFILE' ($CONFIG_PATH)"
