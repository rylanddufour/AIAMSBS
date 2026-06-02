# AIAMSBS Architecture Reference

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

## Volume Mounts Required

Alloy requires these mounts for full observability:

| Mount | Purpose |
|-------|---------|
| `/var/run/docker.sock` | Docker API access (cAdvisor) |
| `/` (rootfs) | Host filesystem (node_exporter) |
| `/sys` | System info (cgroups) |
| `/var/lib/docker/` | Docker metadata |
| `/var/log/journal` | Systemd logs |
| `/dev/disk/` | Disk I/O metrics |

## Why Alloy as Container?

1. **No host installation** - Everything in docker-compose
2. **Unified config** - Single config file for all collectors
3. **Easier updates** - Just update container image tag
4. **Privileged mode required** - For full host access (same as running as host service)

## Verified Working Metrics

### Host Metrics (via prometheus.exporter.unix)
- `node_cpu_seconds_total`
- `node_memory_MemTotal_bytes`
- `node_disk_*`
- `node_network_*`
- `node_filesystem_*`

### Container Metrics (via prometheus.exporter.cadvisor)
- `container_cpu_usage_seconds_total`
- `container_memory_usage_bytes`
- `container_blkio_device_usage_total`
- `container_network_receive_bytes_total`
- `container_network_transmit_bytes_total`

### Logs
- Docker container stdout/stderr (via loki.source.docker)
- Systemd journal (via loki.source.journal)

## Hermes WebUI / Dashboard (Separate Installation)

### Hermes WebUI (Web Interface)
```bash
# Run WebUI container - remote access, restarts on boot, persists sessions
docker run -d \
  --name hermes-webui \
  --restart unless-stopped \
  -v ~/.hermes:/home/hermeswebui/.hermes \
  -p 0.0.0.0:8787:8787 \
  -e HERMES_WEBUI_HOST=0.0.0.0 \
  ghcr.io/nesquena/hermes-webui:latest
```

### Hermes Dashboard (Built-in)
```bash
# Install Node.js 20 (required for web UI)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Build the web UI
cd ~/.hermes/hermes-agent/web
npm install
npm run build

# Run with systemd service (see full config in main docs)
```

### Quick Comparison

| Feature | Hermes Dashboard | Hermes WebUI |
|---------|-----------------|--------------|
| **Source** | Built-in (`hermes dashboard`) | External container |
| **Port** | 9119 | 8787 |
| **Features** | Basic metrics view | Full chat, sessions, files |
| **Sessions** | No | Yes |
| **Auth** | None (--insecure only) | Optional password |