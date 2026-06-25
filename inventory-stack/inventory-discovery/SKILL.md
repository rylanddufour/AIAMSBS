---
name: inventory-discovery
title: Network Inventory Discovery
description: Discover devices on the customer network via nmap and store them in the inventory database. Triggered when the user asks to inventory, discover, or scan the network.
trigger: When the user asks to inventory, discover, scan, or list devices on the network
---

# Inventory Discovery

Run an nmap scan against a target CIDR and insert every discovered host into
the inventory database (exposed by the `inventory-mcp` MCP server).

## When to use this skill

Trigger this skill when the user says any of:

- "inventory the subnet 192.168.0.0/24"
- "discover devices on my network"
- "scan the VLAN X subnet"
- "what's on my network?"
- "find devices on 10.0.1.0/24"

## How to use it

1. **Extract the target CIDR** from the prompt. If the user didn't specify one,
   default to `192.168.0.0/24` (the typical home/SMB subnet). You can also
   infer from the host's primary interface:
   ```bash
   ip route | awk '/default/ {print $3}' | head -1
   # → e.g. 192.168.0.1 → assume /24 → 192.168.0.0/24
   ```

2. **Run the discovery script** with the target:
   ```bash
   $INVENTORY_DISCOVERY_DIR/scripts/discover.py 192.168.0.0/24
   ```
   `$INVENTORY_DISCOVERY_DIR` is the directory this SKILL.md lives in.

3. **Report the summary** the script prints back to the user.

## What the script does

`scripts/discover.py`:

1. Calls `GET http://localhost:8002/scan?target=<CIDR>` (the nmap-discovery
   wrapper running on the AIAMSBS host in host-network mode).
2. Parses the XML output to extract every host:
   - IPv4 address
   - MAC address (if present)
   - Hostname (if reverse-DNS resolved)
   - OS guess (if `--O` succeeded)
3. For each host, calls inventory-mcp's `create_device` tool:
   ```
   POST http://localhost:8001/mcp
   {"jsonrpc":"2.0","method":"tools/call","params":{"name":"create_device","arguments":{...}}}
   ```
4. Counts inserted vs. skipped (duplicates are skipped — inventory-mcp
   uses `device_id` as PRIMARY KEY).

## Defaults

| Knob | Default | Override |
|---|---|---|
| Target CIDR | `192.168.0.0/24` | First positional argument |
| Nmap timeout | 300s | `--max-time` flag |
| Skip duplicates | yes | always |

## Prerequisites

Both must be running (bootstrap.sh installs + starts both as of 2026-06-25):

- **nmap-discovery** container — listens on host port 8002 (`network_mode: host`,
  requires `NET_RAW + NET_ADMIN` Linux capabilities)
- **inventory-mcp** container — listens on host port 8001
- **inventory-mcp registered** in the active Hermes profile (bootstrap.sh does this)

Verify before invoking:

```bash
curl -sf http://localhost:8002/scan?target=127.0.0.1 >/dev/null && \
curl -sf -X POST http://localhost:8001/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}' \
  >/dev/null && echo "OK"
```

If either fails, tell the user: *"inventory stack is not fully deployed — run
`bootstrap.sh` to install nmap-discovery and register inventory-mcp."*

## Examples

### Example 1: explicit CIDR

```
User: "scan 10.0.1.0/24 for devices"

You: (run `discover.py 10.0.1.0/24`)
You: "Found 12 devices on 10.0.1.0/24. 11 new devices added to inventory,
      1 already existed (10.0.1.1 — gateway)."
```

### Example 2: implicit CIDR

```
User: "what's on my network?"

You: (infer CIDR from default route: 192.168.0.0/24)
You: (run `discover.py 192.168.0.0/24`)
You: "Found 8 devices on your 192.168.0.0/24 network. Here's what I see:
      - 192.168.0.1 — gateway (Linux)
      - 192.168.0.10 — desktop (Windows)
      - ..."
```

### Example 3: ambiguous

```
User: "scan the office"

You: "Which subnet? I can run discovery against 10.0.1.0/24 (the usual
      office subnet) or you can give me a specific CIDR."
```

## Out of scope

- **Active probing beyond nmap** — no SNMP polling, no SSH probes, no
  vendor-specific API calls. Inventory is layer-2/3 only.
- **Continuous monitoring** — this skill is one-shot. For periodic
  re-scans, see the `inventory-scheduler` (future) or run on cron.
- **Credential-based discovery** — no SSH keys, no SNMP v3 creds. Just
  plain nmap with what's in the WRAPPER's default command.

## Version

- Added: 2026-06-25 (Task 4 of bootstrap-customer-experience workstream)
- Status: shipped with bootstrap.sh v2.2+
- Depends on: inventory-stack/ + nmap-discovery container + inventory-mcp MCP registration