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

### 2. Prometheus (Metrics Database)
- **Image**: prom/prometheus:v2.54.1
- **Port**: 9090
- **Purpose**: Time-series metrics database with PromQL queries
- **Config**: /stack/prometheus/prometheus.yml
- **Scrape Targets**: node-exporter, cadvisor, grafana, loki, traefik

### 3. Grafana (Visualization)
- **Image**: grafana/grafana:11.2.2
- **Port**: 3000
- **Purpose**: Dashboards and visualization
- **Data Sources**: Prometheus (port 9090), Loki (port 3100)
- **Credentials**: admin / admin123

### 4. Loki (Log Aggregation)
- **Image**: grafana/loki:3.2.0
- **Port**: 3100
- **Purpose**: Centralized log storage
- **Config**: /stack/loki/loki.yml

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

### 6. Node Exporter (Host Metrics)
- **Image**: prom/node-exporter:v1.8.2
- **Port**: 9100
- **Purpose**: Host CPU, memory, disk, network metrics

### 7. Portainer (Container Management GUI)
- **Image**: portainer/portainer-ce:2.21.4
- **Ports**: 9000 (HTTP), 9443 (HTTPS)
- **Purpose**: Web-based Docker container management

### 8. cAdvisor (Container Advisor)
- **Image**: gcr.io/cadvisor/cadvisor:latest
- **Port**: 8081
- **Purpose**: Per-container resource usage (CPU, memory, disk, network)

## Data Collection Flow
- Node Exporter + cAdvisor + Docker Daemon -> Prometheus <- Host Alloy Agent
- System Journal -> Loki <- Host Alloy Agent
- Prometheus + Loki -> Grafana (dashboards)

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

## Access Information

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://192.168.0.220:3000 | admin/admin123 |
| Prometheus | http://192.168.0.220:9090 | None |
| Loki | http://192.168.0.220:3100 | None |
| Traefik | http://192.168.0.220:8080 | None |
| Portainer | https://192.168.0.220:9443 | admin/admin123 |
| cAdvisor | http://192.168.0.220:8081 | None |

## Verified Working Metrics
- node_cpu_seconds_total
- node_memory_MemTotal_bytes
- container_cpu_usage_seconds_total (via cAdvisor)
- container_blkio_device_usage_total (via cAdvisor)
- Docker daemon metrics (builder, engine actions)
- System journal logs