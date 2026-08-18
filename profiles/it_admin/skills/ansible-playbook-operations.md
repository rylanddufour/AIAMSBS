---
name: ansible-playbook-operations
version: 1.0
when: ansible
when: playbook
when: run against
when: run playbook
when: execute playbook
when: apply playbook
when: check mode
when: run on host
profile: it_admin
description: How the IT_ADMIN agent runs Ansible playbooks against customer devices via the v1.0 private-customer Streamlit UI.
---

# ansible-playbook-operations

This is the **canonical** playbook-execution skill for the IT_ADMIN
profile. It teaches the agent how to hand a playbook run to the customer's
**Streamlit UI confirmation screen** so the customer (or their admin) is
the one who actually clicks Confirm and triggers the runner.

If the user wants to *talk about* Ansible (e.g. "what is a playbook
check?", "how do handlers work?") use the regular conversational path;
this skill is for **operationally running** a playbook.

## When to use

Use this skill when the user says any of:

- "run the playbook"
- "apply this playbook to web-prod-01"
- "reboot web-prod-01"
- "run the daily health check"
- "execute inventory/refresh"
- "run a check-mode dry run"
- "what's on app-prod-02 right now?" (often needs `ansible.builtin.setup` /
  facts via a play first)

Do **not** use this skill for read-only inventory lookup — that is the
`inventory-mcp` skill, and inventory-mcp's `inventory_list_devices`
returns the canonical device list without spinning the runner.

## The flow (v1.0)

The agent never calls the runner directly. The customer's **Streamlit
UI** owns the confirm button. Sequence:

1. **Identify the playbook needed.** Match the user's intent to a
   playbook file under `/ansible/playbooks/{customer,generated}/`. The
   `customer/` tree holds human-edited playbooks the customer trusts
   (e.g. `daily-health.yml`); `generated/` holds agent-built one-shots
   (e.g. `reboot.yml`).
2. **Identify the inventory + target.** Use `inventory_list_devices`
   (inventory-mcp tool) to confirm the target hostname or group
   actually exists in the customer's inventory tree.
3. **Construct the request body:**
   ```json
   {
     "inventory": "inventory/<...>",
     "playbook": "playbooks/<...>",
     "target": "<hostname or group or 'all'>",
     "mode": "check",
     "extra_vars": {}
   }
   ```
   Default to `mode=check` for the first run. The customer can switch
   to `apply` from the UI.
4. **POST the request to the Streamlit UI's confirmation screen.**
   The agent writes the pending run to the UI's `/confirm` page
   (`POST http://streamlit-ui:8501/...` over the `monitoring` network,
   via the UI's internal API surface). **The agent MUST NOT call
   `aiamsbs-ansible-runner` directly** — it has no UI in front of it,
   so direct agent calls would bypass the human-in-the-loop trust
   boundary.
5. **Wait for the customer to click Confirm** in the Streamlit UI.
   The UI surfaces a `target`, `playbook`, `mode`, and a red
   "Run Now" button. The customer's eye + click is the v1.0 trust
   boundary.
6. **The runner executes.** On Confirm, the UI HMAC-signs the body
   with `RUNNER_HMAC_SECRET` and POSTs to
   `http://aiamsbs-ansible-runner:8000/runs`. The runner then runs
   `docker exec aiamsbs-ansible ansible-playbook ...` and streams
   NDJSON to `${HOME}/.hermes/logs/aiamsbs-ansible/`.
7. **Loki picks it up.** The host's Grafana Alloy tails that NDJSON
   directory and ships to Loki with label
   `{job="aiamsbs-ansible", run_id=<uuid>}`. The customer can
   query `run_id` in Grafana's Explore / Loki to see the live stream.
8. **Report back.** The UI polls the runner for the run summary
   (status, exit_code, log line count, Loki link) and renders it
   on the **Run History** page. The agent reads that summary via
   the same UI and reports to the user.

## Critical safety boundary

> The agent MUST NOT call `aiamsbs-ansible-runner` directly. It only
> writes the pending run to the Streamlit UI's confirmation screen.
> The customer (or their admin) clicks Confirm in the UI before
> anything runs on a real device. This is the v1.0 trust boundary.

Why: a direct agent→runner call would be an LLM-issued shell on a
customer device with no human in the loop. The Streamlit UI exists
specifically to make every playbook run an *explicit human-issued*
operation. Even if the user types "just do it" in chat, the agent
writes the pending run and waits for the button.

If the user *insists* on bypassing the UI (e.g. "I'm the only admin
here, skip the click"), the agent should:

1. Remind them the UI click is the v1.0 safety boundary.
2. Offer a *test-mode* alternative (a `mode=check` dry run that the
   agent **can** queue without a click — the runner respects the
   same `mode=check` flag for both UI- and agent-initiated runs).
3. If the customer persists, escalate to the human admin (do not
   silently escalate to apply-mode).

## Tool calls available to the agent

- `kb_search(query, top_k=5)` — read past incident / runbook entries
  before running a playbook against a device. (BACKLOG #30 K2,
  registered via `register_kb_mcp`.)
- `inventory_list_devices(filters={...})` — confirm the target exists
  in inventory before running. (BACKLOG #39.2, registered via
  `register_inventory_mcp`.)
- The Streamlit UI's confirmation screen write API (agent-side helper
  inside the Streamlit app — exposed to the agent via Hermes's
  `delegate_task` shape).

The agent does **not** have a direct `ansible-playbook` tool. It does
**not** have a `docker exec` tool. It does **not** have a runner
HTTP client. Anything that touches a customer device routes through
the UI's Confirm button.

## Examples (3 worked)

### Example 1 — "Reboot web-prod-01"

User intent: one-shot reboot of a single prod web host. The agent
synthesizes a `reboot.yml` in `playbooks/generated/` (Card 2 ships a
template) and stages it for confirmation.

- **Playbook**: `playbooks/generated/reboot.yml`
  (or a customer-specific one if it already exists in
  `playbooks/customer/reboot.yml` — prefer customer tree)
- **Inventory**: `inventory/static/prod`
- **Target**: `web-prod-01`
- **Mode**: `apply` (it's a reboot; check-mode is meaningless)
- **Extra vars**: `{}` (or `{"reboot_delay": 5}` if the customer
  playbook uses it)

The agent posts the pending run to the UI's confirmation screen,
tells the user "I have a reboot staged for web-prod-01 in apply
mode — please click Confirm in the Streamlit UI", and waits. The
customer clicks Confirm, the runner `docker exec`s
`ansible-playbook` with the inventory + target, streams to Loki,
and the UI's Run History page shows `exit_code=0` after ~30s.

### Example 2 — "Run the daily health check"

User intent: a recurring, read-only check. Default to check-mode even
on the first run — health checks are safe and the customer usually
wants to see the output before applying any auto-remediation.

- **Playbook**: `playbooks/customer/daily-health.yml`
- **Inventory**: `inventory/static/all`
- **Target**: `all`
- **Mode**: `check` (first run); the customer can switch to `apply`
  in the UI if their playbook has a remediation block gated on
  `mode=apply`.
- **Extra vars**: `{}`

The agent stages the run, the customer clicks Confirm, the runner
runs `ansible-playbook --check ...` against every host, and the UI's
Run History shows the per-host `ok / changed / skipped / unreachable`
counts. Loki retains the full NDJSON for 30 days (customer-configurable
in the v1.1 backlog).

### Example 3 — "List devices" (NOT a playbook call)

If the user asks for an inventory list ("what devices do I have?",
"is there a host called web-prod-01?", "show me the prod group"),
the agent uses the `inventory-mcp` skill and the
`inventory_list_devices` tool. **No playbook, no Streamlit UI, no
runner.** The agent returns the device list directly from SQLite.

This is intentional: most "is X there?" or "show me Y" questions
should not stage a run. Only requests with an operational verb
("run", "apply", "check", "reboot", "restart", "deploy", "roll out",
"sync", "refresh", "rotate") need the playbook flow.

## Front matter — trigger phrases

The YAML front matter at the top lists the trigger phrases Hermes uses
to auto-load this skill. Edit them only by adding new phrases;
removing `when: ansible` or `when: playbook` will break auto-loading
for the most common phrasings.

## Cross-references

- **BACKLOG #59** — AIAMSBS Ansible fleet (long-term vision: agent
  auto-generates + versions playbooks per device class).
- **BACKLOG #61** — *Superseded* by #64 (this skill's spec is the
  final one).
- **BACKLOG #64** — v1.0 private customer deployment (this skill is
  one of the 7 deliverables).
