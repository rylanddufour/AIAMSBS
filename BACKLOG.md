# AIAMSBS Backlog

## Planned Improvements

### High Priority

| # | Item | Description | Complexity |
|---|------|-------------|-------------|
| 1 | Pre-provisioned Grafana dashboards | Create default dashboards for host overview, container overview, Hermes logs, service health | Medium |
| 2 | Health check dashboard | Simple page showing if metrics/logs are flowing, last data received, service status | Low |
| 3 | Default alerting rules | Prometheus alert rules for no metrics, high CPU, disk usage, service down | Low |

### Medium Priority

| # | Item | Description | Complexity |
|---|------|-------------|-------------|
| 4 | Traefik landing page / routing | Nice URLs (grafana.yourdomain.com) instead of ports via Traefik | Medium |
| 5 | Log retention config | Configure Loki retention to prevent disk exhaustion | Low |
| 6 | Backup script | Export config files and dashboards for disaster recovery | Low |

### Low Priority

| # | Item | Description | Complexity |
|---|------|-------------|-------------|
| 7 | TLS/HTTPS for all services | Enable automatic HTTPS via Traefik | Medium |
| 8 | Service dependency health | Show if service depends on another that's down | Low |
| 9 | Metrics for Hermes itself | Monitor Hermes Agent with Prometheus | Low |

---

## Completed

- [x] Config-as-code deployment (v2.1)
- [x] Docker Compose stack definition
- [x] Alloy metrics + logs collection
- [x] Hermes WebUI in container
- [x] Hermes logs collection (~/.hermes/logs)
- [x] Remote access (0.0.0.0 binding)