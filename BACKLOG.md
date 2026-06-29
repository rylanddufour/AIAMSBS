# AIAMSBS Backlog

## Planned Improvements

### High Priority

| # | Item | Description | Complexity |
|---|------|-------------|-------------|
| 1 | Pre-provisioned Grafana dashboards | Create default dashboards for host overview, container overview, Hermes logs, service health | Medium |
| 2 | Health check dashboard | **[RESOLVED — commit 7385d7b](https://github.com/rylanddufour/AIAMSBS/commit/7385d7b), 2026-06-28.** Added `config/grafana/provisioning/dashboards/health-check.json` (uid `aiamsbs-health`, 11 panels, 30s refresh) auto-provisioned by Grafana's existing dashboards.yml. Rows: overview stats (services up, prom series, loki 5m lines), per-service status (5 prom jobs + Loki sources), Service Detail table (color-coded up/scrape-age), Live Logs panel (docker + syslog). E2E-verified on VM 220. **Side note:** the other 3 dashboards (docker-logs, docker-monitoring, linux-host-overview) still use the old nested `{meta, dashboard}` JSON format and silently fail to load with "Dashboard title cannot be empty" — separate item to flatten those. | Low |
| 3 | Default alerting rules | Prometheus alert rules for no metrics, high CPU, disk usage, service down | Low |

### Medium Priority

| # | Item | Description | Complexity |
|---|------|-------------|------------|
| 10 | Add hostname label to Alloy metrics | Add `hostname` label to all scraped metrics so host selector works across multi-host deployments | Medium |
| 27 | AIAMSBS host logs in health dashboard (kanban: t_79dcbaae) | The current Live Logs panel (#30 in `health-check.json`) queries `{job=~"docker\|syslog"}` from Loki — but host-level logs (kernel, systemd services, auth, sudo, sshd failures) live in `job=systemd` (already being scraped by Alloy's `loki.source.journal` block in `config/alloy.yml`) and aren't visible to the customer. Surface security-relevant host logs in the health dashboard so a customer can see failed logins, sudo failures, kernel errors, service crashes alongside container logs.<br><br>**Scope:**<br>• Verify what's actually flowing into Loki today (`job=systemd` should already be there — confirm via Grafana Explore with `{job="systemd"}` query)<br>• Decide layout: (a) extend the existing Live Logs panel query to include `job=systemd`, OR (b) add a dedicated "Host Logs" panel below the existing one (probably better — different concerns, different filters)<br>• Filter for noise: most useful signals are `priority=err\|warning` or substring match for `sshd\|sudo\|auth\|kernel\|OOM`<br>• Consider a Loki query variable (`$log_filter`) so the user can toggle "All host logs" vs "Security events only" vs "Errors only"<br><br>**Related / in flight:**<br>• Item #2 (Health check dashboard) is RESOLVED — this is an additive enhancement on top of the live dashboard<br>• Alloy already has `loki.source.journal "systemd"` configured, so no alloy.yml changes likely needed — just dashboard query work<br><br>**Out of scope (park as separate items if surfaced):**<br>• Loki log retention config (#5) — separate item<br>• Long-term log volume / cost management — separate item<br>• Alerts on host events (failed logins → alert) — separate item | Medium |

### Multi-OEM Skills (New Capability Track)

| # | Item | Description | Complexity |
|---|------|-------------|------------|
| 12 | Multi-OEM skill library | Research, find, and build AIAMSBS skills for managing each OEM + configure Grafana stack integration (dashboards + alerts). OEMs in scope: <br><br>• **Windows Server** <br>• **Linux** <br>• **Cisco Catalyst** switches (CatOS + IOS) <br>• **Ubiquiti UniFi** wireless <br>• **Aruba Networks** (switches + access points) <br>• **VMware vSphere** <br><br>Each OEM integration includes: (1) Hermes skill for managing the platform, (2) Grafana dashboard for visibility, (3) alert rules | High |

### Release & Deployment (New Track)

| # | Item | Description | Complexity |
|---|------|-------------|------------|
| 24 | Default profile MCP auto-loading | **[RESOLVED — PR #9](https://github.com/rylanddufour/AIAMSBS/pull/9), merged 2026-06-27.** Root cause: `~/.hermes/profiles/default/config.yaml` is a **dead location** Hermes never reads — the default profile's config IS the global `~/.hermes/config.yaml`. Older `register_inventory_mcp` auto-detected multi-profile layout via `~/.hermes/profiles/` dir existence and wrote the default profile config to the dead location, silently ignored by Hermes. Fix: `register_inventory_mcp()` special-cases `profile == "default"` to always write to `~/.hermes/config.yaml` (lines ~1057-1162 of bootstrap.sh); idempotency preserved + one-shot migration strips stale `mcp_servers:` from the dead default subdir. Verified on VM 220: smoke test 14/14 PASS, default profile drives inventory via natural language. Discovered during E2E verification card `t_f4ff4c7b`. | — |
| 25 | Inventory `delete_device` tool + confirmation flow | **[RESOLVED — PR #10](https://github.com/rylanddufour/AIAMSBS/pull/10), merged 2026-06-27.** Added `delete_device(device_id, cascade_relationships=True)` to `inventory-stack/mcp/server.py` (returns `deleted_record` so callers can show user what was removed). Updated `profiles/it_admin/skills/non-destructive-operations.md` with mandatory "search → show → confirm → delete" flow. Smoke test 12/12 → 14/14 PASS. E2E verified on VM 220: IT_ADMIN and default profile both follow confirmation pattern (search, show row, ask "confirm?", wait for explicit yes, then delete). Hard-delete only — soft-delete / audit trail is a follow-up when a customer needs it. | — |
| 23 | AIAMSBS release + CI/CD pattern | Design and implement the full dev → test → release → customer-update pipeline so a new AIAMSBS version (bootstrap.sh changes, new skills, container image updates, inventory schema migrations) can be (a) tested end-to-end on a dev VM, (b) committed via PR, (c) tagged as a release, and (d) automatically delivered to installed customer devices **without clobbering customer state** (skills created by the agent, inventory data, dashboard customizations, API keys, locally-modified SOUL.md).<br><br>Must address:<br>• **Versioning scheme** — semver for AIAMSBS itself; how to version bundled skills, the inventory DB schema, and the Docker stack separately so we can update one without bumping others<br>• **Customer update channel** — opt-in `aiamsbs upgrade` script vs. scheduled cron that watches a GitHub release vs. pull-from-customer-initiated `git pull && bash bootstrap.sh`. Trade-off: automation vs. customer control vs. forward-compatibility for breaking changes<br>• **Pre-update safety** — backup customer-modified skills, inventory DB snapshot, current SOUL.md, dashboard JSON before applying upgrade; restore on failure<br>• **Schema migrations** — inventory DB schema version table + migration runner; forward-only with backout plan documented<br>• **Skill update policy** — bundled skills update overwrites customer edits (current `cp` behavior). Need: detect modified-since-install, prompt before overwrite, or skip-by-default with `--force-skill-update` flag<br>• **Test gate** — what passes before tag? E2E smoke (`smoke_test.sh`), inventory MCP integration test, dashboard creds still work, both profiles still respond. Run on snapshot VM before merge to main, not after<br>• **Roll-forward + roll-back** — release tags + GitHub Releases; rollback = `aiamsbs upgrade --to <previous-tag>`<br>• **Channel strategy** — `stable` (every release), `beta` (release candidates), `lts` (long-term support for small shops that don't want to chase upgrades)<br><br>**Related work in flight:**<br>• Phase-04 §4 already calls out the current dangerous clobber paths (`install_*_profile_soul`, `generate_dashboard_credentials`, `configure_hermes_api`)<br>• BACKLOG #22 already gates agent self-modification of skills — needs to be paired with a *customer-aware* upgrade path so bundled skill updates from us don't fight with agent's edits<br>• Upgrade discussion (2026-06-27 Telegram) — three options sketched: marker-file idempotency + opt-in force flag (recommended), separate `aiamsbs upgrade` subcommand, smart skill diff. Decision pending Ryland.<br><br>**Out of scope for #23** (park them as follow-ups if #23 surfaces them):<br>• Telemetry / usage analytics from customer installs<br>• Customer-facing update UI (web dashboard)<br>• Air-gapped delivery (offline install package) | High |

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
|---|------|-------------|------------|
| 7 | TLS/HTTPS for all services | Enable automatic HTTPS via nginx+certbot | Medium |
| 8 | Service dependency health | Show if service depends on another that's down | Low |
| 9 | Metrics for Hermes itself | Monitor Hermes Agent with Prometheus | Low |
| 26 | Blackbox HTTP/TCP probes for service health | **[RESOLVED — pending commit on wt/clean-install-e2e-20260627, 2026-06-28.** Added `prom/blackbox-exporter:latest` service in `docker-compose.yml` (network_mode: host, port 9115) with `config/blackbox.yml` defining three modules: `http_2xx` (readiness + MCP roots), `http_2xx_login` (accepts 2xx+3xx for Hermes Dashboard `/login` 302 redirect), and `tcp_connect` (Promtail syslog :514). Prometheus scrape jobs (`blackbox`, `blackbox_login`, `blackbox_tcp`, `blackbox_exporter` self-metrics) added to `config/prometheus.yml`. Probes hit `localhost` from inside the container so the host-side services are reachable. Verified E2E on VM 220 — see commit for live `probe_success` values per endpoint. | Low |

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
- [x] BACKLOG #2 — Health check dashboard [RESOLVED — commit 7385d7b](https://github.com/rylanddufour/AIAMSBS/commit/7385d7b), 2026-06-28
- [x] BACKLOG #25 — Inventory `delete_device` tool + confirmation flow [RESOLVED — PR #10](https://github.com/rylanddufour/AIAMSBS/pull/10), 2026-06-27
- [x] BACKLOG #24 — Default profile MCP auto-loading [RESOLVED — PR #9](https://github.com/rylanddufour/AIAMSBS/pull/9), 2026-06-27
- [x] BACKLOG #22 — Skill safety gates (agent self-modification hardening) [RESOLVED — PR #8](https://github.com/rylanddufour/AIAMSBS/pull/8), 2026-06-27. `bootstrap.sh` `configure_skill_safety()` sets `skills.write_approval: true` (skill writes staged to `/skills pending` for review) and `skills.guard_agent_created: true` (agent-created skills scanned for exfiltration/persistence/destructive patterns). Closes the gap that `~/.hermes/profiles/*/skills/*.md` is not in `file_tools._SENSITIVE_PATH_PREFIXES` — out of the box the agent could edit its own skills.
- [x] BACKLOG #21 — `mcp_servers` config format (Hermes bug) [RESOLVED — PR #7](https://github.com/rylanddufour/AIAMSBS/pull/7), 2026-06-27
- [x] Config-as-code deployment (v2.1)
- [x] Docker Compose stack definition
- [x] Alloy metrics + logs collection
- [x] Hermes WebUI in container
- [x] Hermes logs collection (~/.hermes/logs)
- [x] Remote access (0.0.0.0 binding)