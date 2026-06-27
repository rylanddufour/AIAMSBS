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
|---|------|-------------|------------|
| 13 | Coordinator profile (deferred) | Build dedicated coordinator profile that routes alerts via inventory MCP to specialist profiles. **May become the default profile** (under review 2026-06-26 — see decision D1). Depends on inventory MCP (#14). | High |
| 14 | Inventory MCP stack | SQLite-backed device inventory exposed via FastMCP server. nmap-based discovery skill for seeding. Registered in the customer's default profile + IT_ADMIN (#20). Lives in `inventory-stack/` subdir with own compose file. | Medium |
| 15 | Ansible container (scope TBD) | Ansible container for bulk operations against managed devices. Scope TBD 2026-06-26 — may be needed by IT_ADMIN (#20) for fleet-wide changes; depends on whether IT_ADMIN ships with automation tools or relies on bash-tool-only. | Medium |
| ~~16~~ | ~~linux_admin Profile~~ | **RETIRED 2026-06-26.** Superseded by IT_ADMIN (#20). The 3 skills shipped in PR #1 were reverted in PR #2. | — |
| ~~17~~ | ~~network_admin Profile~~ | **RETIRED 2026-06-26.** Absorbed into IT_ADMIN (#20) as `skills/network-oem-*` modular skills. | — |
| ~~18~~ | ~~windows_admin Profile~~ | **RETIRED 2026-06-26.** Absorbed into IT_ADMIN (#20) as `skills/windows-server.md` + `skills/active-directory.md`. | — |
| ~~19~~ | ~~vsphere_admin Profile~~ | **RETIRED 2026-06-26.** Absorbed into IT_ADMIN (#20) as `skills/vsphere-admin.md`. | — |
| 20 | IT_ADMIN Profile | Single generalist datacenter IT admin agent. Replaces the planned 4 specialist profiles (16-19). SOUL.md + 19 skill files from OneDrive source: `obsidian_vaults/agent vault/AIAMSBS_Potential_Agent_Soul_skills/it-admin-agent-soul-skills/it-admin-agent/`. Sibling to `default`. Profile name = `IT_ADMIN` (open to rename when product name is decided). | Medium |

## Pending Decisions

| # | Item | Description |
|---|------|-------------|
| D1 | Decide default agent purpose | Is `default` a coordinator (per #13), generic, customer-initiated routing, or something else? Blocks #13 + #14 sequencing and IT_ADMIN's routing logic. |

## Known Bugs

| # | Item | Description | Complexity |
|---|------|-------------|-----------|
| 21 | `mcp_servers` config format (Hermes bug) | **[RESOLVED — PR #7](https://github.com/rylanddufour/AIAMSBS/pull/7), merged 2026-06-27.** `bootstrap.sh` `register_inventory_mcp` now writes DICT format and is also called for `it_admin`. Hermes CLI's `tools_config.py:1365` still expects dict (option (b) — patch Hermes to handle both formats — remains open as a separate item if desired). | — |

---

## Completed

- [x] BACKLOG #21 — `mcp_servers` config format (Hermes bug) [RESOLVED — PR #7](https://github.com/rylanddufour/AIAMSBS/pull/7), 2026-06-27
- [x] Config-as-code deployment (v2.1)
- [x] Docker Compose stack definition
- [x] Alloy metrics + logs collection
- [x] Hermes WebUI in container
- [x] Hermes logs collection (~/.hermes/logs)
- [x] Remote access (0.0.0.0 binding)