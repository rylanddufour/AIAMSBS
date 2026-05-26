# AIAMSBS Monitoring Stack Deployment Goal

## Objective
Deploy a complete monitoring and observability stack on a target VM (Ubuntu) using Docker Compose. The stack must collect host metrics, Docker container metrics, system logs, and provide visualization dashboards.

## Target Environment
- **VM**: 192.168.0.220 (ansible user)
- **OS**: Ubuntu Server
- **Network**: Internal LAN (192.168.0.x)

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
- **Scrape Targets**: node-exporter, cadvisor, grafana, loki, traefik
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

### 5. Alloy (Observability Agent - Host-based)
- **Installation**: Binary at /usr/local/bin/alloy (v1.16.1)
- **Running as**: systemd service
- **Config**: /etc/alloy/config.yml
- **Purpose**: Collects host metrics, Docker metrics, system journal logs
- **Data Sources**:
  - node-exporter (localhost:9100) - Host system metrics
  - cadvisor (localhost:8081) - Per-container metrics
  - Docker daemon (localhost:9325) - Docker engine metrics
  - journald - System logs
- **Outputs**:
  - Metrics -> Prometheus (http://localhost:9090)
  - Logs -> Loki (http://localhost:3100)
- **Restart Policy**: systemd service enabled (auto-start on boot)

### 6. Node Exporter (Host Metrics)
- **Image**: prom/node-exporter:v1.8.2
- **Port**: 9100
- **Purpose**: Host CPU, memory, disk, network metrics
- **Restart Policy**: unless-stopped (auto-start on boot)

### 7. Portainer (Container Management GUI)
- **Image**: portainer/portainer-ce:2.21.4
- **Ports**: 9000 (HTTP), 9443 (HTTPS)
- **Purpose**: Web-based Docker container management
- **Restart Policy**: unless-stopped (auto-start on boot)

### 8. cAdvisor (Container Advisor)
- **Image**: gcr.io/cadvisor/cadvisor:latest
- **Port**: 8081
- **Purpose**: Per-container resource usage (CPU, memory, disk, network)
- **Restart Policy**: unless-stopped (auto-start on boot)

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

- **URL**: http://192.168.0.220:9119
- **Note**: The --insecure flag allows binding to 0.0.0.0 (network access). Use with caution on untrusted networks.

## Data Collection Flow

```
Node Exporter + cAdvisor + Docker Daemon -> Prometheus <- Host Alloy Agent
System Journal -> Loki <- Host Alloy Agent
Prometheus + Loki -> Grafana (dashboards)
```

## Deployment Steps

### 1. Docker Setup
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ansible
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

### 3. Install Host Alloy Agent
```bash
curl -sSL https://github.com/grafana/alloy/releases/latest/download/alloy-linux-amd64.zip -o /tmp/alloy.zip
unzip -o /tmp/alloy.zip -d /tmp/
sudo mv /tmp/alloy-linux-amd64/alloy /usr/local/bin/
sudo chmod +x /usr/local/bin/alloy

# Create /etc/alloy/config.yml
# Create systemd service at /etc/systemd/system/alloy.service
sudo systemctl enable alloy && sudo systemctl start alloy
```

### 4. Install Hermes Web Dashboard
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
| Grafana | http://192.168.0.220:3000 | admin/admin123 |
| Prometheus | http://192.168.0.220:9090 | None |
| Loki | http://192.168.0.220:3100 | None |
| Traefik | http://192.168.0.220:8080 | None |
| Portainer | https://192.168.0.220:9443 | admin/admin123 |
| cAdvisor | http://192.168.0.220:8081 | None |
| Hermes Dashboard | http://192.168.0.220:9119 | None (API keys exposed) |

## Verified Working Metrics
- node_cpu_seconds_total
- node_memory_MemTotal_bytes
- container_cpu_usage_seconds_total (via cAdvisor)
- container_blkio_device_usage_total (via cAdvisor)
- Docker daemon metrics (builder, engine actions)
- System journal logs
## Backlog (Future Research)

### 1. cAdvisor Docker-Only Mode ✅ RESOLVED
- **Issue**: cAdvisor registers multiple container factories (systemd, containerd, Docker, Raw), creating duplicate metrics
- **Solution Applied**:
  1. Restarted cAdvisor with `--docker_only=true` flag to use only Docker factory
  2. Added `metric_relabel_configs` in Prometheus to drop metrics without `name` label:
     ```yaml
     - job_name: 'cAdvisor'
       static_configs:
         - targets: ['cadvisor:8080']
       metric_relabel_configs:
         - source_labels: [name]
           regex: '^$'
           action: drop
     ```
  3. Connected cAdvisor container to monitoring Docker network
- **Result**: 59 metrics → 8 metrics (only named Docker containers)

### 2. Container Name Label Enhancement
- **Issue**: cAdvisor provides container names via the `name` label (from Docker labels), but only for containers with docker-compose labels
- **Current State**: Works for docker-compose containers (shows names like "grafana", "prometheus", etc.)
- **Research**: Explore if there's a way to get container names for ALL containers without requiring docker-compose labels
- **Note**: Current setup uses `container_label_*` labels from docker-compose for name resolution

## Current Dashboard Configuration

### Container Metrics Queries
The Grafana dashboard uses these Prometheus queries for container metrics:

```promql
# Container CPU Usage
sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[5m])) * 100

# Container Memory Usage  
sum by (name) (container_memory_usage_bytes{name!=""}) / 1048576

# Container Network RX
sum by (name) (rate(container_network_receive_bytes_total{name!=""}[5m]))

# Container Network TX
sum by (name) (rate(container_network_transmit_bytes_total{name!=""}[5m]))
```

**Key Points:**
- Filter `{name!=""}` ensures we only get containers with names (filters out root cgroup)
- `sum by (name)` aggregates any duplicate metrics from multiple cAdvisor factories
- The `name` label comes from Docker container labels (via cAdvisor Docker factory)
