# AIAMSBS - AI Agent Managed Services for SMBs

Self-hosting infrastructure platform using Hermes Agent.

## Prerequisites

- Ubuntu Server (24.04 recommended)
- User with **sudo privileges** (Hermes runs as this user)
- Internet connectivity for downloading images

## Deployment Process

### 1. Bootstrap the VM

Run this on the target VM as a user with sudo rights:

```bash
curl -fsSL https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/bootstrap.sh | bash
```

**What bootstrap.sh does:**
- Installs Docker + Docker Compose
- Installs Hermes Agent dependencies (Python, Node.js, ffmpeg, ripgrep)
- Clones Hermes Agent repo
- Sets up Hermes configuration

### 2. Configure API Key

After bootstrap completes, add your LLM provider API key:

```bash
# Create .env file with your API key
echo 'OPENROUTER_API_KEY=your-key-here' > ~/.hermes/.env
```

Or use any OpenAI-compatible provider (OpenAI, Anthropic, OpenRouter, etc.)

### 3. Deploy the Monitoring Stack

Start Hermes and give it the GOAL.md to deploy:

```bash
cd ~/.hermes/hermes-agent
source .venv/bin/activate
hermes chat -q "Deploy the monitoring stack from https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/GOAL.md"
```

Hermes will:
1. Clone the AIAMSBS repo
2. Create stack directory structure
3. Generate all config files (Traefik, Prometheus, Loki, Alloy)
4. Create docker-compose.yml
5. Deploy all containers

### 4. Install Hermes Web Dashboard (Optional)

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
| Hermes Dashboard | http://localhost:9119 | None |

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