# AIAMSBS Monitoring Stack Deployment Goal

## Objective
Deploy a complete monitoring and observability stack on a target VM using Docker Compose. The stack must collect host metrics, Docker container metrics, system logs, and provide visualization dashboards.

## Target Environment
- **VM**: localhost (current machine)
- **OS**: Ubuntu Server
- **User**: $USER (must have sudo and docker group membership)

## Prerequisites
- Docker installed and running
- Git available
- User has sudo privileges and belongs to docker group

## Components to Deploy

| Service | Image | Ports | Purpose |
|---------|-------|-------|---------|
| Traefik | traefik:v3.1 | 80, 443, 8080 | Reverse proxy with automatic HTTPS |
| Prometheus | prom/prometheus:v2.54.1 | 9090 | Time-series metrics database |
| Grafana | grafana/grafana:13.0.1 | 3000 | Dashboards and visualization |
| Loki | grafana/loki:3.2.0 | 3100 | Log aggregation |
| Alloy | grafana/alloy:latest | 12345 | Metrics + log collection agent |
| Portainer | portainer/portainer-ce:2.21.4 | 9000, 9443 | Container management |

## Data Flow
```
Alloy (container metrics + host metrics) -> Prometheus
Alloy (container logs + journal logs) -> Loki
Prometheus + Loki -> Grafana (dashboards)
```

## Deployment Steps

### 1. Docker Setup (if not already installed)
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
echo '{"metrics-addr":"0.0.0.0:9325","experimental":true}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
# Log out and back in for docker group membership
```

### 2. Deploy the Stack
```bash
git clone https://github.com/rylanddufour/AIAMSBS.git
cd AIAMSBS
docker compose up -d
```

### 3. Verify Deployment
Confirm these services are running:
```bash
docker compose ps
```

Expected containers: traefik, prometheus, grafana, loki, alloy, portainer

## Access

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / admin123 |
| Prometheus | http://localhost:9090 | (none) |
| Loki | http://localhost:3100 | (none) |
| Traefik | http://localhost:8080 | (none) |
| Portainer | https://localhost:9443 | admin / admin123 |
| Alloy Debug UI | http://localhost:12345 | (none) |

## Success Criteria

### Metrics Flowing to Prometheus
Run this query in Prometheus (http://localhost:9090):
- `container_cpu_usage_seconds_total` (container metrics)
- `node_cpu_seconds_total` (host metrics)

### Logs Flowing to Loki
In Grafana > Explore > Loki, query:
- `{job="docker"}` (container logs)
- `{job="systemd"}` (journal logs)

If queries return data, the deployment is successful.

## What Was Removed (v2.0)
The following are now handled by Alloy inside its container:
- ~~node-exporter~~ → replaced by `prometheus.exporter.unix`
- ~~cAdvisor~~ → replaced by `prometheus.exporter.cadvisor`
- ~~host-based Alloy (systemd)~~ → container version with full access