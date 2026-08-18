# aiamsbs-ansible-stack

AIAMSBS v1.0 customer Ansible execution side (BACKLOG #64, Card 2).

Two sibling containers on the shared `monitoring` Docker network:

| Container                | Purpose                                                       | Exposed?      |
|--------------------------|---------------------------------------------------------------|---------------|
| `aiamsbs-ansible`        | Stock Ansible runtime (`ansible-core` + 3 OEM collections)    | No            |
| `aiamsbs-ansible-runner` | Thin FastAPI bridge with HMAC verification + docker socket    | No            |

The runner is the **only** container in v1.0 with `/var/run/docker.sock`
mounted. Streamlit (Card 3) talks to the runner over HTTP on the monitoring
network — Streamlit never sees the socket. This eliminates the
streamlit → docker.sock privilege escalation risk flagged in the #64
prompt.

Both containers write to a shared `/ansible/logs/*.log` (NDJSON) on the
host; the existing AIAMSBS `alloy` container tails that directory and
ships it to `loki:3100` with labels `{job="aiamsbs-ansible", source="aiamsbs_host"}`.

## Layout

```
aiamsbs-ansible-stack/
├── docker-compose.yml              # aiamsbs-ansible + aiamsbs-ansible-runner
├── README.md                       # this file
├── loki_logger.py                  # shared log shipper (NDJSON append)
├── aiamsbs-ansible/
│   ├── Dockerfile                  # python:3.12-slim + ansible-core 2.16.3
│   └── entrypoint.sh               # sleep infinity (so docker exec works)
├── aiamsbs-ansible-runner/
│   ├── Dockerfile                  # python:3.12-slim + fastapi + docker SDK
│   └── main.py                     # FastAPI: POST /run + GET /health + HMAC
├── playbooks/
│   ├── customer/                   # customer-authored playbooks (rw)
│   └── generated/                  # AIAMSBS-generated playbooks (rw)
│       └── hello.yml               # trivial test playbook for E2E verify
├── inventory/
│   ├── static/                     # hand-edited inventories (rw)
│   │   └── localhost
│   └── generated/                  # script-built inventories (rw)
├── artifacts/                      # ansible output (facts cache, callback)
└── logs/                           # loki_logger NDJSON output (alloy tails)
```

## Bring it up

```bash
cd /home/ansible/AIAMSBS
docker compose -f aiamsbs-ansible-stack/docker-compose.yml up -d --build
```

Both containers join the existing `monitoring` Docker network (external;
defined by the main AIAMSBS `docker-compose.yml`).

## Test the runner

The runner has **no host port** — it lives on the monitoring network only.
Reach it via the container's IP on that network:

```bash
RUNNER_IP=$(docker inspect -f \
    '{{.NetworkSettings.Networks.monitoring.IPAddress}}' \
    aiamsbs-ansible-runner)
curl -s http://${RUNNER_IP}:8000/health
# → {"status":"ok","containers":["aiamsbs-ansible"]}
```

Sign a test request and POST `/run`:

```bash
BODY='{"inventory":"inventory/static/localhost","playbook":"playbooks/generated/hello.yml"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "dev-secret-rotate-me" | awk '{print $2}')
curl -sS -X POST http://${RUNNER_IP}:8000/run \
    -H "Content-Type: application/json" \
    -H "X-Signature: sha256=${SIG}" \
    -d "$BODY"
```

The response is an NDJSON stream (one JSON object per line). The final
line has `{"event": "exit", "exit_code": 0}` on success.

A bad signature returns **401**:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -X POST http://${RUNNER_IP}:8000/run \
    -H "Content-Type: application/json" \
    -H "X-Signature: sha256=deadbeef" \
    -d "$BODY"
# → 401
```

## Verify Loki got the entry

```bash
curl -s -G http://localhost:3100/loki/api/v1/query \
    --data-urlencode 'query={job="aiamsbs-ansible"}' \
    | jq '.data.result | length'
# → ≥ 1 within ~30s of the run
```

## HMAC secret rotation

The runner reads `RUNNER_HMAC_SECRET` from the container environment. For
local dev it defaults to `dev-secret-rotate-me` (matches the example
above). For production:

1. Create `/home/ansible/AIAMSBS/.env` (gitignored) with:
   ```
   RUNNER_HMAC_SECRET=<long-random-string>
   ```
2. Re-deploy:
   ```bash
   docker compose -f aiamsbs-ansible-stack/docker-compose.yml \
       --env-file /home/ansible/AIAMSBS/.env \
       up -d --build
   ```
3. All callers (Streamlit in Card 3, any external client) must use the
   same secret. Clients sign the **raw** request body with HMAC-SHA256
   and pass it as `X-Signature: sha256=<hex>`.

Card 7 (E2E + bootstrap integration) will wire this into `bootstrap.sh`
and the customer-side overlay compose.

## What lives where at runtime

| Host path                                            | Container path          | Notes                                                |
|------------------------------------------------------|-------------------------|------------------------------------------------------|
| `./playbooks/customer`                               | `/ansible/playbooks/customer` | rw; customer-authored playbooks                |
| `./playbooks/generated`                              | `/ansible/playbooks/generated` | rw; AIAMSBS-generated playbooks (Card 4+)     |
| `./inventory/static`                                 | `/ansible/inventory/static` | rw; hand-edited inventories                    |
| `./inventory/generated`                              | `/ansible/inventory/generated` | rw; script-built inventories (Card 6)       |
| `./artifacts`                                        | `/ansible/artifacts`    | rw; ansible facts cache + callback output            |
| `./logs`                                             | `/ansible/logs`         | rw; loki_logger NDJSON; alloy tails this             |

## Built-in ansible collections

- `cisco.ios` 6.1.0
- `ansible.windows` 2.2.0
- `community.general` 8.4.0

Full OEM coverage is BACKLOG #59 territory; v1.0 ships with these three
because they're sufficient for the Card 4 "Run Playbook" demo and most
SMB network device / Windows server automation.

## Card scope

- ✅ Built: Ansible container + runner container + Loki plumbing
- ⏭️ Card 3: Streamlit UI (`streamlit-ui-stack/`)
- ⏭️ Card 4: Run Playbook confirmation flow + HMAC client
- ⏭️ Card 7: Overlay compose (`docker-compose.v1-private.yml`) + bootstrap integration

## Card status

- Card 2 (this card): containers + Loki plumbing + E2E verify on .220.
- Card 3: Streamlit sibling stack — own card.
- Card 4: Run Playbook UI — owns the confirmation flow + HMAC client.
- Card 7: E2E + bootstrap — owns `deploy_aiamsbs_ansible_stack()` and
  the customer overlay compose.

---

## Card 7 integration (BACKLOG #64, Card 7)

As of Card 7 this stack is **never deployed standalone** on a customer
host. The customer-facing install path is the overlay compose at the
repo root:

```bash
cd ~/AIAMSBS
docker compose -f docker-compose.yml -f docker-compose.v1-private.yml up -d
```

The overlay `include:`s `aiamsbs-ansible-stack/docker-compose.yml` (this
file) and `streamlit-ui-stack/docker-compose.yml`, so the bind mounts,
env vars, healthchecks, and image tags defined here flow through
unchanged. The overlay only adds a `aiamsbs-v1-private=true` label to
the three v1.0 services (so `docker ps --filter label=aiamsbs-v1-private`
is the canonical "is the v1.0 stack up?" check).

`bootstrap.sh` gains two new functions called from `main()`:

- `deploy_aiamsbs_ansible_stack()` — gated on `AIAMSBS_DEPLOY_V1_PRIVATE=true`
  (or `--v1-private`). Calls
  `docker compose -f docker-compose.yml -f docker-compose.v1-private.yml up -d
  aiamsbs-ansible aiamsbs-ansible-runner`.
- `deploy_streamlit_ui_stack()` — same gate, scopes to `streamlit-ui`.

Both functions are idempotent (a no-op on a healthy install) and
hard-gated (the main branch never deploys v1.0 features unless the
customer opts in). The pre-Card 7 standalone `docker compose -f
aiamsbs-ansible-stack/docker-compose.yml up -d` invocation still works
for dev, but is **not** the customer path.