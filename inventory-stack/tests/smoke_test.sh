#!/usr/bin/env bash
# Smoke test for AIAMSBS inventory-stack.
#
# Exercises every tool exposed by the inventory-mcp container over MCP
# streamable-http, plus a TCP-socket probe of the nmap-discovery wrapper,
# after seeding the inventory DB with three representative devices.
#
# Run from inventory-stack/:
#     bash tests/smoke_test.sh
#
# Exit codes:
#   0  every check passed
#   1  first failing test name is printed to stderr; the failing check stops
#      execution and the script returns 1.

set -u  # don't `set -e` — we want to capture per-check failures ourselves

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

MCP_URL="http://127.0.0.1:8001/mcp"
NMAP_PORT=8002
NMAP_HOST=127.0.0.1
MCP_CONTAINER="${MCP_CONTAINER:-inventory-mcp}"
NMAP_CONTAINER="${NMAP_CONTAINER:-nmap-discovery}"

CT="Content-Type: application/json"
ACC="Accept: application/json, text/event-stream"

LINUX_ID="dev-linux-01"
LINUX_HOST="linux-host-01"
LINUX_IP="192.168.10.10"
SWITCH_ID="dev-switch-01"
SWITCH_HOST="core-switch-01"
SWITCH_IP="192.168.10.1"
AP_ID="dev-ap-01"
AP_HOST="ap-floor1-01"
AP_IP="192.168.10.50"

# Colors (disabled when not a TTY so logs stay clean in CI)
if [ -t 1 ]; then
    C_PASS=$'\033[32m'
    C_FAIL=$'\033[31m'
    C_RESET=$'\033[0m'
else
    C_PASS=""
    C_FAIL=""
    C_RESET=""
fi

PASS_COUNT=0
FAIL_COUNT=0
FAIL_NAME=""

pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    printf '  %s[PASS]%s %s\n' "$C_PASS" "$C_RESET" "$1"
}

fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAIL_NAME="$1"
    printf '  %s[FAIL]%s %s\n' "$C_FAIL" "$C_RESET" "$1" >&2
    if [ -n "${2-}" ]; then
        printf '         %s\n' "$2" >&2
    fi
    exit 1
}

info() {
    printf '  [....] %s\n' "$1"
}

section() {
    printf '\n=== %s ===\n' "$1"
}

# ---------------------------------------------------------------------------
# Helpers: MCP over streamable-http
# ---------------------------------------------------------------------------

# Initialize a session and print the session id. Uses curl -D - to capture
# headers, parses mcp-session-id, sends notifications/initialized, then
# echoes the SID on stdout.
mcp_init() {
    local init_resp
    init_resp=$(curl -s -D - -X POST "$MCP_URL" \
        -H "$CT" -H "$ACC" \
        --max-time 10 \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke-test","version":"1.0"}}}') \
        || fail "mcp_init" "curl initialize failed"

    local sid
    sid=$(printf '%s' "$init_resp" \
        | grep -i '^mcp-session-id:' \
        | head -1 \
        | awk '{print $2}' \
        | tr -d '\r\n') \
        || fail "mcp_init" "could not parse session id"

    if [ -z "$sid" ]; then
        fail "mcp_init" "no mcp-session-id in response headers"
    fi

    # Acknowledge initialization. 202 expected; body is empty.
    curl -s -X POST "$MCP_URL" \
        -H "$CT" -H "$ACC" -H "Mcp-Session-Id: $sid" \
        --max-time 5 \
        -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
        >/dev/null \
        || fail "mcp_init" "notifications/initialized failed"

    printf '%s' "$sid"
}

# Call an MCP tool. Args:
#   $1 = session id
#   $2 = tool name
#   $3 = arguments JSON object (string)
# Echoes a JSON string on stdout representing the unwrapped tool result:
#   * if the tool returned a dict, the JSON string IS the dict
#   * if the tool returned a list of dicts, the JSON string is a list of dicts
#     (FastMCP expands list-returning tools into multiple `content` items,
#     each with its own `text` payload — we re-assemble them here).
# Fails the script on HTTP non-200 or an RPC error envelope.
mcp_call() {
    local sid="$1" tool="$2" args="$3"
    local body
    body=$(printf '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":%s,"arguments":%s}}' \
        "$(printf '%s' "$tool" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read().rstrip()))')" \
        "$args")

    # Capture response with -i to keep headers; split status line off.
    local raw http_code
    raw=$(curl -s -i -X POST "$MCP_URL" \
        -H "$CT" -H "$ACC" -H "Mcp-Session-Id: $sid" \
        --max-time 10 \
        -d "$body") || fail "mcp_call($tool)" "curl failed"

    http_code=$(printf '%s' "$raw" | head -1 | awk '{print $2}')
    if [ "$http_code" != "200" ]; then
        fail "mcp_call($tool)" "HTTP $http_code — $(printf '%s' "$raw" | head -c 200)"
    fi

    # Strip headers, then extract the SSE `data:` line.
    local payload
    payload=$(printf '%s' "$raw" \
        | sed -n '/^data: /{s/^data: //; p;}' \
        | head -1)

    if [ -z "$payload" ]; then
        fail "mcp_call($tool)" "no SSE data line in response"
    fi

    # Validate outer JSON-RPC envelope; reassemble content items into a
    # single JSON document (dict if 1 item, list if N items).
    local inner
    inner=$(printf '%s' "$payload" | python3 -c '
import sys, json
try:
    d = json.loads(sys.stdin.read())
except Exception as e:
    print("PARSE_ERROR:", e); sys.exit(2)
if "error" in d:
    print("RPC_ERROR:", json.dumps(d["error"])); sys.exit(3)
content = d.get("result", {}).get("content", [])
if not content:
    print("NO_CONTENT"); sys.exit(4)
# Each content[i].text is itself a JSON string. Parse all of them.
items = []
for c in content:
    t = c.get("text", "")
    if not t:
        continue
    try:
        items.append(json.loads(t))
    except Exception:
        items.append(t)
if len(items) == 1:
    print(json.dumps(items[0]))
elif len(items) > 1:
    print(json.dumps(items))
else:
    print(json.dumps(None))
')
    local rc=$?
    if [ $rc -ne 0 ]; then
        fail "mcp_call($tool)" "$inner (rc=$rc)"
    fi
    printf '%s' "$inner"
}

# Python-side assertion helpers ------------------------------------------------

# assert_json: <description> <json-string> <python-expr-on-parsed-json>
# Loads the JSON string and evaluates the python expression in a context
# where `d` is the parsed value. Fails the test if the expression is falsy.
assert_json() {
    local desc="$1" payload="$2" expr="$3"
    python3 -c "
import json, sys
d = json.loads(sys.argv[1])
ok = bool(($expr))
sys.exit(0 if ok else 1)
" "$payload" >/dev/null 2>&1 \
        && pass "$desc" \
        || fail "$desc" "expression failed: $expr — payload: $payload"
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

section "preflight"

# Seed the DB. seed.py uses `docker exec` so we don't need to touch the volume.
if ! python3 "$HERE/seed.py" >/dev/null; then
    fail "seed" "seed.py failed"
fi
pass "seed (DB reseeded via seed.py)"

# Confirm inventory-mcp container is up.
if command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$MCP_CONTAINER"; then
        pass "container $MCP_CONTAINER is up"
    else
        # Try with sudo as a fallback (dev sandbox).
        if sudo -n docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$MCP_CONTAINER"; then
            pass "container $MCP_CONTAINER is up (sudo docker)"
        else
            fail "container $MCP_CONTAINER is up" "not in docker ps output"
        fi
    fi
else
    info "docker not on PATH; skipping container presence check (curl probe will fail loudly if down)"
fi

# ---------------------------------------------------------------------------
# Open an MCP session
# ---------------------------------------------------------------------------

section "MCP session"

SID=$(mcp_init) || true
if [ -z "${SID-}" ]; then
    fail "MCP initialize" "no session id returned"
fi
pass "initialize (session=$SID)"

# ---------------------------------------------------------------------------
# Test each of the 8 tools
# ---------------------------------------------------------------------------

section "MCP tools (8)"

# 1. get_device — Linux host
PAYLOAD=$(mcp_call "$SID" "get_device" "{\"device_id\":\"$LINUX_ID\"}")
assert_json "get_device($LINUX_ID) returns seeded linux host" "$PAYLOAD" \
    "d.get('device_id')=='$LINUX_ID' and d.get('hostname')=='$LINUX_HOST' and d.get('ip_address')=='$LINUX_IP' and d.get('device_type')=='linux_host'"

# 2. lookup_by_ip — switch
PAYLOAD=$(mcp_call "$SID" "lookup_by_ip" "{\"ip\":\"$SWITCH_IP\"}")
assert_json "lookup_by_ip($SWITCH_IP) returns seeded switch" "$PAYLOAD" \
    "d.get('hostname')=='$SWITCH_HOST' and d.get('device_id')=='$SWITCH_ID'"

# 3. lookup_by_hostname — AP
PAYLOAD=$(mcp_call "$SID" "lookup_by_hostname" "{\"hostname\":\"$AP_HOST\"}")
assert_json "lookup_by_hostname($AP_HOST) returns seeded AP" "$PAYLOAD" \
    "d.get('device_id')=='$AP_ID' and d.get('ip_address')=='$AP_IP'"

# 4. search_devices — query="linux"
# The tool searches device_id, hostname, ip_address, vendor, description, tags.
# "linux" matches the seeded linux_host (device_type=linux_host, tags include
# 'linux', hostname is linux-host-01). FastMCP returns one `content` item per
# match, so the wire shape is either a single dict (1 hit) or a list of dicts
# (N hits). Accept either, but always require the linux host to be present and
# the switch/AP to be absent.
PAYLOAD=$(mcp_call "$SID" "search_devices" "{\"query\":\"linux\"}")
assert_json "search_devices(query='linux') returns linux host only" "$PAYLOAD" \
    "((isinstance(d, dict) and d.get('device_id')=='$LINUX_ID') or (isinstance(d, list) and any(x.get('device_id')=='$LINUX_ID' for x in d))) and not (isinstance(d, dict) and d.get('device_id') in ('$SWITCH_ID','$AP_ID')) and not (isinstance(d, list) and any(x.get('device_id') in ('$SWITCH_ID','$AP_ID') for x in d))"

# 5. create_device — insert a brand-new device, expect id echoed
NEW_ID="dev-smoke-new-$$"
NEW_HOST="smoke-new-host-$$"
NEW_IP="192.168.99.$$"
PAYLOAD=$(mcp_call "$SID" "create_device" \
    "{\"device\":{\"device_id\":\"$NEW_ID\",\"hostname\":\"$NEW_HOST\",\"ip_address\":\"$NEW_IP\",\"device_type\":\"linux_host\",\"vendor\":\"SmokeTestCo\",\"description\":\"created by smoke_test\"}}")
assert_json "create_device echoes device_id" "$PAYLOAD" \
    "d.get('device_id')=='$NEW_ID' and ('status' in d or 'created_at' in d)"

# 6. update_device — rename linux host's hostname, then verify via get_device.
NEW_HOSTNAME="linux-host-01-renamed"
PAYLOAD=$(mcp_call "$SID" "update_device" \
    "{\"device_id\":\"$LINUX_ID\",\"fields\":{\"hostname\":\"$NEW_HOSTNAME\"}}")
assert_json "update_device returns success envelope" "$PAYLOAD" \
    "d.get('status')=='updated' and d.get('device_id')=='$LINUX_ID' and int(d.get('rows', 0))>=1"

# Confirm the update actually landed by re-reading.
PAYLOAD=$(mcp_call "$SID" "get_device" "{\"device_id\":\"$LINUX_ID\"}")
assert_json "get_device confirms update_device wrote new hostname" "$PAYLOAD" \
    "d.get('hostname')=='$NEW_HOSTNAME'"

# Restore the original hostname so the search_devices assertion above remains
# valid for re-runs (and so future runs see consistent state).
mcp_call "$SID" "update_device" \
    "{\"device_id\":\"$LINUX_ID\",\"fields\":{\"hostname\":\"$LINUX_HOST\"}}" >/dev/null

# 7. get_device_relationships — switch has 2 relationships (one as source,
# one as target). The server returns both directions.
PAYLOAD=$(mcp_call "$SID" "get_device_relationships" "{\"device_id\":\"$SWITCH_ID\"}")
assert_json "get_device_relationships($SWITCH_ID) returns 2 entries" "$PAYLOAD" \
    "(isinstance(d, list)) and len(d)==2 and all({'source_device_id','target_device_id','relationship_type'}.issubset(set(x.keys())) for x in d)"

# 8. delete_device — seed a throwaway device, then delete it. Verify the
# returned envelope and confirm the row is actually gone afterwards.
DELETE_ID="smoke-delete-$$"
DELETE_HOST="smoke-delete-host-$$"
mcp_call "$SID" "create_device" \
    "{\"device\":{\"device_id\":\"$DELETE_ID\",\"hostname\":\"$DELETE_HOST\",\"ip_address\":\"192.168.99.$$\",\"device_type\":\"linux_host\",\"vendor\":\"SmokeTestCo\",\"description\":\"smoke-test throwaway\"}}" >/dev/null

PAYLOAD=$(mcp_call "$SID" "delete_device" "{\"device_id\":\"$DELETE_ID\"}")
assert_json "delete_device returns success envelope with deleted_record" "$PAYLOAD" \
    "d.get('status')=='deleted' and d.get('device_id')=='$DELETE_ID' and int(d.get('rows', 0))==1 and isinstance(d.get('deleted_record'), dict) and d['deleted_record'].get('device_id')=='$DELETE_ID' and d['deleted_record'].get('hostname')=='$DELETE_HOST'"

# Confirm the row is really gone by re-reading via get_device (should error).
PAYLOAD=$(mcp_call "$SID" "get_device" "{\"device_id\":\"$DELETE_ID\"}")
assert_json "get_device after delete_device returns not found" "$PAYLOAD" \
    "d.get('error')=='not found' and d.get('device_id')=='$DELETE_ID'"

# ---------------------------------------------------------------------------
# nmap-discovery wrapper
# ---------------------------------------------------------------------------

section "nmap-discovery wrapper (port $NMAP_PORT)"

# Try the conventional healthcheck endpoints first.
NMAP_HEALTH_OK=0
for path in /health /healthz /ready /; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$NMAP_HOST:$NMAP_PORT$path" 2>/dev/null || echo 000)
    if [ "$code" = "200" ]; then
        pass "nmap-discovery GET $path -> 200"
        NMAP_HEALTH_OK=1
        break
    fi
done

if [ "$NMAP_HEALTH_OK" -eq 0 ]; then
    # Fallback: TCP socket connect. Per task spec this is an acceptable pass.
    if python3 -c "
import socket, sys
s = socket.socket()
s.settimeout(3)
try:
    s.connect(('$NMAP_HOST', $NMAP_PORT))
    s.close()
except Exception as e:
    print('connect failed:', e); sys.exit(1)
sys.exit(0)
" >/dev/null 2>&1; then
        pass "nmap-discovery TCP connect to $NMAP_HOST:$NMAP_PORT (no healthcheck endpoint exposed)"
    else
        fail "nmap-discovery reachable" "no healthcheck endpoint AND TCP connect failed on $NMAP_HOST:$NMAP_PORT"
    fi
fi

# ---------------------------------------------------------------------------
# Wrap-up
# ---------------------------------------------------------------------------

section "summary"
printf '  passed: %d\n  failed: %d\n' "$PASS_COUNT" "$FAIL_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
    printf '\n%sFAIL%s: %s\n' "$C_FAIL" "$C_RESET" "$FAIL_NAME"
    exit 1
fi
printf '%sOK%s: all smoke checks passed\n' "$C_PASS" "$C_RESET"
exit 0