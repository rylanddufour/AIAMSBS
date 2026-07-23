# vaultwarden-stack

AIAMSBS Runtime Vault — BACKLOG #48 + #49.

Self-hosted password/secret vault (vaultwarden) + Bitwarden MCP server
(`bitwarden/mcp-server`) in one Docker Compose project. Provides credential
storage for `kb_ingest_share` (BACKLOG #50) and customer-facing secret
management for the AIAMSBS host.

## What it does

| service | role |
|---|---|
| **vaultwarden** | Self-hosted Bitwarden-compatible server. Customer's web vault UI lives here (admin panel for first-user creation, then the regular vault UI for day-to-day use). |
| **bitwarden-mcp** | Official Bitwarden MCP server (`@bitwarden/mcp-server`), exposes the Bitwarden CLI as MCP tools (`get_item`, `list_items`, `create_item`, etc.) for the agent. Talks to vaultwarden over `BW_API_BASE_URL`/`BW_IDENTITY_URL`. |

## Layout

    vaultwarden-stack/
    ├── docker-compose.yml          # vaultwarden + bitwarden-mcp services
    ├── bitwarden-mcp/
    │   ├── Dockerfile              # node:22-bookworm-slim + npm i -g @bitwarden/cli @bitwarden/mcp-server
    │   ├── launch-bitwarden-mcp.sh # Login/unlock wrapper, persists BW_SESSION to a volume
    │   └── .dockerignore
    ├── generate-admin-token.sh     # bootstrap calls this; writes /etc/vaultwarden/admin-token mode 0600
    ├── README.md                   # this file
    └── .gitignore

## Run it

    cd vaultwarden-stack
    docker compose up -d --build

The `bitwarden-mcp` image is built locally on first run (no pre-built image
on Docker Hub). Subsequent runs reuse the cached build.

## First-run UX

1. Customer runs `bootstrap.sh` on the AIAMSBS host.
2. Bootstrap generates `/etc/vaultwarden/admin-token` (mode 0600) and prints
   it in the "Bootstrap Complete!" output.
3. Customer browses to `http://<aiamsbs-host>:8003/admin`, pastes the admin
   token, and creates the first regular user.
4. Customer populates `/etc/bitwarden-mcp.env` with `BW_USER` and
   `BW_PASSWORD` (or `BW_CLIENTID`/`BW_CLIENTSECRET` for client-credentials
   auth — BACKLOG follow-up).
5. Customer runs `docker compose restart bitwarden-mcp`. The launch wrapper
   logs in with the credentials, unlocks the vault, and persists `BW_SESSION`
   to a named volume so subsequent restarts don't need a fresh unlock.

## Auth model (BACKLOG #49, choice A)

`bitwarden/mcp-server` is **stdio-only** (uses `StdioServerTransport` from
`@modelcontextprotocol/sdk`). Hermes reaches it via `docker exec -i
bitwarden-mcp mcp-server-bitwarden --stdio` — registered in both `default`
and `it_admin` profiles' `~/.hermes/config.yaml`. The container has no
network ports; all communication is over stdin/stdout.

The README warning ("never deploy this server to cloud hosting, containers,
or public servers") is about EXPOSURE, not containerization — we run
vaultwarden on `127.0.0.1:8003` and bitwarden-mcp with no published ports,
so the vault is not reachable from off-host.

## What this stack is NOT

- **No password sync to Bitwarden cloud.** Vaultwarden is self-hosted; the
  customer's data never leaves the AIAMSBS host.
- **No HSM / TPM-backed key storage.** The vault encryption key is held in
  the vaultwarden container's process memory, like any other vaultwarden
  install. For higher-security deployments, see vaultwarden's YubiKey /
  WebAuthn 2FA options (env vars in the compose).
- **No org / machine-account onboarding automation.** Auth choice A
  (username/password) covers the MVP. Client-credentials API key auth
  (choice B) is a follow-up row.

## Card status

- BACKLOG #48: Deploy vaultwarden as sibling docker-compose service.
- BACKLOG #49: Wire bitwarden/mcp-server against vaultwarden.
- BACKLOG #50: `kb_ingest_share` MCP tool (consumer of this stack).
- BACKLOG #51: Documentation + diagram cards (deferred).
