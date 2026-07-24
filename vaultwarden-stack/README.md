# vaultwarden-stack

AIAMSBS Runtime Vault — BACKLOG #48 + #49.

Self-hosted password/secret vault (`vaultwarden`) + the official Bitwarden
MCP server (`bitwarden/mcp-server`, **installed host-local per its README
warning**) on the AIAMSBS host. Provides credential storage for
`kb_ingest_share` (BACKLOG #50) and customer-facing secret management.

| service | role | where |
|---|---|---|
| **vaultwarden** | Self-hosted Bitwarden-compatible server. Customer's web vault UI (admin panel + day-to-day use). | `vaultwarden-stack/docker-compose.yml` (container) |
| **bitwarden-mcp** | Official Bitwarden MCP server (`@bitwarden/mcp-server`). Exposes Bitwarden CLI as MCP tools (`get_item`, `list_items`, `create_item`, …) for the agent. Talks to vaultwarden over `BW_API_BASE_URL`/`BW_IDENTITY_URL`. | `vaultwarden-stack/install-bitwarden-mcp-host.sh` — **host-local** (not a container, per upstream README warning) |

## Layout

```
vaultwarden-stack/
├── docker-compose.yml                       # vaultwarden ONLY (no bitwarden-mcp container)
├── bitwarden-mcp/
│   └── launch-bitwarden-mcp.sh              # host-local shim: bw login --apikey + exec mcp-server-bitwarden
├── install-bitwarden-mcp-host.sh            # idempotent: npm install -g @bitwarden/cli @bitwarden/mcp-server
├── generate-admin-token.sh                  # bootstrap calls this; writes /etc/vaultwarden/admin-token mode 0600
├── README.md                                # this file
└── .gitignore
```

## Run it (the bootstrap does this for you)

```bash
cd vaultwarden-stack
sudo ./generate-admin-token.sh       # one-time, idempotent (preserves existing token)
sg docker -c "docker compose up -d"  # pulls + starts vaultwarden
curl -s http://localhost:8003/alive  # sanity check — vaultwarden healthcheck endpoint
./install-bitwarden-mcp-host.sh      # host-local npm install for bw + mcp-server-bitwarden
```

## Customer onboarding (client_credentials model)

The customer (small IT shop) owns the vault entirely. The agent never
sees the customer's master password — only an **org-scoped machine account
API key** (Bitwarden's API-key flow with `client_id` + `client_secret`).
This is BACKLOG #49, the model the customer explicitly approved in the
2026-07-23 Telegram thread (rejected the older `BW_USER`+`BW_PASSWORD`
design because it gave the agent full vault blast radius).

### Step 1 — open the vault + create the first user

```
http://<aiamsbs-host>:8003                  # main vault UI
http://<aiamsbs-host>:8003/admin            # admin panel (token in bootstrap output)
```

Paste the bootstrap-printed admin token at the admin panel. Create the
first user (email + master password). After the first user exists,
**disable the admin token** for safety — the customer can re-enable if
they lose access.

### Step 2 — create an org-scoped machine account

1. Sign in to the vault UI with the user from step 1.
2. Click **Organizations → New Organization**. Name it e.g.
   `AIAMSBS-agents`. This is the **only** org the agent can see.
3. Click **Organizations → AIAMSBS-agents → Settings → Machine Accounts**.
4. Click **New Machine Account** → name it `bitwarden-mcp`.
5. The org creates a `client_id` + `client_secret` pair for that
   machine account. **Copy both** — the secret is shown only once.

### Step 3 — give the agent the scoped credential

On the AIAMSBS host (the only place the env file exists):

```bash
sudo tee /etc/bitwarden-mcp.env >/dev/null <<'EOF'
BW_API_BASE_URL=http://127.0.0.1:8003
BW_IDENTITY_URL=http://127.0.0.1:8003
BW_CLIENTID=<paste from step 2>
BW_CLIENTSECRET=<paste from step 2>
EOF
sudo chmod 600 /etc/bitwarden-mcp.env
```

### Step 4 — add items the agent needs

In the vault UI, under the `AIAMSBS-agents` org (not your personal
org/collection), add the items the agent will need: SMB/NFS share
credentials for `kb_ingest_share` (BACKLOG #50), Proxmox/Grafana/etc.
API tokens, whatever.

Items in your **personal** vault collection are **not** visible to the
machine account. This is the blast-radius gate.

### Step 5 — test the agent

```bash
hermes chat -q "List the items in the AIAMSBS-agents vault org"
```

The agent authenticates via `bw login --apikey` using the env vars from
step 3, persists `BW_SESSION` to `$HOME/.local/share/bitwarden-cli/`,
and any subsequent agent calls reuse the session.

## Auth model (BACKLOG #49, choice B — approved 2026-07-23)

`bitwarden/mcp-server` is **stdio-only** (uses `StdioServerTransport`
from `@modelcontextprotocol/sdk`). Hermes reaches it via:

```yaml
mcp_servers:
  bitwarden-mcp:
    command: /home/ansible/AIAMSBS/vaultwarden-stack/bitwarden-mcp/launch-bitwarden-mcp.sh
    args: ["--stdio"]
```

The launch shim does `bw login --apikey` (using `BW_CLIENTID`/
`BW_CLIENTSECRET` from `/etc/bitwarden-mcp.env`), caches `BW_SESSION`
under `$HOME/.local/share/bitwarden-cli/`, then `exec mcp-server-bitwarden`.
NO published network port; ALL communication is over stdin/stdout.

### Why client_credentials (not username/password)

| concern | mitigation |
|---|---|
| Master password on disk → agent has full vault blast radius | Eliminated — there is no master password on disk. The `client_secret` is org-scoped; can only see items the customer put in `AIAMSBS-agents` org. |
| `BW_PASSWORD` in env file = anyone with shell on .220 owns the vault | Eliminated — `BW_CLIENTSECRET` only grants access to the org the customer defined. |
| Compromise of the machine-account credential | Customer revokes the machine account in the vault UI; existing device passwords do NOT need to be rotated. |

## What this stack is NOT

- **No password sync to Bitwarden cloud.** Vaultwarden is self-hosted; the
  customer's data never leaves the AIAMSBS host.
- **No HSM / TPM-backed key storage.** The vault encryption key is held
  in vaultwarden container memory, like any vaultwarden install. For
  higher-security deployments, see vaultwarden's YubiKey / WebAuthn 2FA
  options.
- **No TLS / reverse proxy yet.** Vault UI is plain HTTP on port 8003.
  BACKLOG row for `caddy` or `traefik` + Let's Encrypt coming.
- **Bitwarden CLI plugins not in scope.** `bw send`, `bw config`,
  `bw import` all work for the customer but the agent only uses
  `bw list items` / `bw get item` / `bw create` / `bw edit` / `bw delete`.

## Card status

| Card | Status | Notes |
|---|---|---|
| BACKLOG #48: Deploy vaultwarden as sibling docker-compose service | Built (compose, admin-token script) | Bind = `0.0.0.0:8003` (LAN-reachable); admin token in `/etc/vaultwarden/admin-token` mode 0600 |
| BACKLOG #49: Wire `bitwarden/mcp-server` against vaultwarden | Refactored | Was container; now **host-local** install per upstream README warning. Auth = `bw login --apikey` (client_credentials) per 2026-07-23 customer approval. |
| BACKLOG #50: `kb_ingest_share` MCP tool | Not built | Consumer of this stack; depends on a working machine-account flow. |
| BACKLOG #51: Documentation + diagram cards | Deferred per BACKLOG row | After #48/#49 work end-to-end. |
