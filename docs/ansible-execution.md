# Ansible execution — how a playbook run actually happens

This is the user-facing guide to the v1.0 Ansible execution path
(BACKLOG #64, Card 7). For stack internals, see
`aiamsbs-ansible-stack/README.md`. For the customer-facing TL;DR,
see `docs/v1-private-customer-runbook.md`.

## Why three containers?

The v1.0 Ansible path deliberately splits into three roles on the
shared `monitoring` Docker network:

| Container                | Role                                                                 | Privileges |
|--------------------------|----------------------------------------------------------------------|------------|
| `aiamsbs-ansible`        | Stock `ansible-core` runtime. Stays alive so the runner can exec.    | none |
| `aiamsbs-ansible-runner` | Thin FastAPI bridge. Verifies HMAC, calls `docker exec`.             | **only one with `/var/run/docker.sock`** |
| `streamlit-ui`           | Customer-facing UI. Stages runs, awaits Confirm, polls for results.  | none (no docker socket, no ansible) |

This split is the v1.0 trust boundary. Streamlit never has docker
socket access. The agent (chat) never has direct runner access.
Only the customer's click in the UI moves a run from "pending" to
"running".

## The flow

1. **Customer picks a run.** On the Streamlit **Run Playbook** page
   the customer selects:
   - inventory file (e.g. `inventory/static/prod`)
   - playbook file (e.g. `playbooks/customer/daily-health.yml`)
   - target (e.g. `web-prod-01` or `all`)
   - mode (`check` or `apply`)
   - extra vars (free-form key/value JSON, optional)

2. **Streamlit writes a pending run to the SQLite `playbook_runs` table**
   with `status=pending`, `run_id=<uuid>`, and the body the runner
   will eventually receive. The customer sees a confirmation screen
   with a red **Confirm** button.

3. **Customer clicks Confirm.** The browser POSTs to Streamlit's
   `/confirm` endpoint. Streamlit:
   - reads the pending body from SQLite
   - HMAC-signs the **raw** body with `RUNNER_HMAC_SECRET` (SHA-256)
   - POSTs to `http://aiamsbs-ansible-runner:8000/run` on the
     monitoring network with header `X-Signature: sha256=<hex>`

4. **Runner validates.** `aiamsbs-ansible-runner`:
   - recomputes HMAC over the raw body
   - 401s on mismatch (with a 5s sleep to slow brute force)
   - on match, marks the run `status=running` in the runner's
     in-memory state
   - calls `docker exec aiamsbs-ansible ansible-playbook -i
     /ansible/<inventory> /ansible/<playbook> --<mode> [extra vars]`
   - streams stdout/stderr line-by-line to NDJSON
   - writes each line to
     `/home/ansible/.hermes/logs/aiamsbs-ansible/<run_id>.log`

5. **Alloy tails and ships.** The host's Grafana Alloy (config in
   `config/alloy.yml`) reads the NDJSON file and ships to Loki with
   labels `{job="aiamsbs-ansible", run_id="<uuid>", source="aiamsbs_host"}`.

6. **Streamlit polls.** The browser long-polls the runner's
   `/runs/<run_id>` endpoint. When the runner's `docker exec`
   returns, the response includes `exit_code`, `log_line_count`,
   and a Loki link. Streamlit updates the row in `playbook_runs`
   to `status=complete` (or `failed`).

7. **Run History shows it.** The customer reloads the
   **Run History** page and sees the completed run, exit code,
   log line count, and a clickable link to the Loki query for
   `run_id=<uuid>`.

## The trust boundary

The agent **never** calls `aiamsbs-ansible-runner` directly. The
agent only writes pending runs to the SQLite-backed Streamlit
confirmation screen. The customer's click is the only thing that
moves a run from pending → running.

This is enforced three ways:

1. **No agent tool for the runner.** The IT_ADMIN profile's
   `ansible-playbook-operations` skill documents this explicitly:
   "the agent MUST NOT call `aiamsbs-ansible-runner` directly. It
   only writes to the confirmation screen." (See
   `profiles/it_admin/skills/ansible-playbook-operations.md`.)
2. **No docker socket on streamlit-ui.** The compose file
   (`streamlit-ui-stack/docker-compose.yml`) does not bind-mount
   `/var/run/docker.sock` to streamlit-ui. Only the runner has it.
3. **HMAC signature.** Even if a malicious page managed to call
   the runner, the runner's HMAC check fails without
   `RUNNER_HMAC_SECRET`. The Streamlit app reads the same secret
   from `STREAMLIT_RUNNER_HMAC_SECRET` (default `dev-secret-rotate-me`).

In v1.0 private customer deployments the secret stays at the
default (one customer = one host = low blast radius). For v2
multi-tenant, rotate per-customer and put the secret in
`/home/ansible/AIAMSBS/.env` on the customer host.

## How to use it (3 examples)

### Run the daily health check (read-only)

- Inventory: `inventory/static/all`
- Playbook: `playbooks/customer/daily-health.yml`
- Target: `all`
- Mode: `check`
- Extra vars: `{}`

Click Confirm. The runner reports `exit_code=0` and the per-host
`ok / changed / skipped / unreachable` counts stream to Loki
under `run_id=<uuid>`. Reload Run History to see the result.

### Reboot web-prod-01

- Inventory: `inventory/static/prod`
- Playbook: `playbooks/generated/reboot.yml` (or a customer
  `playbooks/customer/reboot.yml` if it exists)
- Target: `web-prod-01`
- Mode: `apply`
- Extra vars: `{}`

Click Confirm. The runner execs the reboot. Loki logs every
`ansible.builtin.reboot` task line. Run History shows the
final exit code (0 on success, non-zero on failure).

### List devices (NOT a playbook run)

If the user wants to *see* devices — not run anything on them —
use the **Inventory Search** page, or ask the agent in
**Agent Chat** ("list my devices"). Inventory lookups don't go
through the runner. They go through `inventory-mcp` and return
in milliseconds.

## Logs in Loki

Useful Grafana / Loki queries:

- All ansible runs (any run_id):
  `{job="aiamsbs-ansible"}`
- One specific run:
  `{job="aiamsbs-ansible", run_id="<uuid>"}`
- Only errors:
  `{job="aiamsbs-ansible"} |= "ERROR"`
- Per-host:
  `{job="aiamsbs-ansible"} |= "web-prod-01"`

The NDJSON file on the host lives at
`/home/ansible/.hermes/logs/aiamsbs-ansible/<run_id>.log`. Read
it directly with `tail -f` while a run is in progress.

## Cross-references

- `aiamsbs-ansible-stack/README.md` — stack internals (HMAC secret
  rotation, bind mounts, healthchecks).
- `streamlit-ui-stack/README.md` — UI internals.
- `docs/streamlit-ui.md` — UI user guide.
- `docs/v1-private-customer-runbook.md` — first 30 minutes.
- `profiles/it_admin/skills/ansible-playbook-operations.md` — the
  agent skill that teaches Hermes to stage runs (not run them).
