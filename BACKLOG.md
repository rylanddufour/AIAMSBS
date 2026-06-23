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
| 10 | Add hostname label to Alloy metrics | Add `hostname` label to all scraped metrics so host selector works across multi-host deployments | Medium |

### Multi-OEM Skills (New Capability Track)

| # | Item | Description | Complexity |
|---|------|-------------|-------------|
| 12 | Multi-OEM skill library | Research, find, and build AIAMSBS skills for managing each OEM + configure Grafana stack integration (dashboards + alerts). OEMs in scope: <br><br>• **Windows Server** <br>• **Linux** <br>• **Cisco Catalyst** switches (CatOS + IOS) <br>• **Ubiquiti UniFi** wireless <br>• **Aruba Networks** (switches + access points) <br>• **VMware vSphere** <br><br>Each OEM integration includes: (1) Hermes skill for managing the platform, (2) Grafana dashboard for visibility, (3) alert rules | High |

### Metrics Fix (Pre-req for dashboards)

| # | Item | Description | Complexity |
|---|------|-------------|-------------|
| A | Fix container metrics | Ensure `container_cpu_usage_seconds_total` and other container_* metrics flow to Prometheus | — |
| B | Add hostname label | Add `hostname` label to all metrics for multi-host dropdown selector | — |
| 5 | Log retention config | Configure Loki retention to prevent disk exhaustion | Low |
| 6 | Backup script | Export config files and dashboards for disaster recovery | Low |
| 6a | Hermes WebUI scheduled jobs | Enable gateway in container so cron jobs work in WebUI | Medium |

### Testing

| # | Item | Description | Complexity |
|---|------|-------------|-------------|
| 11 | Test syslog with real network device | Verify Promtail receives syslog on port 514 and Loki stores/logs appear in Grafana dashboard | Low |


### Low Priority

| # | Item | Description | Complexity |
|---|------|-------------|-------------|
| 7 | TLS/HTTPS for all services | Enable automatic HTTPS via nginx+certbot | Medium |
| 8 | Service dependency health | Show if service depends on another that's down | Low |
| 9 | Metrics for Hermes itself | Monitor Hermes Agent with Prometheus | Low |

---

## Inventory & Multi-Agent (New Capability Track)

| # | Item | Description | Complexity |
|---|------|-------------|-------------|
| 13 | Coordinator profile (deferred) | Build dedicated coordinator profile that routes alerts via inventory MCP to specialist profiles. **Default profile is the interim coordinator** until this exists. Depends on inventory MCP (#14) + specialist profiles (future). | High |
| 14 | Inventory MCP stack | SQLite-backed device inventory exposed via FastMCP server. nmap-based discovery skill for seeding. All AIAMSBS-installed profiles (default, aiamsbs_dev, aiamsbs_research, future) registered as clients. Lives in `inventory-stack/` subdir with own compose file. See `research/multi-oem-skill-research-2026-06-22.md` for design context. | Medium |

---

## Completed

- [x] Config-as-code deployment (v2.1)
- [x] Docker Compose stack definition
- [x] Alloy metrics + logs collection
- [x] Hermes WebUI in container
- [x] Hermes logs collection (~/.hermes/logs)
- [x] Remote access (0.0.0.0 binding)