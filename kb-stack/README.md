# kb-stack

AIAMSBS Runtime Knowledge Base — K1 (BACKLOG #30).

A FastMCP server backed by SQLite + FTS5 that exposes five knowledge-base
tools over MCP streamable-http. This card is greenfield inside
`kb-stack/`; bootstrap integration is K2 and the HTML review queue is K3.

## What it does

Stores and retrieves atomic knowledge entries (runbooks / facts / gotchas)
with a trust ladder: agent-written entries start at `status='pending'`
(level 0); customer-written entries start at `status='approved'`
(level 3); the customer can flip agent entries pending → approved/rejected
via `kb_update`.

Search is FTS5-only — BM25 ranked, no embeddings, no model calls, no
network. The justification is in
`obsidian_vaults/agent vault/AIAMSBS_Docs_Diagrams/kb_workflow.md`.

## Layout

    kb-stack/
    ├── docker-compose.yml    # kb-mcp service on 127.0.0.1:8002
    ├── mcp/
    │   ├── Dockerfile        # python:3.12-slim
    │   ├── requirements.txt  # mcp>=1.0.0
    │   ├── server.py         # FastMCP server, 7 tools
    │   └── init_db.sql       # schema + FTS5 virtual table + triggers
    ├── tests/
    │   ├── conftest.py
    │   ├── test_kb_add_and_search.py
    │   ├── test_kb_list_filter.py
    │   ├── test_kb_update.py
    │   └── test_kb_delete.py
    └── README.md

## Run it

    cd kb-stack
    docker compose up --build -d

The container binds 127.0.0.1:8002 and joins the `monitoring` external
network (same pattern as `inventory-stack`). Data persists in the named
volume `kb-data` at `/data/kb.db` inside the container.

Healthcheck is a TCP-socket probe to `127.0.0.1:8002` (no HTTP
endpoint on the server itself — FastMCP only speaks streamable-http on
`/mcp`).

## Tools

Five required + two convenience:

- `kb_search(query, limit=10, source_types=None)` — FTS5 BM25 search.
- `kb_add(content, entry_type, tags=None, source_id=None, created_by="agent")`
- `kb_update(entry_id, content=None, tags=None, status=None)`
- `kb_list(source_type=None, status=None, limit=50, offset=0)`
- `kb_delete(entry_id)` — destructive, returns the deleted row.
- `kb_add_source(name, source_type, file_path_or_url=None)` (convenience)
- `kb_list_sources()` (convenience)

## Talk to it

After `docker compose up`, the MCP endpoint is `http://127.0.0.1:8002/mcp`.
The standard MCP streamable-http handshake:

    # Initialize a session
    curl -s -D - -X POST http://127.0.0.1:8002/mcp \
      -H "Content-Type: application/json" \
      -H "Accept: application/json, text/event-stream" \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'

The response carries an `Mcp-Session-Id` header; pass it back as
`Mcp-Session-Id: <id>` on subsequent calls. The
`inventory-stack/tests/smoke_test.sh` script is a working example of
this dance for inventory-mcp on port 8001.

## Tests

    cd kb-stack
    python3 -m pytest tests/ -v

The tests import `server.py` directly and use a tmp sqlite file per
test (see `tests/conftest.py`); no running container required.

To run the tests inside the same `python:3.12-slim` image the server
uses:

    docker run --rm -v "$PWD":/app -w /app python:3.12-slim \
      bash -c "pip install -q pytest && pip install -q -r mcp/requirements.txt && pytest tests/ -v"

## Data location

- Container: `/data/kb.db`
- Named volume: `kb_data` (in the `kb-stack` project)
- Override at runtime with `KB_DB_PATH=/path/to/kb.db`

## Environment variables

- `KB_DB_PATH` — sqlite file path. Default `/data/kb.db`.

## Where the design lives

`obsidian_vaults/agent vault/AIAMSBS_Docs_Diagrams/kb_workflow.md`
(via rclone `onedrive:`).

## Card status

- K1 (this card): server + schema + tests.
- K2: bootstrap.sh integration + VM E2E.
- K3: HTML review queue UI.
- K5: doc ingestion (paste / file upload).
- K6 (BACKLOG #31): self-correcting loop.
