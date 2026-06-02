# AIAMSBS Monitoring Stack Deployment Goal

## Objective
Deploy a complete monitoring and observability stack on a target VM (Ubuntu) using Docker Compose. The stack must collect host metrics, Docker container metrics, system logs, and provide visualization dashboards.

## Target Environment
- **VM**: localhost (current user with sudo rights)
- **OS**: Ubuntu Server
- **User**: $USER (must have sudo privileges)

## Stack Components

### 1. Traefik (Reverse Proxy)
- **Image**: traefik:v3.1
- **Ports**: 80 (HTTP), 443 (HTTPS), 8080 (dashboard)
- **Purpose**: Reverse proxy with automatic HTTPS via Let's Encrypt and service discovery
- **Config**: /stack/traefik/traefik.yml
- **Restart Policy**: unless-stopped (auto-start on boot)

### 2. Prometheus (Metrics Database)
- **Image**: prom/prometheus:v2.54.1
- **Port**: 9090
- **Purpose**: Time-series metrics database with PromQL queries
- **Config**: /stack/prometheus/prometheus.yml
- **Scrape Targets**: alloy, grafana, loki, traefik
- **Restart Policy**: unless-stopped (auto-start on boot)

### 3. Grafana (Visualization)
- **Image**: grafana/grafana:13.0.1
- **Port**: 3000
- **Purpose**: Dashboards and visualization (includes AI Assistant in 13+)
- **Data Sources**: Prometheus (port 9090), Loki (port 3100)
- **Credentials**: admin / admin123
- **Restart Policy**: unless-stopped (auto-start on boot)

### 4. Loki (Log Aggregation)
- **Image**: grafana/loki:3.2.0
- **Port**: 3100
- **Purpose**: Centralized log storage
- **Config**: /stack/loki/loki.yml
- **Restart Policy**: unless-stopped (auto-start on boot)

### 5. Alloy (Observability Agent - Container)
- **Image**: grafana/alloy:latest
- **Port**: 12345 (debug UI)
- **Purpose**: Unified metrics and log collection (replaces node-exporter, cAdvisor, and host-based Alloy)
- **Running as**: Docker container (privileged mode)
- **Config**: /stack/alloy/config.alloy
|- **Data Collection**:
  - **Embedded cAdvisor** - Container metrics (CPU, memory, disk, network)
  - **Embedded node_exporter** - Host system metrics (CPU, memory, disk, network, filesystems)
  - **loki.source.docker** - Docker container stdout/stderr logs
  - **loki.source.journal** - Systemd journal logs
  - **loki.source.file** - Host file-based logs (Hermes agent logs)
- **Outputs**:
  - Metrics -> Prometheus via remote_write (http://prometheus:9090)
  - Logs -> Loki (http://loki:3100)
- **Volume Mounts**: Docker socket, host rootfs, /sys, /var/lib/docker, journal
- **Restart Policy**: unless-stopped (auto-start on boot)

### 6. Portainer (Container Management GUI)
- **Image**: portainer/portainer-ce:2.21.4
- **Ports**: 9000 (HTTP), 9443 (HTTPS)
- **Purpose**: Web-based Docker container management
- **Restart Policy**: unless-stopped (auto-start on boot)

## What Was Slimmed Down (v2.0)
The following components were **removed** in favor of Alloy's embedded exporters:

| Removed Component | Reason | Replaced By |
|-------------------|--------|-------------|
| node-exporter container | Redundant | Alloy's `prometheus.exporter.unix` |
| cAdvisor container | Redundant | Alloy's `prometheus.exporter.cadvisor` |
| Host-based Alloy (systemd) | No longer needed | Alloy container with full config |

**Benefits:**
- Single container handles all metrics collection
- No host package installation required
- Unified configuration in docker-compose
- Easier to update (just update the container image)

## Hermes Agent Web Dashboard

### Installation
```bash
# Install Node.js 20 (required for web UI)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Build the web UI
cd ~/.hermes/hermes-agent/web
npm install
npm run build
```

### Startup on Boot (systemd service)
```bash
sudo tee /etc/systemd/system/hermes-dashboard.service > /dev/null << 'EOF'
[Unit]
Description=Hermes Agent Web Dashboard
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ansible
WorkingDirectory=/home/ansible/.hermes/hermes-agent
ExecStart=/bin/bash -c 'source .venv/bin/activate && exec hermes dashboard --port 9119 --host 0.0.0.0 --insecure --skip-build --no-open'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable hermes-dashboard.service
sudo systemctl start hermes-dashboard.service
```

## Hermes WebUI (Web Interface for Hermes Agent)

### Overview
Hermes WebUI provides a full-featured web interface for Hermes Agent with:
- Chat interface with streaming responses
- Session management (create, search, pin, archive, projects)
- Workspace file browser with inline preview
- Task/cron job management GUI
- Skills management
- Memory editor (MEMORY.md, USER.md)
- Profile switching
- Multiple themes (dark/light with various skins)

### Architecture
```
┌─────────────────────┐         ┌─────────────────────┐
│  hermes-webui       │         │   Host (192.168.x) │
│  (Docker container) │ ◀──────▶│   Hermes Agent     │
│  :8787             │         │   Gateway :8642    │
└─────────────────────┘         └─────────────────────┘
```

### Installation (Single Container)
```bash
# Run WebUI container - connects to Hermes on host via ~/.hermes mount
docker run -d \
  --name hermes-webui \
  -v ~/.hermes:/home/hermeswebui/.hermes \
  -v ~/workspace:/workspace \
  -p 127.0.0.1:8787:8787 \
  ghcr.io/nesquena/hermes-webui:latest
```

### Configuration Options
| Variable | Default | Description |
|---|---|---|
| `HERMES_WEBUI_PASSWORD` | (none) | Enable password auth |
| `HERMES_WEBUI_HOST` | 127.0.0.1 | Bind address |
| `HERMES_WEBUI_PORT` | 8787 | Port |
| `HERMES_WEBUI_STATE_DIR` | ~/.hermes/webui | Session storage |

### Access
- **URL**: http://localhost:8787
- **Localhost only**: Binds to 127.0.0.1 by default
- **Remote access**: Set `HERMES_WEBUI_HOST=0.0.0.0` + `HERMES_WEBUI_PASSWORD`

### Key Differences: WebUI vs Dashboard

| Feature | Hermes Dashboard | Hermes WebUI |
|---|---|---|
| **Source** | Built-in (`hermes dashboard`) | External (nesquena/hermes-webui) |
| **Port** | 9119 | 8787 |
| **Features** | Basic metrics view | Full chat, sessions, files, cron, skills |
| **Sessions** | No | Yes (persistent across reloads) |
| **Authentication** | None (--insecure only) | Optional password + passkeys |
| **Framework** | React (bundled) | Vanilla JS (no build step) |

**Recommendation**: Use Hermes WebUI for full agent interaction, or Hermes Dashboard for quick metrics viewing.

## Access Information

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin/admin123 |
| Prometheus | http://localhost:9090 | None |
| Loki | http://localhost:3100 | None |
| Traefik | http://localhost:8080 | None |
| Portainer | https://localhost:9443 | admin/admin123 |
| Alloy | http://localhost:12345 | None (debug UI) |
| Hermes WebUI | http://localhost:8787 | Optional password |
| Hermes Dashboard | http://localhost:9119 | None (API keys exposed) |

```
Alloy Container (embedded cAdvisor + node_exporter) -> Prometheus
Alloy Container (container logs + journal logs) -> Loki
Prometheus + Loki -> Grafana (dashboards)
```

## Deployment Steps

### 1. Docker Setup
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
echo '{"metrics-addr":"0.0.0.0:9325","experimental":true}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

### 2. Stack Deployment
```bash
git clone https://github.com/rylanddufour/AIAMSBS.git
cd AIAMSBS
docker compose up -d
# All containers have restart: unless-stopped - auto-start on boot enabled
```

### 3. Install Hermes Web Dashboard (Optional)
```bash
# Install Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Build web UI
cd ~/.hermes/hermes-agent/web
npm install
npm run build

# Create systemd service (see Hermes Agent Web Dashboard section above)
```

## Access Information

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin/admin123 |
| Prometheus | http://localhost:9090 | None |
| Loki | http://localhost:3100 | None |
| Traefik | http://localhost:8080 | None |
| Portainer | https://localhost:9443 | admin/admin123 |
| Alloy | http://localhost:12345 | None (debug UI) |
| Hermes Dashboard | http://localhost:9119 | None (API keys exposed) |

## Verified Working Metrics

### Host Metrics (via prometheus.exporter.unix)
- node_cpu_seconds_total
- node_memory_MemTotal_bytes
- node_disk_*
- node_network_*
- node_filesystem_*

### Container Metrics (via prometheus.exporter.cadvisor)
- container_cpu_usage_seconds_total
- container_memory_usage_bytes
- container_blkio_device_usage_total
- container_network_receive_bytes_total
- container_network_transmit_bytes_total

### Logs
- Docker container stdout/stderr (via loki.source.docker)
- Systemd journal (via loki.source.journal)

## Alloy Configuration Details

The Alloy container uses these components:

```alloy
// Container metrics (replaces cAdvisor)
prometheus.exporter.cadvisor "containers" {
  docker_host = "unix:///var/run/docker.sock"
  storage_duration = "5m"
}

// Host metrics (replaces node-exporter)
prometheus.exporter.unix "host" {
  rootfs_path = "/"
}

// Scrape both and send to Prometheus
prometheus.scrape "cadvisor" { ... }
prometheus.scrape "node" { ... }
prometheus.remote_write "default" { ... }

// Container logs
loki.source.docker "containers" { ... }

// Systemd journal logs
loki.source.journal "systemd" { ... }

loki.write "default" { ... }
```

## Previous Research Notes

### Why Alloy as Container?
1. **No host installation** - Everything in docker-compose
2. **Unified config** - Single config file for all collectors
3. **Easier updates** - Just update container image tag
4. **Privileged mode required** - For full host access (same as running as host service)

### Volume Mounts Required
- `/var/run/docker.sock` - Docker API access
- `/` (rootfs) - Host filesystem for node_exporter
- `/sys` - System info (cgroups)
- `/var/lib/docker/` - Docker metadata
- `/var/log/journal` - Systemd logs
- `/dev/disk/` - Disk I/O metrics