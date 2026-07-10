#!/usr/bin/env python3
"""Regenerate the Prometheus file_sd_configs target list from inventory.

Reads every device from inventory-mcp's list_devices() tool, builds a
file_sd_configs target list, writes it to
config/prometheus/targets/blackbox_inventory.json, and triggers a
Prometheus reload.

Invoked by:
  - Hermes cron (BACKLOG #39 sub-item 6, daily 02:00)
  - Manual kickoff: `python3 regenerate_blackbox.py`
  - bootstrap.sh end-of-install kickoff (BACKLOG #39 sub-item 7)

Idempotent: running twice produces the same file (modulo JSON ordering).
Handles empty inventory (writes `[]`, triggers reload, exits 0).
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

INVENTORY_URL = "http://localhost:8001/mcp"
PROM_RELOAD_URL = "http://localhost:9090/-/reload"
INSTALL_DIR = os.environ.get("AIAMSBS_INSTALL_DIR", os.path.expanduser("~/AIAMSBS"))
TARGETS_DIR = os.path.join(INSTALL_DIR, "config/prometheus/targets")
TARGETS_FILE = os.path.join(TARGETS_DIR, "blackbox_inventory.json")


def http_post_json(base_url: str, body: dict, session_id: str | None = None) -> tuple[dict, str | None]:
    """POST JSON-RPC to the MCP server, return (parsed_response, new_session_id)."""
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    req = urllib.request.Request(base_url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        sid = resp.headers.get("mcp-session-id") or session_id
        raw = resp.read().decode("utf-8")
    if raw.startswith("event:"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                raw = line[len("data:"):].strip()
                break
    return json.loads(raw), sid


def list_inventory_devices() -> list[dict]:
    """MCP handshake + list_devices() call. Returns list of device dicts."""
    init_resp, sid = http_post_json(INVENTORY_URL, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "aiamsbs-regen-blackbox", "version": "1.0.0"}},
    })
    if not sid:
        raise SystemExit("inventory-mcp did not return a session id")
    # notifications/initialized (no body expected)
    http_post_json(INVENTORY_URL, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id=sid)
    resp, _ = http_post_json(INVENTORY_URL, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "list_devices", "arguments": {}},
    }, session_id=sid)
    if "error" in resp:
        raise SystemExit(f"inventory-mcp returned protocol error: {resp['error']}")
    result = resp.get("result", {})
    if result.get("isError"):
        content = result.get("content", [])
        msg = content[0].get("text", "<no content>") if content else "<no content>"
        raise SystemExit(f"list_devices tool error: {msg[:200]}")
    # tool result text is JSON-encoded string per FastMCP convention
    text = result.get("content", [{}])[0].get("text", "[]")
    return json.loads(text)


def build_target_groups(devices: list[dict]) -> list[list[dict]]:
    """Build Prometheus file_sd_configs target list.

    Returns a list of target groups, one group per device. Each group is a list
    of {"targets": [...], "labels": {...}}. Using one group per device keeps
    the labels scoped tightly to that host.
    """
    groups = []
    for d in devices:
        ip = d.get("device_id") or d.get("ip_address")
        if not ip:
            continue
        host = d.get("hostname") or ip
        device_type = d.get("device_type") or "unknown"
        groups.append([{
            "targets": [ip],
            "labels": {
                "host": host,
                "device_type": device_type[:50],
            },
        }])
    return groups


def write_targets_file(groups: list[list[dict]]) -> None:
    """Atomically write the targets JSON. write-temp + rename is safe here:
    the bind-mount is on the DIRECTORY (not a single file), so the new file
    appears atomically under the watched glob. Avoids the inode-bind-mount
    trap that bites prometheus.yml direct edits.
    """
    os.makedirs(TARGETS_DIR, exist_ok=True)
    tmp = TARGETS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(groups, f, indent=2)
        f.write("\n")
    os.replace(tmp, TARGETS_FILE)


def reload_prometheus() -> None:
    """POST /-/reload. The /-/reload endpoint is enabled by
    --web.enable-lifecycle in docker-compose.yml. The container stays up;
    only the in-memory config is reloaded. The targets file (via
    file_sd_configs) is re-read on the next scrape (default 60s for the
    blackbox_inventory job).
    """
    req = urllib.request.Request(PROM_RELOAD_URL, method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        if resp.status != 200:
            raise SystemExit(f"prometheus reload returned HTTP {resp.status}")


def main() -> int:
    try:
        devices = list_inventory_devices()
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        print(f"ERROR: inventory-mcp unreachable at {INVENTORY_URL}: {exc}", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: MCP handshake failed: {exc}", file=sys.stderr)
        return 1

    groups = build_target_groups(devices)
    print(f"Inventory: {len(devices)} device(s); targets file: {len(groups)} group(s)")

    try:
        write_targets_file(groups)
    except OSError as exc:
        print(f"ERROR: failed to write {TARGETS_FILE}: {exc}", file=sys.stderr)
        return 1

    try:
        reload_prometheus()
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
        print(f"ERROR: prometheus reload failed: {exc}", file=sys.stderr)
        return 1

    print(f"OK: wrote {TARGETS_FILE} ({len(groups)} target group(s)) and reloaded Prometheus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
