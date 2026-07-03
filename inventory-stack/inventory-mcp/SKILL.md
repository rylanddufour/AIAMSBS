---
name: inventory-mcp
title: AIAMSBS Inventory MCP
description: Look up, search, create, update, and delete network device records in the AIAMSBS inventory (SQLite-backed, served by inventory-mcp on :8001).
trigger: When a user asks about a device, host, IP, MAC, or anything that should be in the network inventory. Also when ingesting new devices from nmap discovery or other sources.
---

# AIAMSBS Inventory MCP

SQLite-backed device inventory exposed via FastMCP. Registers as `inventory-mcp` in `default` and `it_admin` profiles. Server runs on `http://localhost:8001/mcp` after `bootstrap.sh` deploys the inventory stack.

**When to use this skill:** any user question about "what's on the network", "find host X", "add this device", "update the record for Y", or "delete Z". If a user is asking about a managed device, this is the first stop.

**Don't use this for:** network ops (firewall rules, switch config) — that's a different skill. Inventory is read/write of the device *registry*, not device *control*.

## Tools

| Tool | Signature | Use for |
|---|---|---|
| `get_device` | `(device_id: str) -> dict` | Exact lookup when you have the device_id |
| `lookup_by_ip` | `(ip: str) -> dict` | User gave an IP, you want the device record |
| `lookup_by_hostname` | `(hostname: str) -> dict` | User gave a hostname |
| `search_devices` | `(query, device_type='', tag='', limit=20) -> list` | Free-text search; matches device_id/hostname/IP/vendor/description/tags |
| `create_device` | `(device: dict) -> dict` | Add a new device record. `device_id` is required; other fields are optional. |
| `update_device` | `(device_id, fields: dict) -> dict` | Patch fields on an existing device. `updated_at` set automatically. |
| `delete_device` | `(device_id, cascade_relationships=True) -> dict` | **DESTRUCTIVE** — hard delete, not soft. Always confirm with the user first. |
| `get_device_relationships` | `(device_id) -> list` | Source/target relationships (e.g., "switch port X is on switch Y") |

## Valid device fields

These are the columns on the `devices` table. Use them as keys when calling `create_device` or `update_device`; unknown fields are silently dropped:

`device_id`, `hostname`, `ip_address`, `mac_address`, `device_type`, `vendor`, `model`, `management_endpoint`, `credential_ref`, `site`, `role`, `tags`, `description`, `source`, `last_seen`

## Examples

**Find a device by IP:**
```
> user: "what's at 10.0.1.42?"
> agent: lookup_by_ip("10.0.1.42") → {device_id: "...", hostname: "...", vendor: "Ubiquiti", ...}
```

**Search by free text:**
```
> user: "show me all UniFi switches"
> agent: search_devices("UniFi", device_type="switch") → [ ... ]
```

**Add a new device:**
```
> user: "we just installed a new AP at the warehouse — 10.0.5.30, UniFi U6-Pro, site=warehouse"
> agent: create_device({"device_id": "ap-warehouse-01", "ip_address": "10.0.5.30", "vendor": "UniFi", "model": "U6-Pro", "device_type": "access_point", "site": "warehouse"})
```

**Delete (always confirm first):**
```
> agent: get_device("ap-warehouse-01")  → shows user the row
> agent: "Confirm deletion of ap-warehouse-01 (and its 3 relationships)? [y/n]"
> user: "y"
> agent: delete_device("ap-warehouse-01")
```

## Pitfalls

- **`delete_device` is hard delete.** No soft-delete, no audit trail. The pattern is `search → show → confirm → delete` — never delete without showing the user the row first and getting explicit yes.
- **`device_id` is required on create.** If the user gives a hostname or IP but no device_id, derive one (e.g., `ap-<site>-<n>`) and confirm before calling.
- **Unknown fields are silently dropped on create/update.** If a field name doesn't match `VALID_DEVICE_FIELDS`, it's ignored. No error. Use the exact column names from the table above.
- **`tags` is stored as a JSON array string.** Pass it as a list when creating; it comes back as a list from `_row_to_dict`. If you get it back as a string, the JSON was malformed on insert — flag it.
- **The MCP is local-only (`localhost:8001`).** Don't try to hit it from a remote profile — the connection will be refused. The MCP and the agent that uses it must be on the same host.
- **`create_device` on a duplicate `device_id` returns a SQLite UNIQUE constraint error** (HTTP 500-shaped from the MCP). If you need upsert semantics, check first with `get_device` and `update_device` instead.
- **Don't poll.** Inventory is a small in-memory SQLite file. Reads are O(milliseconds). No need to cache, batch, or debounce.
