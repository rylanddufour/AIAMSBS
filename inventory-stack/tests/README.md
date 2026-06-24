# inventory-stack smoke tests

Reproducible end-to-end check for the inventory MCP server and the
nmap-discovery wrapper. Seeds three representative devices + two
relationships into `/data/inventory.db`, then exercises every tool the
MCP server exposes plus a TCP probe of the nmap-discovery port.

## Files

- `seed.sql`  — INSERT 3 fixture devices (linux host, switch, AP) and 2
  relationships. Begins with `DELETE FROM` on both tables so it's
  idempotent.
- `seed.py`   — Python driver that pipes `seed.sql` into the running
  `inventory-mcp` container via `docker exec` (or `sudo -n docker exec`
  when the daemon socket needs elevation). Falls back to writing a
  local sqlite file when `--db PATH` is passed.
- `smoke_test.sh` — bash harness. Seeds the DB, opens an MCP session,
  calls all 7 tools, and probes the nmap-discovery wrapper.
- `README.md` — this file.

## Running

The stack must already be up:

```
cd inventory-stack/
docker compose up -d
docker compose --profile discovery up -d nmap-discovery
```

Then from `inventory-stack/`:

```
bash tests/smoke_test.sh
```

Exit 0 = every check passed. The first failing check prints its name
and the script returns 1.

## What it verifies

| Step                       | What it checks                                    |
|----------------------------|---------------------------------------------------|
| seed                       | seed.py clears + reinserts fixtures               |
| container presence         | inventory-mcp is in `docker ps`                   |
| MCP initialize             | `/mcp` returns a `mcp-session-id` and 200 OK      |
| `get_device`               | round-trips the seeded linux host                 |
| `lookup_by_ip`             | round-trips the seeded switch                     |
| `lookup_by_hostname`       | round-trips the seeded AP                         |
| `search_devices`           | query="linux" finds the linux host, no others     |
| `create_device`            | echoes the new device_id with `status`/`created_at` |
| `update_device`            | returns success envelope + `get_device` confirms the rename |
| `get_device_relationships` | switch has 2 entries                              |
| nmap-discovery             | TCP connect to 127.0.0.1:8002                     |

## MCP wire format

The server returns `streamable-http` SSE — each `tools/call` reply is a
single `event: message` frame with a `data:` line containing the
JSON-RPC envelope. FastMCP puts each list element of a tool's return
value into a separate `content` item, so `search_devices` and
`get_device_relationships` return multiple `content` entries (one per
match). `smoke_test.sh`'s `mcp_call` helper re-assembles those into a
single JSON document (dict for 1 hit, list for N hits).

The MCP streamable-http transport also requires both `Content-Type:
application/json` and `Accept: application/json, text/event-stream`
on every POST — bare `Accept: */*` will get a 406.

## Idempotency

`smoke_test.sh` clears the inventory DB on every run (via the
`DELETE FROM` at the top of `seed.sql`), so re-runs always converge on
the same fixture state. The test also restores the linux host's
hostname after the `update_device` check so subsequent runs see the
expected `hostname="linux-host-01"`.

## Known followups (not fixed by this script)

- `inventory-mcp` shows `(unhealthy)` in `docker compose ps` because
  the phase-1 healthcheck probes `/mcp` with a bare GET — MCP
  streamable-http expects POST + the JSON-RPC `initialize` payload.
  The probe should be replaced (e.g. socket-connect to port 8001) in
  a follow-up card.
- The nmap-discovery FastAPI app exposes only `/scan` — no `/health`
  endpoint. The TCP-socket fallback in `smoke_test.sh` covers this.