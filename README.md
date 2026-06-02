# AIAMSBS - AI Agent Managed Services for SMBs

Self-hosting infrastructure platform using Hermes Agent.

## Prerequisites

- Ubuntu Server (24.04 recommended)
- User with **sudo privileges** (Hermes runs as this user)
- Internet connectivity for downloading images

## Deployment Process

### Quick Start (Recommended)

The bootstrap script supports both CLI arguments and interactive mode. **CLI is recommended** because piped input (`curl | bash`) doesn't support interactive prompts.

```bash
# Replace YOUR_API_KEY with your actual API key
curl -fsSL https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/bootstrap.sh | bash -s -- --api-key YOUR_API_KEY --provider openrouter
```

**Supported providers:** `openai`, `anthropic`, `openrouter`, `google`

Example with model:
```bash
curl -fsSL https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/bootstrap.sh | bash -s -- --api-key sk-xxx --provider openrouter --model openai/chatgpt-4o-latest
```

### Interactive Mode (Advanced)

If you prefer to be prompted for each option, clone the script first and run it interactively:

```bash
# Download script first
curl -fsSL -o bootstrap.sh https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/bootstrap.sh

# Make executable and run (stdin will be your terminal)
chmod +x bootstrap.sh
./bootstrap.sh
```

**What bootstrap.sh does:**
- Installs Docker + Docker Compose
- Installs Hermes Agent dependencies (Python, Node.js, ffmpeg, ripgrep)
- Clones Hermes Agent repo
- Configures your API key
- Auto-deploys the monitoring stack

```bash
# Install Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Build web UI
cd ~/.hermes/hermes-agent/web
npm install
npm run build

# Create systemd service
sudo tee /etc/systemd/system/hermes-dashboard.service > /dev/null << 'EOF'
[Unit]
Description=Hermes Agent Web Dashboard
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/.hermes/hermes-agent
ExecStart=/bin/bash -c 'source .venv/bin/activate && exec hermes dashboard --port 9119 --host 0.0.0.0 --insecure --skip-build --no-open'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable hermes-dashboard
sudo systemctl start hermes-dashboard
```

## Accessing Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / admin123 |
| Prometheus | http://localhost:9090 | None |
| Loki | http://localhost:3100 | None |
| Traefik | http://localhost:8080 | None |
| Portainer | https://localhost:9443 | admin / admin123 |
| Alloy | http://localhost:12345 | None (debug UI) |
| Hermes WebUI | http://localhost:8787 | Optional password |
| Hermes Dashboard | http://localhost:9119 | None |

> ⚠️ **Security Note:** The Hermes Dashboard (port 9119) has no built-in authentication. It is **highly recommended** to restrict access with a firewall.

### Recommended Firewall Rules

The Hermes Dashboard exposes API keys and configuration. Restrict access to trusted IPs only:

```bash
# Enable UFW if not already enabled
sudo ufw enable

# Allow your admin IP to access Hermes Dashboard (replace with your IP)
sudo ufw allow from 203.0.113.10/32 to any port 9119

# Allow your IP to access Grafana, Prometheus, Traefik UI
sudo ufw allow from 203.0.113.10/32 to any port 3000,8080,9090

# Deny direct access to Hermes Dashboard from the internet
sudo ufw deny 9119

# Check status
sudo ufw status
```

**Alternative: Use Tailscale VPN**
- If Tailscale is installed, connect via VPN instead of exposing ports
- Zero exposed ports = maximum security

**Dynamic IPs:** If your IP changes frequently, consider:
- Using Tailscale for access
- Using a VPN
- Implementing basic auth via Traefik middleware

## Architecture (v2.0 - Slimmed)

```
┌─────────────────────────────────────────────────────────┐
│                    Host System                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│              ┌─────────────────────┐                    │
│              │      Alloy          │ (Docker container) │
│              │  (privileged mode)  │                    │
│              └──────────┬──────────┘                    │
│                         │                               │
│    ┌────────────────────┼────────────────────┐         │
│    ▼                    ▼                    ▼         │
│ ┌──────────┐    ┌─────────────┐    ┌───────────┐       │
│ │ cAdvisor │    │  Prometheus │    │   Loki    │       │
│ │(embedded)│    │   (:9090)   │    │  (:3100)  │       │
│ └──────────┘    └─────────────┘    └───────────┘       │
│ ┌──────────┐         │                   │              │
│ │node_exp  │         └─────────┬─────────┘              │
│ │(embedded)│                   ▼                        │
│ └──────────┘            ┌─────────────┐                 │
│ ┌──────────┐            │  Grafana    │ (:3000)         │
│ │docker    │            └─────────────┘                 │
│ │logs      │                                         │
│ └──────────┘                                         │
└─────────────────────────────────────────────────────────┘
```

**What's New in v2.0:**
- **Alloy as container** - Replaces host-based Alloy (no systemd service needed)
- **Embedded exporters** - cAdvisor and node_exporter run inside Alloy
- **Fewer containers** - Removed standalone node-exporter and cAdvisor containers
- **Unified config** - Single config.alloy file manages all collection

## Troubleshooting

### Check container status
```bash
docker ps
```

### View logs
```bash
docker compose logs -f
```

### Restart a service
```bash
docker compose restart <service-name>
```

### Check Alloy logs
```bash
docker logs alloy
```

### Access Alloy debug UI
```bash
# Port 12345 provides the Alloy UI for debugging
curl http://localhost:12345
```

## Files

- `GOAL.md` - Deployment specification for Hermes
- `bootstrap.sh` - Initial VM setup script
- `docker-compose.mcp.yml` - MCP server configuration
- `stack/alloy/config.alloy` - Alloy configuration (embedded exporters)