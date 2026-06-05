# AIAMSBS Monitoring Stack Deployment

## Objective
Deploy a complete monitoring and observability stack on a target VM using Docker Compose and configuration files stored in this repository.

## Target Environment
- **VM**: localhost (current machine)
- **OS**: Ubuntu Server
- **User**: $USER (must have sudo and docker group membership)

## Prerequisites
- Docker installed and running (handled by bootstrap)
- Git available
- User has sudo privileges and belongs to docker group

## Configuration Files

This deployment uses explicit configuration files to ensure consistent, reproducible deployments:

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Stack definition (services, ports, volumes) |
| `config/alloy.yml` | Metrics and log collection configuration |
| `config/prometheus.yml` | Prometheus scrape targets |
| `config/loki.yml` | Log aggregation configuration |
| `config/traefik.yml` | Reverse proxy configuration |
| `config/grafana/provisioning/datasources/datasources.yml` | Grafana data sources |
| `.env.example` | Environment variables template |

## Components Deployed

| Service | Image | Ports | Purpose |
|---------|-------|-------|---------|
| Traefik | traefik:v3.1 | 80, 443, 8080 | Reverse proxy with automatic HTTPS |
| Prometheus | prom/prometheus:v2.54.1 | 9090 | Time-series metrics database |
| Grafana | grafana/grafana:13.0.1 | 3000 | Dashboards and visualization |
| Loki | grafana/loki:3.2.0 | 3100 | Log aggregation |
| Alloy | grafana/alloy:latest | 12345 | Metrics + log collection agent |
| Portainer | portainer/portainer-ce:2.21.4 | 9000, 9443 | Container management |
| Hermes WebUI | ghcr.io/nesquena/hermes-webui:latest | 8787 | Web interface for Hermes Agent |

## Data Flow
```
Alloy (container metrics + host metrics) -> Prometheus
Alloy (container logs + journal logs) -> Loki
Prometheus + Loki -> Grafana (dashboards)
```

## Deployment Steps

### 1. Copy Environment Template
```bash
cp .env.example .env
# Edit .env with your desired passwords
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

Expected containers: traefik, prometheus, grafana, loki, alloy, portainer, hermes-webui

## Access

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / (from .env) |
| Prometheus | http://localhost:9090 | (none) |
| Loki | http://localhost:3100 | (none) |
| Traefik | http://localhost:8080 | (none) |
| Portainer | https://localhost:9443 | admin / (from .env) |
| Hermes WebUI | http://localhost:8787 | (none) |
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

## Pre-Provisioned Dashboards

The following dashboards are automatically loaded when Grafana starts:

| Dashboard | Purpose |
|-----------|---------|
| Network Device Logs | Syslog from firewalls, switches, routers (job=syslog) |
| Docker Monitoring | Container CPU, memory, network, disk metrics |
| Docker Logs | Container stdout/stderr logs |
| Linux Host Overview | Host-level CPU, memory, disk, network |

These are defined in:
- `config/grafana/provisioning/dashboards/dashboards.yml` (provisioning config)
- `dashboards/*.json` (dashboard definitions)

## Version
- Configuration files in this commit are deterministic
- To pin a specific deployment, use the commit hash