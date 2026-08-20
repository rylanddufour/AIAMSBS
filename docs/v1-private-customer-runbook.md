# v1.0 private customer — first 30 minutes

This is the one-page TL;DR for a v1.0 private customer (BACKLOG #64).
If you have just received a freshly-deployed AIAMSBS host, work
through this in order. Every step is something you'll actually do in
the first half hour.

If you hit a wall at any step, check the matching deep-dive doc:

- Login or UI weirdness → `docs/streamlit-ui.md`
- Run Playbook / HMAC / Loki → `docs/ansible-execution.md`
- Stack internals → `streamlit-ui-stack/README.md` and
  `aiamsbs-ansible-stack/README.md`

---

## 0. What you should have in your hand

From the operator who deployed AIAMSBS for you:

- The host's URL (e.g. `http://192.168.0.220:8501` for the UI).
- A username (`admin` by default) and a temporary password
  (`admin` by default — **change this now**).
- The customer's name (shown in the UI header).

If you don't have all three, ask the operator. Do not skip
authentication setup.

## 1. Log in (2 minutes)

1. Open the host URL in a browser.
2. You should see the AIAMSBS v1.0 login screen. Log in with
   `admin` / `admin`.
3. You land on the **Home** page. Confirm:
   - Every backend in the **Health** card is green.
   - The header shows the correct customer name.
4. If anything is red, the Home page tells you which backend is
   down. Ask the operator to check
   `docker ps --filter label=aiamsbs-v1-private` on the host.

## 2. Change the admin password (3 minutes)

The default `admin/admin` is for first-login convenience only. The
first thing you should do is rotate it.

On the host (SSH access required, or ask the operator):

```bash
# Generate a bcrypt hash for your new password
python3 -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_NEW_PASSWORD', bcrypt.gensalt()).decode())"
```

Copy the output. Then edit `/home/ansible/AIAMSBS/.env` (create it
if missing):

```
STREAMLIT_ADMIN_PASSWORD_HASH=$2b$12$...
# Leave STREAMLIT_ADMIN_PASSWORD unset so the container uses the hash.
```

Re-deploy just streamlit-ui:

```bash
cd ~/AIAMSBS
docker compose -f docker-compose.yml -f docker-compose.v1-private.yml up -d streamlit-ui
```

Log in with the new password. Done.

## 3. Add a KB entry (2 minutes)

The **KB** (knowledge base) is your runbook store. Every runbook,
incident postmortem, and "we tried X and it worked" note should
land here so future you (and the agent) can find it.

1. Open **KB Search** in the sidebar.
2. Click **Add entry**. Fill in:
   - Title: short, searchable (e.g. "OPNsense firmware upgrade")
   - Body: the actual runbook or postmortem
   - Tags: comma-separated (e.g. `opnsense, firewall, upgrade`)
3. Click **Save**.
4. Confirm by searching for one of your tags. The new entry
   should appear at the top.

Useful tag conventions: `vendor:<name>`, `os:<name>`,
`task:<verb>`, `env:prod|stage|dev`. They make cross-cutting
queries easy later.

## 4. Run a playbook (5 minutes)

This is the v1.0 trust boundary. Read `docs/ansible-execution.md`
for the full flow, but the short version is:

1. Open **Run Playbook** in the sidebar.
2. Pick an inventory file. For your first run, the
   `inventory/static/localhost` is the safest choice — it targets
   the host itself.
3. Pick a playbook file. The `playbooks/generated/hello.yml` is
   a trivial no-op that ships with the stack and is perfect for
   verifying the flow.
4. Target: `all` (or whatever your inventory defaults to).
5. Mode: **`check`** (dry run — no changes).
6. Click **Stage Run**. The confirmation screen appears.
7. Click **Confirm**. The runner executes. Watch the **Run
   History** page for the result. Expect `exit_code=0` within
   a few seconds for the hello playbook.
8. Now try `mode=apply` on the same playbook if it has an apply
   block. Otherwise write your own and stage it.

The run's full NDJSON log is in Grafana → Explore → Loki under
`{job="aiamsbs-ansible", run_id="<uuid>"}`. Click the link in
Run History to jump straight there.

## 5. Ask the agent (5 minutes)

The **Agent Chat** page is a thin UI over Hermes's
`/v1/responses` API. The agent runs as the **IT_ADMIN** profile,
which has access to:

- `kb_search` (your KB from step 3)
- `inventory_list_devices` (your devices)
- the `ansible-playbook-operations` skill (which stages runs
  for the UI, never executes directly)

Useful first questions:

- "List my devices" → uses inventory-mcp. Should return whatever
  the inventory discover cron has found.
- "Search the KB for opnsense" → uses kb_search. Should return
  the entry you added in step 3.
- "Reboot web-prod-01" → uses the ansible skill to STAGE a run.
  The agent will tell you to click Confirm in the UI. It will
  not run anything on its own.

The agent's text comes from whatever model is configured in
`HERMES_MODEL` (default `minimax/minimax-m3`). To change models,
ask the operator to update the env var in the customer's `.env`
file and re-deploy streamlit-ui.

## 6. (Optional) Add a device to inventory (10 minutes)

The **Inventory** page shows devices the host has discovered via
the daily 02:00 nmap scan. To add a device manually:

1. Open **Inventory Search**.
2. Click **Add device**. Fill in hostname, IP, OS, tags.
3. Save.

The new device is immediately visible to the agent and to your
playbooks' `inventory/static/all` group (after you add it to the
inventory file's group block, which requires SSH access to the
host — ask the operator).

## Where to go next

- `docs/streamlit-ui.md` for everything UI-shaped (auth, health,
  Loki labels, redeploy).
- `docs/ansible-execution.md` for the playbook run flow,
  HMAC, the trust boundary, and Loki query patterns.
- `BACKLOG.md` for what's planned in v1.1 (multi-user auth,
  device-class auto-generation, vault-encrypted secrets).

If something's broken and the docs don't help, the host's
Grafana (`http://<host>:3000`, default `admin`/`admin123`) has
pre-provisioned dashboards and Loki queries for everything
mentioned above. The `aiamsbs-ansible` and `aiamsbs-streamlit`
jobs are the two new ones; the rest of the stack is unchanged.
