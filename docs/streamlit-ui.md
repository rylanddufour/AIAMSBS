# Streamlit UI — user guide

This is the customer-facing guide for the v1.0 Streamlit UI
(BACKLOG #64, Card 7). For the stack internals, see
`streamlit-ui-stack/README.md`. For first-time setup, see
`docs/v1-private-customer-runbook.md`.

## What it is

A single-page (multi-tab) Streamlit app served at
`http://<your-host>:8501/`. It is the only host-exposed port for the
v1.0 customer stack — the underlying backends (Ansible runner, KB,
inventory, Loki, Grafana, Hermes) all communicate on the internal
`monitoring` Docker network and are not directly reachable from your
browser.

## Pages

| Page          | Path                     | What it does                                                                 |
|---------------|--------------------------|------------------------------------------------------------------------------|
| **Home**      | `/`                      | Landing dashboard. Per-backend health, recent runs, recent chat sessions.   |
| **Settings**  | `/Settings`              | Read-only view of every env var + customer name + model. Health subsection. |
| **Run Playbook** | `/Run_Playbook`       | Stage a playbook run. The customer clicks Confirm. This is the v1.0 trust boundary. |
| **Run History** | `/Run_History`        | Past playbook runs with status, exit code, log line count, Loki link.       |
| **Agent Chat** | `/Agent_Chat`          | Chat with the IT_ADMIN agent. Uses Hermes `/v1/responses` (server-side MCP). |
| **KB Search** | `/KB_Search`             | Search the customer's knowledge base. Add new entries.                      |
| **Inventory Search** | `/Inventory_Search` | Browse / search the customer's device inventory.                          |

## Auth

Single admin for v1.0. Default username `admin` and password `admin`
(env var `STREAMLIT_ADMIN_PASSWORD`). For a production deploy, set
`STREAMLIT_ADMIN_PASSWORD_HASH` to a bcrypt hash (the page picks
that up automatically) and leave `_PASSWORD` unset.

Generate a bcrypt hash:

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt()).decode())"
```

Put the result in `/home/ansible/AIAMSBS/.env`:

```
STREAMLIT_ADMIN_PASSWORD_HASH=$2b$12$...your-hash...
```

Then re-deploy:

```bash
cd ~/AIAMSBS
docker compose -f docker-compose.yml -f docker-compose.v1-private.yml up -d streamlit-ui
```

The container recreates with the new env. The dev `admin/admin`
default is replaced.

## Health

The Home page shows per-backend health (Prometheus, Loki, Grafana,
KB-MCP, Inventory-MCP, Ansible runner, Hermes). The Settings page
shows the same in a denser form plus the full env. Both are read-only.

A red "unreachable" badge means one of the backends is down. Check
`docker ps --filter label=aiamsbs-v1-private` and the host's
`docker compose logs` output for the failing service.

## Where events go

Every page action writes an NDJSON line to
`/home/ansible/.hermes/logs/aiamsbs-streamlit/<stream>.log`. The
host's Grafana Alloy tails that directory and ships to Loki with
label `job="aiamsbs-streamlit"`. Each log line has a `stream` field
(`streamlit`, `chat`, `kb`, or `inventory`) for finer queries.

Useful Grafana / Loki queries:

- All streamlit events:
  `{job="aiamsbs-streamlit"}`
- Just chat sessions:
  `{job="aiamsbs-streamlit", stream="chat"}`
- Just KB activity:
  `{job="aiamsbs-streamlit", stream="kb"}`
- Just inventory lookups:
  `{job="aiamsbs-streamlit", stream="inventory"}`

## Idempotent redeploy

The container is healthy on first boot and stays up across redeploys:

```bash
cd ~/AIAMSBS
docker compose -f docker-compose.yml -f docker-compose.v1-private.yml up -d
```

No image rebuild on a clean state, no SQLite wipe, no LLM context
loss. Edit a `.py` file in `streamlit-ui-stack/streamlit-app/` and
Streamlit's live-reload picks it up without a container restart
(`server.runOnSave=true` in the Dockerfile).

## Cross-references

- `docs/ansible-execution.md` — how the Run Playbook page actually
  hands off to the runner, and the v1.0 trust boundary.
- `docs/v1-private-customer-runbook.md` — the first 30 minutes.
- `streamlit-ui-stack/README.md` — developer-facing stack doc.
