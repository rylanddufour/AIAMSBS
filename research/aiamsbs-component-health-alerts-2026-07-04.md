# Grafana Alert Use Cases for AIAMSBS

Research date: 2026-07-04
Author: Hermes Agent (subagent, on behalf of Ryland)
Audience: AIAMSBS customer (solo IT admin at a 1–10 person shop)
Target stack: Grafana 13.0.1 + Prometheus 2.54.1 + Loki 3.2.0 + Alloy (latest) + blackbox_exporter (latest) on a single Linux VM. Notification delivery via Grafana Unified Alerting → Telegram (default) and email (fallback).
Informs: BACKLOG #3 ("Default alerting rules", Low), and the v0.2/v1.0 alerting work that follows.
Companion research:
- [`multi-oem-skill-research-2026-06-22.md`](./multi-oem-skill-research-2026-06-22.md) — multi-vendor monitoring patterns
- [`multi-oem-path-forward-2026-06-22.md`](./multi-oem-path-forward-2026-06-22.md) — strategic ship sequence

---

## 1. Executive summary

**The core alert philosophy for AIAMSBS is "earn the admin's 30 minutes."** A solo IT admin at a 10-person shop has roughly 30 minutes of focused ops time per day. Every alert that fires consumes a slice of that budget. An alerting system that pages five times a day for things the admin cannot act on will be muted within a week — and a muted alerting system is worse than no alerting system, because it destroys trust in the *next* critical alert. The single design constraint that overrides every other is **signal-to-noise**: an alert that is not actionable within 5 minutes by the person who gets paged should not page.

The seven alerts that must ship in the first "Default alerting rules" PR (BACKLOG #3) are:

1. **Core service down** — any of Prometheus / Loki / Grafana / Alloy / blackbox_exporter reporting `up == 0` for > 2m. **Critical.** We have lost observability or the customer has lost their dashboards.
2. **Blackbox probe failure** — `probe_success == 0` for > 2m on any of the four module types (`blackbox`, `blackbox_mcp`, `blackbox_login`, `blackbox_tcp`). **Critical.** The customer's HTTP/TCP endpoints are not responding.
3. **Host disk > 90%** on `/`, `/var`, or `/var/lib/docker` with a **predict_linear** warning at "will fill in < 7 days". **Critical at 90% (data loss imminent), warning at 80% or 7-day fill projection.** ext4 reserves 5% for root, so 90% is the actual "no space left" point.
4. **Container crash loop** — a single container has restarted ≥ 3 times in 15m. **Critical.** Implies the workload is broken and is consuming host resources.
5. **Loki/Prometheus crash loop in their own logs** — `panic`, `fatal`, or `OOMKilled` substring in `job="docker"` for the loki / prometheus / grafana containers. **Critical.** Self-observability has failed; we must escalate.
6. **Backup cron failure** — the `AIAMSBS Dashboard Backup` Hermes cron job (registered in `~/.hermes/cron/jobs.json`, fired by the `hermes-gateway` systemd service per `profiles/it_admin/skills/dashboard-backup.md`) has `last_status: error` for > 24h, **or** no new `dashboard-backup-*.tar.gz` in `~/backups/` for > 26h. **Warning.** This is the customer's only safety net for the dashboard state.
7. **Hermes-gateway systemd service not active** — `systemctl is-active hermes-gateway.service` returns non-active, OR the `hermes-gateway.service` systemd unit has been `failed` for > 5m. **Critical.** Without the gateway, no Hermes cron fires — and that includes the backup in #6, plus any future scheduled work.

**Explicitly do NOT alert on (at least in v1.0):** per-container transient CPU spikes < 5m, individual container restarts ≤ 2 in 24h, in-node memory pressure that resolves itself, network blips on a single interface, log-noise from healthy services (kernel timestamp skew, journal rotation messages), and `scrape failures` shorter than the `for:` duration. These generate the majority of false-positive noise in a stock Prometheus+Grafana install; if we ship them by default, the admin mutes the channel and the real alerts get ignored. We will revisit *some* of these as info-level annotations on the health dashboard (visible but not paged) once we have evidence they correlate with real problems.

---

## 2. Audience + signal-to-noise philosophy

### The small-shop reality

The customer for AIAMSBS is a **solo IT generalist at a 1–10 person shop**. The same person who:
- Sets up new laptops when someone joins
- Renews the O365 tenant
- Unplugs a switch when "the Wi-Fi is down"
- Files the quarterly taxes if it's a 1-person shop

…also has to keep AIAMSBS running. Per `BACKLOG.md` item #3 and the broader product framing in `GOAL.md` and `README.md`, this stack has to be installable in 20 minutes and stay out of the way. Alerting is the single most sensitive feature for this audience: too quiet, and they miss a real outage; too loud, and they quit the tool.

Per `profiles/it_admin/skills/monitoring-observability.md`, the "Alert Quality Rules" are already documented at the skill level — **actionable, routed to the right owner, low-noise, severity-based, suppressed during maintenance, linked to runbooks**. This document turns those rules into specific rule recommendations for the AIAMSBS stack.

### High-signal vs. low-signal examples

| Signal | Example | Why |
|---|---|---|
| **High** | `probe_success{instance="http://localhost:3000/api/health"} == 0 for 2m` | Specific, actionable (Grafana itself is down), the only fix is `docker compose restart grafana`. The admin can verify in one command. |
| **High** | `node_filesystem_avail_bytes{mountpoint="/var/lib/docker"} < 10%` for 10m | Actionable in 5 min: `docker system prune -a`, or expand the disk. Real risk of cascade. |
| **Low** | `rate(node_network_receive_bytes_total[1m]) > 100MB/s` for 30s | Network spikes during backups, O365 sync, Windows updates. No action the admin can take; not predictive. |
| **Low** | `container_start_time_seconds` advanced 1 time in 24h | One restart ≠ a problem. Crash-loops are problems (3+ in 15m). |
| **Low** | `rate(node_vmstat_pgpgin[5m]) > 1000` | Page cache pressure; not actionable in a small shop, the kernel handles it. |

### What "actionable" means for a 1–10 person shop

An alert is **actionable** if and only if the on-call IT admin can take a concrete step within 5 minutes that meaningfully changes the outcome. The step must be one of:
- Run a single `docker compose restart <service>` or `systemctl restart <unit>`
- Free disk space (delete a log, prune Docker, expand a volume)
- Acknowledge a known issue and silence the alert (with a documented reason)
- Open a vendor support ticket with a specific log line in hand

If the only response to an alert is "look at the dashboard, see if it gets worse, come back later," the alert should be **info-level** and only visible on the dashboard — not a page.

### Suppression philosophy

Three suppression rules should apply to every alert by default:

1. **Duration suppression:** every alert must have a `for:` clause of at least `2m` (8× the 15s evaluation interval). One-minute blips are not problems. This is the most important rule and is the single biggest difference between "noisy Prometheus" and "useful Prometheus."
2. **Dependency suppression:** if Prometheus itself is down, do not also fire "Grafana is down" and "Loki is down" — they are likely all symptoms of the same root cause. Use Grafana's `inhibit_rules` or a single composite alert that captures "the observability stack as a whole is down."
3. **Maintenance windows:** the customer must be able to mark a 1-hour window during a planned restart and have alerts silenced for that period. Grafana's "silence" feature handles this; we should document it in `profiles/it_admin/skills/` rather than ship our own.

### When to alert vs. when to log-only

| Event | Response |
|---|---|
| Service has been down 2m | **Page** (Telegram interrupt) |
| Service has been down 30s | **Log to Loki** (visible in dashboard, no notification) |
| Container restarted 1 time in 24h | **Log to Loki** (annotation on health dashboard) |
| Container restarted 3 times in 15m | **Page** (Telegram interrupt) |
| Disk at 85% but fill rate predicts 30+ days | **Log to Loki** |
| Disk at 85% with predict_linear projecting fill in 5 days | **Page** (Telegram) |
| One failed SSH login | **Log to Loki** |
| 50 failed SSH logins in 5m from the same IP | **Page** (Telegram) — likely active attack |
| Hermes backup cron last_status = error | **Batch into a single daily digest message at 09:00** (Telegram batch) |
| Hermes-gateway systemd service failed | **Page** (Telegram interrupt) — this kills the backup and any future cron |

The pattern: **page on the thing that hurts RIGHT NOW; batch-digest the thing that hurts by EOD; log-only the thing that doesn't hurt yet.**

---

## 3. Alert use cases

The following categories cover every signal the AIAMSBS stack can produce. Each entry is the **specific rule we should ship**, not a generic template. PromQL is evaluated against Prometheus; LogQL is evaluated against Loki. Where a category has no high-signal alert, the section says so explicitly.

> **Note on `job` labels:** The deployed `health-check.json` dashboard (commit 7385d7b) queries `job="integrations/unix"` for the unix_exporter metrics, which is the standard Grafana Cloud Alloy label. The `config/alloy.yml` in the repo does not currently set that label name — this is a known drift between the dashboard (verified working on VM 220 per `BACKLOG.md` #2) and the alloy config. The PromQL below uses the `job="integrations/unix"` form to match what the dashboard actually queries; the alloy config should be reconciled in a follow-up so it matches. This is captured in Open Questions.

### 3.1 Service availability (Prometheus `up{}` on every scrape job)

The fundamental "is it alive" check. Evaluated as a composite per `profiles/it_admin/skills/monitoring-observability.md` ("low-noise, severity-based"). All of these use the standard Prometheus `up` metric (value 1 = last scrape succeeded, 0 = failed).

| # | Name | Severity | Source | Query | Threshold rationale | Runbook action |
|---|---|---|---|---|---|---|
| 3.1.1 | Prometheus self-scrape down | critical | Prometheus | `up{job="prometheus"} == 0` for `2m` | 2m suppression prevents a single slow scrape (≥ 15s scrape_timeout) from paging. The `for:` clause means 8 missed evaluation cycles in a row. | Run `curl http://localhost:9090/-/ready`; if unresponsive, `docker compose restart prometheus`. Then check `docker logs prometheus --tail 100` for `OOMKilled` / `panic` / disk-full. |
| 3.1.2 | Alloy self-scrape down | critical | Prometheus | `up{job="alloy"} == 0` for `2m` | Same as 3.1.1. Alloy is the collector; if it's down we lose metrics and log shipping. | `docker compose restart alloy`. Check `docker logs alloy` — common cause is the `docker.sock` mount gone (host reboot + docker restarted before alloy). |
| 3.1.3 | Grafana self-scrape down | critical | Prometheus | `up{job="grafana"} == 0` for `2m` | Customer loses dashboards. The first symptom a user notices. | `docker compose restart grafana`. Check `docker logs grafana --tail 100` for provisioning errors (the AIAMSBS BACKLOG #1 incident was empty-title dashboards causing provisioning loops). |
| 3.1.4 | Loki self-scrape down | critical | Prometheus | `up{job="loki"} == 0` for `2m` | We lose log search. All log-based alerts below become blind. | `docker compose restart loki`. Check disk space on `/loki` — back when compactor was missing, disk filled and Loki refused to start (BACKLOG #5). |
| 3.1.5 | blackbox_exporter self-scrape down | critical | Prometheus | `up{job="blackbox_exporter"} == 0` for `2m` | We lose the HTTP/TCP probes (3.2 below). The customer-facing service-health signals go dark. | `docker compose restart blackbox_exporter`. Verify `9115` is listening (`ss -tlnp | grep 9115`). |
| 3.1.6 | All observability down at once | critical | Prometheus | `count(up{job=~"prometheus|alloy|grafana|loki|blackbox_exporter"} == 1) == 0` for `2m` | The composite: if literally no scrape job is up, the host itself is the problem (out of memory, kernel panic, host reboot). This single alert replaces 5 individual paged alerts when the root cause is the host. | SSH to host. `uptime`, `dmesg -T | tail -50`, `free -h`. Most likely cause: host reboot, OOM, or the `monitoring` Docker network was destroyed. |

### 3.2 Blackbox probe health (HTTP + TCP service availability)

`config/blackbox.yml` defines 4 modules: `http_2xx`, `http_2xx_login` (accepts 2xx+3xx for Hermes `/login` 302), `http_2xx_or_404` (MCP servers), `tcp_connect`. Scrape jobs in `config/prometheus.yml:36-118` are `blackbox`, `blackbox_mcp`, `blackbox_login`, `blackbox_tcp`. The `probe_success` metric is `1` when the probe matched `valid_status_codes`, `0` otherwise.

| # | Name | Severity | Source | Query | Threshold rationale | Runbook action |
|---|---|---|---|---|---|---|
| 3.2.1 | Grafana UI down | critical | Prometheus | `probe_success{job="blackbox", instance="http://localhost:3000/api/health"} == 0` for `2m` | `api/health` is the Grafana 13 readiness endpoint, 200 OK when healthy. 2m filter prevents `/health` slow responses from paging (it can stall for 5s under load). | Open `http://<host>:3000` in a browser. If 502/503, `docker compose restart grafana`. If 504, host network is the problem. |
| 3.2.2 | Loki API down | critical | Prometheus | `probe_success{job="blackbox", instance="http://localhost:3100/ready"} == 0` for `2m` | `/ready` is the Loki readiness endpoint. Same 2m floor as 3.2.1. | `curl http://localhost:3100/ready` to confirm. `docker compose restart loki`. If `/ready` returns 503, check Loki logs for `compactor` errors (BACKLOG #5 had compactor deadlock on disk-full). |
| 3.2.3 | Prometheus API down | critical | Prometheus | `probe_success{job="blackbox", instance="http://localhost:9090/-/ready"} == 0` for `2m` | `/-/ready` is the Prometheus readiness endpoint. | `docker compose restart prometheus`. If it OOMs on restart, the TSDB has grown past the host's RAM — increase `--storage.tsdb.retention.time` (default 15d) down, or expand the host disk. |
| 3.2.4 | Alloy API down | critical | Prometheus | `probe_success{job="blackbox", instance="http://localhost:12345/-/ready"} == 0` for `2m` | Same as 3.1.2, but via the blackbox module rather than the `up{}` self-scrape. Belt-and-braces; the `up{}` check already catches this, but the blackbox probe adds the HTTP-path coverage (e.g. Alloy process alive but HTTP handler broken). | Same as 3.1.2. |
| 3.2.5 | Hermes Dashboard down | critical | Prometheus | `probe_success{job="blackbox_login", instance="http://localhost:9119/login"} == 0` for `2m` | `/login` redirects 302 → `/` per `config/blackbox.yml:23-34`. If the redirect stops, the dashboard service is wedged. | `sudo systemctl status hermes-dashboard.service` — should be `active`. If `failed`, `journalctl -u hermes-dashboard.service -n 100`. Common cause: missing venv or broken auth provider (BACKLOG item referenced the basic-auth bug). |
| 3.2.6 | Inventory MCP down | critical | Prometheus | `probe_success{job="blackbox_mcp", instance="http://localhost:8001/"} == 0` for `2m` | Inventory MCP returns 404 at `/` per `config/blackbox.yml:36-46` but is otherwise healthy. 5xx still fails. | `docker compose -f inventory-stack/docker-compose.yml restart inventory-mcp`. Check `docker logs inventory-mcp` for SQLite errors. |
| 3.2.7 | Grafana MCP down | critical | Prometheus | `probe_success{job="blackbox_mcp", instance="http://localhost:8000/"} == 0` for `2m` | Same as 3.2.6. | `docker compose -f docker-compose.mcp.yml restart grafana-mcp`. Common cause: `GRAFANA_SERVICE_ACCOUNT_TOKEN` expired or the underlying Grafana (which `grafana-mcp` proxies) is down — check 3.2.1 first. |
| 3.2.8 | Promtail syslog receiver down | critical | Prometheus | `probe_success{job="blackbox_tcp", instance="localhost:514"} == 0` for `2m` | Network devices' syslog (OPNsense, switches, APs — verified working per `BACKLOG.md` #11) goes to Promtail on TCP/514. If this is down, the customer stops receiving device logs and won't notice until they look. | `docker compose restart promtail`. `ss -tlnp | grep 514` to confirm bind. If a network device recently changed config, verify it still points at the AIAMSBS host. |

### 3.3 Host health (Alloy `prometheus.exporter.unix`)

Verified working metrics in `ARCHITECTURE.md:54-68`: `node_cpu_seconds_total`, `node_memory_MemTotal_bytes`, `node_disk_*`, `node_network_*`, `node_filesystem_*`. The current `config/alloy.yml` configures `prometheus.exporter.unix "self"` (the **Grafana Alloy unix_exporter**, not the legacy `node_exporter`); the live health-check dashboard queries these with `job="integrations/unix"`.

| # | Name | Severity | Source | Query | Threshold rationale | Runbook action |
|---|---|---|---|---|---|---|
| 3.3.1 | Host CPU sustained high | warning | Prometheus | `avg by (instance) (100 - (rate(node_cpu_seconds_total{mode="idle", job="integrations/unix"}[5m])) * 100) > 90` for `15m` | 15m floor because CPU spikes < 5m are normal (kernel builds, log compactions, PromQL backfills). 5m rate + 15m `for:` = 20m of sustained high CPU before page, which is the right balance for a small shop. 90% threshold = 9 of 10 cores saturated on a 10-core box; lower than 90% and a 4-core box would page on `apt full-upgrade`. | `top -c` to see which process. If `prometheus`: a heavy query is running. If `alloy`: a scrape target is hanging. If `dockerd`: a container is misbehaving — combine with 3.4.1. |
| 3.3.2 | Host load average high | warning | Prometheus | `node_load5{job="integrations/unix"} > count without (cpu, mode) (node_cpu_seconds_total{mode="idle", job="integrations/unix"}) * 1.5` for `15m` | Load > 1.5× core count sustained 15m = runnable queue is backed up. Don't alert on `load1` (too noisy on bursty workloads); 5m average is the right grain. | `uptime` to see the 1/5/15 values, then `ps -eo pid,pcpu,comm --sort=-pcpu \| head` to find the culprit. |
| 3.3.3 | Host memory pressure | warning | Prometheus | `(1 - (node_memory_MemAvailable_bytes{job="integrations/unix"} / node_memory_MemTotal_bytes{job="integrations/unix"})) * 100 > 90` for `10m` | `MemAvailable` (not `MemFree`) accounts for reclaimable cache; 90% of total means only 10% of RAM is genuinely available for new allocations. 10m floor because reclaim takes a few minutes under load. | `free -h`. If `available` is low but `buff/cache` is high, the kernel is hoarding — usually fine. If `available` is genuinely low and a container is the source, that container's OOMKill is the next thing you'll see (3.4.2). |
| 3.3.4 | Host memory critical (OOM imminent) | critical | Prometheus | `(1 - (node_memory_MemAvailable_bytes{job="integrations/unix"} / node_memory_MemTotal_bytes{job="integrations/unix"})) * 100 > 97` for `2m` | At 97% the kernel will start OOMKilling processes on the next allocation. 2m floor because reclaim can take 30s and we don't want to page on transient pressure. | `journalctl -k --since "5 min ago" | grep -i "out of memory"`. If a container was OOMKilled, see 3.4.2. If host process was killed, the choice is to kill the runaway or expand the VM's RAM. |
| 3.3.5 | Filesystem critical | critical | Prometheus | `node_filesystem_avail_bytes{mountpoint=~"/\|/var", job="integrations/unix"} / node_filesystem_size_bytes{mountpoint=~"/\|/var", job="integrations/unix"} * 100 < 10` for `5m` | ext4 reserves 5% for root, so 10% remaining = the filesystem is functionally full for non-root processes. We exclude `/proc`, `/sys`, `/dev` via the `mountpoint=~"/\|/var"` selector. 5m floor prevents a brief write burst from paging. | `df -h \| grep -E "^/dev"`. If `/var/lib/docker` is the offender, `docker system prune -a` (caution: removes unused images) or `docker volume prune`. If `/` is full, find the largest dirs: `du -sh /var/log/* 2>/dev/null \| sort -h \| tail`. |
| 3.3.6 | Filesystem warning (fill prediction) | warning | Prometheus | `predict_linear(node_filesystem_avail_bytes{mountpoint="/var/lib/docker", job="integrations/unix"}[6h], 7 * 24 * 3600) < 0` for `30m` | `predict_linear` extrapolates the 6h growth rate to project when the filesystem hits zero. The 7-day horizon matches a typical weekly ops review cadence. 30m `for:` ensures we're not fooled by a 10-minute write spike. | If the projection says "fills in 5 days," you have 5 days to act — `du -sh /var/lib/docker/volumes` to find the offender, then `docker volume rm` or expand the volume. |
| 3.3.7 | Disk INODE pressure | warning | Prometheus | `node_filesystem_files_free{mountpoint="/var/lib/docker", job="integrations/unix"} / node_filesystem_files{mountpoint="/var/lib/docker", job="integrations/unix"} * 100 < 10` for `10m` | Small files (millions of `*.tsdb` chunks, journal entries) can exhaust inodes before bytes. 10% free inodes = the customer will start hitting "No space left on device" on file creates even with disk space available. | `df -i /var/lib/docker`. Common cause: a runaway log writer or Loki chunk spam. |
| 3.3.8 | Filesystem read-only | critical | Prometheus | `node_filesystem_readonly{mountpoint=~"/\|/var", job="integrations/unix"} == 1` for `1m` | Filesystem went read-only = critical data integrity risk. The kernel does this on EXT4 errors. 1m floor — even a brief read-only state is a critical condition. | `dmesg -T \| grep -i "ext4.*error"`. The host filesystem is failing; safest path is snapshot the VM, then `umount`/`fsck`. **Do not reboot until you understand the error** — `fsck` on a mounted filesystem makes it worse. |

### 3.4 Container health (Prometheus cAdvisor / Alloy cadvisor)

`ARCHITECTURE.md:62-67` documents the verified working cAdvisor metrics. **However, the current `config/alloy.yml` does not actually configure `prometheus.exporter.cadvisor`** — only `prometheus.exporter.unix "self"` is present. The BACKLOG #A "Fix container metrics" and the `BACKLOG.md` comment about `container_cpu_usage_seconds_total` suggest this was the plan but the live alloy config drifted. **The container-health alerts below assume BACKLOG #A is resolved first** (cAdvisor exporter added to alloy.yml). See Open Questions.

| # | Name | Severity | Source | Query | Threshold rationale | Runbook action |
|---|---|---|---|---|---|---|
| 3.4.1 | Container crash loop | critical | Prometheus | `increase(container_start_time_seconds{job="integrations/cadvisor"}[15m]) > 3` for `2m` | `container_start_time_seconds` is a Unix timestamp that ticks forward on every container start. Counting its increases over 15m is the standard cAdvisor crash-loop detector. 3 restarts / 15m = a process that cannot stay up. | `docker ps --filter "status=restarting"`. Then `docker logs <container> --tail 100` to see why. Common: missing env var (BACKLOG #A!), bad image, OOMKilled (3.4.2). |
| 3.4.2 | Container OOMKilled | critical | Prometheus | `rate(container_oom_events_total{job="integrations/cadvisor"}[5m]) > 0` for `1m` | An OOMKill is always a real problem (the kernel decided to kill this process). 1m `for:` because the rate will naturally go to zero after the kill. | `docker inspect <container> --format '{{.State.OOMKilled}}'`. Either raise the memory limit in `docker-compose.yml` (the `memory:` field on the service) or fix the actual leak. |
| 3.4.3 | Container CPU throttled | warning | Prometheus | `rate(container_cpu_cfs_throttled_seconds_total{job="integrations/cadvisor"}[5m]) / rate(container_cpu_cfs_throttled_periods_total{job="integrations/cadvisor"}[5m]) > 0.5` for `15m` | A container is being throttled > 50% of the time = its CPU limit is too low for its workload. This is the standard "your container is CPU-starved" signal. Warning, not critical, because throttling doesn't crash anything. | Check the container's `cpus:` limit in `docker-compose.yml`. Either raise it (if the host has spare capacity per 3.3.1) or fix the workload to be more efficient. |
| 3.4.4 | AIAMSBS container itself down (any of the 6) | critical | Prometheus | `count by (name) (kube_pod_container_status_running{job="integrations/cadvisor"} == 0) > 0` for `2m` | **AIAMSBS ships the AIAMSBS stack itself** — if any of `prometheus`, `loki`, `grafana`, `alloy`, `blackbox_exporter`, `promtail` are not running, the customer is missing data. | Per-container: `docker compose restart <service>`. If multiple at once, see 3.1.6 (host is the root cause). |

### 3.5 Log-based alerts (Loki)

Alloy ships two log sources per `config/alloy.yml:21-44`:
- `loki.source.docker "containers"` → `job="docker"`, `source="aiamsbs_host"`
- `loki.source.journal "systemd"` → `job="systemd"`, `source="aiamsbs_host"`

Both flow into Loki with 90-day retention (`config/loki.yml:36`). Promtail adds `job="network_syslog"`, `source="network_device"` (`config/promtail.yml:14-21`). LogQL is the Loki query language; rate expressions use `rate(...)` over a window. **All log-based alerts require the Loki pipeline to be reliably ingesting** — BACKLOG #5 (90-day retention) is resolved, but BACKLOG #27 (host logs in dashboard) suggests the customer doesn't yet have visibility into host logs from the health dashboard. **Don't ship the alerts below until the dashboard surfaces the data, otherwise the customer gets paged with no easy way to verify.**

| # | Name | Severity | Source | Query | Threshold rationale | Runbook action |
|---|---|---|---|---|---|---|
| 3.5.1 | Docker daemon error spike | warning | Loki | `sum(rate({job="docker", source="aiamsbs_host"} \|~ "(?i)error\|panic\|fatal" [5m])) > 5` for `5m` | > 5 errors/sec for 5m = the host's Docker daemon is in trouble. 5m floor prevents individual container crashes (handled by 3.4.1) from double-paging. | Open the health dashboard Live Logs panel (`config/grafana/provisioning/dashboards/health-check.json` panel #30) and filter `job=docker`. Identify the offender by `compose_service` label. |
| 3.5.2 | SSH auth failure surge | warning | Loki | `sum(rate({job="systemd", source="aiamsbs_host"} \|~ "sshd.*(Failed password\|Invalid user\|Connection closed by)" [5m])) > 0.5` for `10m` | > 30 failed logins in 5m = either a misconfigured client (e.g. wrong SSH key on a new laptop) or an active attack. 10m floor because the customer will typo a password 3 times in a row and we don't want to page for that. | `journalctl -u sshd --since "30 min ago" | grep "Failed" | awk '{print $11}' | sort | uniq -c \| sort -rn \| head` to find the source IPs. If a single IP dominates, `ufw deny from <ip>`. |
| 3.5.3 | sudo auth failure | warning | Loki | `sum(rate({job="systemd", source="aiamsbs_host"} \|~ "sudo.*(authentication failure\|incorrect password attempts)" [5m])) > 0.1` for `5m` | A sudo failure is either the admin fat-fingering their own password (low signal) or someone else trying (high signal). 5m floor / 0.1 rate catches the latter without paging on the former. | `journalctl _COMM=sudo --since "30 min ago"`. If the user is a known admin, it's likely a typo. If an unexpected user, treat as potential compromise per `profiles/it_admin/skills/security-baseline.md`. |
| 3.5.4 | Kernel OOM message | critical | Loki | `sum(rate({job="systemd", source="aiamsbs_host", _TRANSPORT="kernel"} \|~ "Out of memory: Killed process" [5m])) > 0` for `1m` | Kernel OOMKill is always a critical event. The system is choosing which process to die. 1m floor — we want to know immediately. | `journalctl -k --since "5 min ago" \| grep "Out of memory"`. Combine with 3.4.2 (the killed process is usually a container). |
| 3.5.5 | Loki process dying in its own logs | critical | Loki | `sum(rate({job="docker", compose_service="loki"} \|~ "(?i)panic\|fatal\|level=fatal" [5m])) > 0` for `2m` | Self-observability: if Loki is dying, our ability to detect anything is dying with it. 2m floor because a single log line is not a death. | `docker logs loki --tail 200`. Common: compactor deadlock (BACKLOG #5), OOMKilled, schema migration failure. |
| 3.5.6 | Prometheus process dying in its own logs | critical | Loki | `sum(rate({job="docker", compose_service="prometheus"} \|~ "(?i)panic\|fatal\|level=fatal" [5m])) > 0` for `2m` | Same as 3.5.5 for Prometheus. | `docker logs prometheus --tail 200`. Common: WAL corruption (rare on a single-host setup), OOMKilled, bad config reload. |
| 3.5.7 | Grafana provisioning errors | warning | Loki | `sum(rate({job="docker", compose_service="grafana"} \|~ "Failed to load dashboard\|Dashboard title cannot be empty\|provisioning" [10m])) > 0.1` for `10m` | This is the BACKLOG #1 incident: empty-title dashboards in the provisioning folder caused 3 errors per 10s reload cycle. 0.1/sec for 10m = 60 errors in 10m, which is what a stuck provisioning loop produces. | `docker logs grafana 2>&1 \| grep -i provision \| tail -50`. Check `config/grafana/provisioning/dashboards/*.json` for empty `title` fields. |
| 3.5.8 | Hermes-gateway errors | warning | Loki | `sum(rate({job="systemd", source="aiamsbs_host", _SYSTEMD_UNIT="hermes-gateway.service"} \|~ "(?i)error\|traceback\|exception" [5m])) > 0.5` for `10m` | Per `profiles/it_admin/skills/dashboard-backup.md`, the gateway daemon ticks all Hermes cron jobs. Gateway errors = no scheduled work gets done. | `sudo journalctl -u hermes-gateway.service --since "30 min ago"`. Combined with 3.5.9 if the service has actually failed. |
| 3.5.9 | Hermes-gateway process restarting | critical | Loki | `sum(rate({job="systemd", source="aiamsbs_host", _SYSTEMD_UNIT="hermes-gateway.service"} \|~ "Started hermes-gateway.service\|Stopped hermes-gateway.service" [15m])) > 2` for `5m` | 2+ start/stop cycles in 15m = the service is crashlooping. This silently breaks every Hermes cron. | `sudo systemctl status hermes-gateway.service` (should be `active (running)` per the BACKLOG #33 resolution). If `failed`, `sudo systemctl restart hermes-gateway.service` and watch `journalctl -u hermes-gateway.service -f`. |
| 3.5.10 | Network device severity spike | info | Loki | `sum by (host) (rate({job="network_syslog", source="network_device", severity=~"error\|critical"} [5m])) > 0.5` for `15m` | Error-level syslog from network gear means a real event (link flap, BGP session down, fan failure). Info level — the customer should look at the Network Device Logs dashboard (`dashboards/network-syslog.json`) but doesn't need to be paged at 3 AM for a single flap. | Open the network-syslog dashboard, filter by `severity=error` or `severity=critical`, drill into the device. |

### 3.6 AIAMSBS-specific (the things only AIAMSBS has)

These are the alert rules that exist *because* AIAMSBS has a specific workflow. They reference AIAMSBS-specific files and paths.

| # | Name | Severity | Source | Query | Threshold rationale | Runbook action |
|---|---|---|---|---|---|---|
| 3.6.1 | Dashboard backup cron failure | warning | Prometheus (via `textfile` or `node_textfile`) | Custom exporter needed — see Open Questions. Until then, fallback to a **Loki-based** check: `count_over_time({job="systemd", source="aiamsbs_host", _SYSTEMD_UNIT="hermes-gateway.service"} \|~ "AIAMSBS Dashboard Backup" [25h]) < 1` | The `AIAMSBS Dashboard Backup` Hermes cron (per `profiles/it_admin/skills/dashboard-backup.md`) fires daily at 01:00. If the gateway hasn't logged that prompt text in 25h, the cron hasn't run. 25h = 1h slack over the 24h schedule. | `hermes cron list` and look for `last_status` + `last_error`. If `state: scheduled` but `last_status: error`, the script failed — read the error. If `enabled: true` and never ran, the gateway is the problem (3.5.9). |
| 3.6.2 | No fresh backup archive | warning | Prometheus (via `textfile`) or node cron | Same Loki-based fallback as 3.6.1: inspect `~/.hermes/scripts/backup-dashboards.sh` exit codes. A proper version uses a textfile collector: `cat > /var/lib/node_exporter/textfile_collector/aiamsbs_backup.prom << EOF` then the cron writes `aiamsbs_backup_last_success_timestamp_seconds < (time() - 26*3600)`. | 26h = 24h schedule + 2h slack for clock skew / late cron fire. | If no archive in `~/backups/`, run `~/.hermes/scripts/backup-dashboards.sh` manually to surface the error. |
| 3.6.3 | Hermes-gateway systemd service down | critical | Prometheus (node exporter systemd collector) or Loki | `node_systemd_unit_state{name="hermes-gateway.service", state="active"} == 0` for `5m`. Loki fallback: absence of `Started hermes-gateway.service` log lines in 5m + presence of `Stopped` lines. | Per BACKLOG #33 (RESOLVED), the gateway is installed as a system-level systemd service at `/etc/systemd/system/hermes-gateway.service`. If it goes down, the dashboard backup, daily backlog reminder, and any future scheduled work stop firing silently. 5m floor — systemd restarts on its own within seconds for most failures. | `sudo systemctl status hermes-gateway.service`. If `inactive (dead)`, `sudo systemctl start hermes-gateway.service`. If `failed`, `journalctl -u hermes-gateway.service -n 100`. |
| 3.6.4 | Grafana provisioning errors | warning | Loki | (See 3.5.7) | This is the AIAMSBS-specific class of failure that BACKLOG #1 was. Repeated empty-title provisioning errors mean a customer is editing a dashboard JSON file and breaking it. | Per 3.5.7. |
| 3.6.5 | Hermes dashboard basic auth fail | warning | Loki | `sum(rate({job="systemd", source="aiamsbs_host", _SYSTEMD_UNIT="hermes-dashboard.service"} \|~ "(?i)401\|Unauthorized\|auth provider" [5m])) > 0.5` for `10m` | A burst of 401s on the dashboard = either a customer fat-fingering creds (low) or someone trying to break in (high). 5m rate floor + 10m `for:` catches sustained bursts only. | `journalctl -u hermes-dashboard.service --since "30 min ago" | grep -i "unauthorized"`. If from a known admin IP, ignore. If from an unknown IP, check the broader picture (3.5.2 SSH failures from same IP?). |
| 3.6.6 | Cert expiry (Grafana / Hermes Dashboard) | warning | Prometheus (blackbox) | Requires a cert-expiry check. The cleanest path is `probe_ssl_earliest_cert_expiry - time()` in the blackbox module for HTTPS endpoints. **Current stack serves HTTP only on 3000/9119** — see Open Questions. | Standard public-website guidance is 14-day warning, 7-day critical, but the AIAMSBS customer is exposing these to a private VPN/Tailscale, not the public internet. Start with 30-day warning, 14-day critical. | If cert is expiring, renew per the certbot/manual procedure. Out of scope for BACKLOG #3 to design the cert-renewal workflow. |

### 3.7 Network / inventory (only if inventory-mcp + nmap-discovery are in use)

Per `inventory-stack/docker-compose.yml`, the inventory stack has two services: `inventory-mcp` (always on) and `nmap-discovery` (gated by `profiles: ["discovery"]`, so only runs when the customer explicitly enables it). **These alerts are NOT in the default "Default alerting rules" PR** — they should land in v0.2 once BACKLOG #14 is fully resolved and the customer has a populated inventory. The core alerts (sections 3.1–3.6) must work without inventory being installed.

| # | Name | Severity | Source | Query | Threshold rationale | Runbook action |
|---|---|---|---|---|---|---|
| 3.7.1 | Inventory MCP down | critical | Prometheus | (See 3.2.6 — blackbox probe) | If inventory-mcp is down, the IT_ADMIN profile loses its primary lookup path. The customer falls back to "SSH and look up by hand" which is the workflow we're trying to eliminate. | Per 3.2.6. |
| 3.7.2 | Inventory DB size warning | info | Prometheus (custom) | A custom exporter that runs `wc -c /var/lib/docker/volumes/inventory-data/_data/inventory.db` and exposes `aiamsbs_inventory_db_bytes`. Warn at > 100MB. | Inventory DB is SQLite; > 100MB means tens of thousands of devices (rare in a 1–10 person shop, common after `nmap-discovery` runs a wide scan). | `du -sh /var/lib/docker/volumes/inventory-data/`. If unexpectedly large, check for a runaway discovery job. |
| 3.7.3 | Discovered device count sudden change | info | Prometheus (custom) | `aiamsbs_inventory_devices_count` change > 20% in 24h | Sudden drop = data loss (e.g., someone ran `delete_device` without cascade). Sudden spike = nmap-discovery found a new subnet (could be legitimate or could be a rogue device). Info level — neither is an emergency. | `inventory-mcp list_devices` to see what changed. If a subnet was added, that's expected after a network change. If devices disappeared, check for accidental deletion. |
| 3.7.4 | nmap-discovery last-run stale | warning | Prometheus (custom) | `time() - aiamsbs_nmap_discovery_last_run_timestamp_seconds > 7 * 86400` | If the customer has enabled `nmap-discovery`, the periodic scan is supposed to keep inventory fresh. > 7 days stale = either the scan is broken or the customer's network changed. | `docker compose -f inventory-stack/docker-compose.yml --profile discovery run nmap-discovery`. Check logs. |
| 3.7.5 | Network device syslog flow stopped | warning | Loki | `count_over_time({job="network_syslog", source="network_device", host="<known-host>"} [1h]) == 0` for `3h` | If a known device stops sending syslog for 3h, either the device is down, the network path is broken, or the device's syslog config was rolled back. | `nc -vz <known-device> 514` (UDP/TCP syslog port). If reachable, the device config is the issue. If not, network path. |
| 3.7.6 | Network device link state change | info | Loki | `sum(rate({job="network_syslog", source="network_device"} \|~ "(?i)link (up\|down)\|interface.*(up\|down)\|line protocol" [5m])) > 0.1` for `5m` | Multiple interface state changes in 5m = a flapping link. Not a page (flapping is annoying but rarely an emergency for a 1–10 person shop), but visible on the dashboard. | Open the network-syslog dashboard, filter `severity=warning`, find the interface. The IT_ADMIN skill `network-troubleshooting` has the full diagnostic flow. |

### 3.8 MCP stack (grafana-mcp / inventory-mcp / kb-mcp / nmap-discovery)

The MCP servers are the agent's primary tool path. If they're down, the AIAMSBS value proposition collapses — the customer is left with a stock Grafana install. These alerts are in the default PR but the blackbox probes for them (3.2.6, 3.2.7, and the kb-mcp probe below) are the primary signal.

| # | Name | Severity | Source | Query | Threshold rationale | Runbook action |
|---|---|---|---|---|---|---|
| 3.8.1 | grafana-mcp down | critical | Prometheus | (See 3.2.7 — blackbox probe at `:8000/`) | The agent's path to "query Grafana" / "create alert rule" / "update dashboard" goes through grafana-mcp. | Per 3.2.7. |
| 3.8.2 | inventory-mcp down | critical | Prometheus | (See 3.2.6 — blackbox probe at `:8001/`) | The agent's path to "what device has this IP" goes through inventory-mcp. | Per 3.2.6. |
| 3.8.3 | kb-mcp down | warning | Prometheus (blackbox) | **NOTE:** Currently no blackbox probe for `kb-mcp` on port 8002 — see Open Questions. The probe needs to be added to `config/blackbox.yml` and `config/prometheus.yml`. Until then, the alert cannot fire. | kb-mcp is a query-time tool. If it's down, the agent's KB lookups fail but the platform runs fine. Warning, not critical — the customer doesn't lose observability. | `docker compose -f kb-stack/docker-compose.yml restart kb-mcp`. Check `docker logs kb-mcp` for SQLite errors. |
| 3.8.4 | nmap-discovery unresponsive | warning | Prometheus (custom) | The `nmap-discovery` container uses `network_mode: host` and doesn't publish a fixed port per `inventory-stack/docker-compose.yml:26-41`. Probe via systemd: `node_systemd_unit_state{name="nmap-discovery.service"} == 0`. | nmap-discovery is gated by `profiles: ["discovery"]` — it only runs when the customer enables it. If enabled and the unit is down, scheduled scans stop. Warning, not critical, because the agent has the `discover-devices` skill as a manual fallback. | `docker compose -f inventory-stack/docker-compose.yml --profile discovery restart nmap-discovery`. |

### 3.9 Categories with no high-signal alert

- **Per-container CPU > 80%**: too noisy. Every Windows update, every `apt full-upgrade`, every PromQL backfill. Use the host-level alert (3.3.1) instead — if one container is dragging the host, you'll catch it there.
- **Individual disk I/O wait > 30%**: noisy and not actionable in a small shop. The disk-fill alerts (3.3.5, 3.3.6) cover the actual failure mode.
- **Network receive/transmit bytes threshold**: not actionable. Network is bursty; setting a threshold above the burst rate is meaningless and below it pages constantly.
- **Container memory > 90% of limit**: noisy; the kernel handles it via the page cache. If it actually matters, the OOMKill (3.4.2) will fire.
- **Loki `ingestion_rate` spike**: not actionable. High ingest = the customer is generating more logs, not a problem. If the spike causes disk pressure, 3.3.5 catches it.
- **Grafana internal errors below 1/min**: not actionable. Grafana logs a lot; below 1/min is just background noise.
- **PromQL evaluation errors**: should be visible in the dashboard for debugging, but never a page. A bad query by the admin doesn't mean the system is broken.

---

## 4. Severity matrix (opinionated)

This is the contract between AIAMSBS and the customer's phone. **Every alert shipped must declare one of these three severities; the notification pipeline is configured once and never re-thought.**

| Severity | Channel | Cadence | When it fires | Examples in this doc |
|---|---|---|---|---|
| **critical** | Telegram (interrupt) + dashboard banner | Immediate, no batching | Customer needs to act now or data is at risk | 3.1.1–3.1.6, 3.2.1–3.2.8, 3.3.4, 3.3.5, 3.3.8, 3.4.1, 3.4.2, 3.4.4, 3.5.4, 3.5.5, 3.5.6, 3.5.9, 3.6.3, 3.8.1, 3.8.2 |
| **warning** | Telegram (batched, 09:00 daily digest) + dashboard panel | Once per day at 09:00 local, with the morning backlog reminder | Customer should look today but it's not on fire | 3.3.1, 3.3.2, 3.3.3, 3.3.6, 3.3.7, 3.4.3, 3.5.1, 3.5.2, 3.5.3, 3.5.7, 3.5.8, 3.6.1, 3.6.2, 3.6.5, 3.6.6, 3.7.4, 3.7.5, 3.8.3, 3.8.4 |
| **info** | Loki + dashboard annotation only. **No notification.** | Never | Customer should be able to find it if they go looking | 3.5.10, 3.7.2, 3.7.3, 3.7.6 |

**Rationale for the digest pattern:** A solo admin doesn't need a Telegram interrupt at 14:00 for a warning that won't change anything in the next 8 hours. A daily 09:00 digest bundled with the existing `Daily Backlog Reminder` Hermes cron (already in `~/.hermes/cron/jobs.json`, `schedule: "0 9 * * *"`) means the admin reads **one** message per morning that contains: pending kanban cards + accumulated warnings. This is the lowest-friction delivery pattern that respects the 30-minute rule.

**Implementation note for the digest:** Grafana 13.x supports "group by" + "group wait" / "group interval" / "repeat interval" timing on alert rules. The recommended pattern is:
- All `warning` rules: `group_wait: 30m, group_interval: 1h, repeat_interval: 24h` (a single batched message per day, but with 30m suppression at the start so transients don't fire).
- All `critical` rules: `group_wait: 0s, group_interval: 5m, repeat_interval: 4h` (immediate first page, repeat every 4h if not acked).

For details, see [Grafana Unified Alerting — group timing](https://grafana.com/docs/grafana/latest/alerting/fundamentals/notifications/#grouping).

---

## 5. Notification channel recommendations

The single most important constraint: **for a 1–10 person shop, every channel adds a maintenance burden (an API key, a webhook URL, a service to monitor).** AIAMSBS's job is to make the default configuration work and let the customer override later.

### 5.1 Default: Telegram (already wired)

The Hermes cron jobs in `~/.hermes/cron/jobs.json` use `deliver: "telegram:8704545814"` as the existing pattern. The **Grafana native Telegram contact point** is the cleanest path: it POSTs directly to Telegram's Bot API using a `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` configured in the contact point. No additional infrastructure; no separate webhook server. **This should be the default contact point for both critical and warning severities.**

Bootstrap will need to:
1. Ask for `TELEGRAM_BOT_TOKEN` (or create one via BotFather and prompt the customer to paste it) and `TELEGRAM_CHAT_ID`.
2. Write a Grafana contact-point provisioning file under `config/grafana/provisioning/contact-points/contact-points.yml`.
3. Write a notification policy file under `config/grafana/provisioning/notification-policies/policies.yml` that maps `severity=critical` → Telegram immediately, `severity=warning` → Telegram with the digest timing from §4.

For docs, see the [Grafana Telegram contact point reference](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/#telegram).

### 5.2 Fallback: Email

Email is the only universally-available channel. The Grafana **email contact point** is built in (uses SMTP). The `it_admin` profile's `change-management.md` skill already covers the "notify stakeholders" flow; alerts-to-email is the same path. Configure as the **secondary** contact point for `critical` severity, so that if Telegram is down (rate-limited, customer lost their phone), the email still arrives. No additional contact-point for `warning` — the digest goes to Telegram only.

### 5.3 Self-hosted alternative: ntfy.sh

`ntfy.sh` is a simple, self-hosted pub/sub notification service that can be deployed as a single Docker container. The customer's phone subscribes to a topic via the ntfy Android/iOS app, and Grafana POSTs a webhook. **Trade-off:** the customer must run ntfy.sh on a separate (always-on) host, or accept a hosted-ntfy dependency. Useful for shops that have an "everything on-prem" policy. Not a default; document as an option in `profiles/it_admin/skills/monitoring-observability.md` once we've validated the integration. **Recommend for v0.2, not BACKLOG #3.**

### 5.4 NOT recommended: PagerDuty / OpsGenie / VictorOps

**PagerDuty and OpsGenie are the wrong tool for a 1–10 person shop.** They are designed for 24/7 on-call rotations across multiple humans, with escalation policies, time-zone-aware schedules, and incident management workflows. A solo admin doesn't have an escalation policy — they ARE the escalation policy. They don't need incident management — they ARE the incident manager. The monthly cost ($21–41/user for PagerDuty, $9–15/user for OpsGenie) for a single human is pure waste.

If a customer specifically wants a "wake me up at 3 AM" channel, the right path is:
- Critical severity → Telegram push notification (default on iOS/Android, free)
- Or: PagerDuty Free tier (5 users free, supports 1 user fine)

Do not ship PagerDuty/OpsGenie in the default config.

### 5.5 Channel decision matrix

| Scenario | Default | Override option |
|---|---|---|
| Solo IT admin, has Telegram | Telegram | ntfy.sh (self-hosted), email (fallback) |
| Solo IT admin, no Telegram, has email | Email | ntfy.sh |
| 2-person IT shop (one primary, one backup) | Telegram (both subscribed to the same bot) | PagerDuty Free (if they want rotation) |
| 5+ person shop with formal on-call | PagerDuty | — |
| Air-gapped / no internet | ntfy.sh on a separate host | Email to a local SMTP relay |

---

## 6. Implementation order

The key constraint: **don't ship an alert that depends on a data source the customer doesn't have working.** Loki was the most fragile part of the stack (BACKLOG #5 retention only resolved 2026-07-03). The health-check dashboard (BACKLOG #2, RESOLVED 2026-06-28) is the only verified-working visualization. The order below respects that.

### 6.1 Phase 0 — BACKLOG #3 "Default alerting rules" (Low, ship in current PR)

**All Prometheus-based alerts that use `up{}`, `probe_success`, and `node_*` metrics. Zero new infrastructure required** — the data sources are already flowing per the BACKLOG #2 dashboard and BACKLOG #26 (blackbox probes) resolution.

**Ship list (in priority order, 14 rules):**

1. 3.1.1 prometheus self-scrape down — critical
2. 3.1.2 alloy self-scrape down — critical
3. 3.1.3 grafana self-scrape down — critical
4. 3.1.4 loki self-scrape down — critical
5. 3.1.5 blackbox_exporter self-scrape down — critical
6. 3.1.6 all observability down at once — critical (composite)
7. 3.2.1–3.2.8 blackbox probe failures — critical (8 rules rolled into one alert group)
8. 3.3.4 host memory critical (OOM imminent) — critical
9. 3.3.5 filesystem critical — critical
10. 3.3.8 filesystem read-only — critical
11. 3.3.1 host CPU sustained high — warning
12. 3.3.2 host load average high — warning
13. 3.3.6 filesystem fill prediction (7-day) — warning
14. 3.3.3 host memory pressure — warning

**Required deliverables:**
- `config/grafana/provisioning/alerting/rules.yml` (or `rules/*.yml` per rule group) with all 14 rules
- `config/grafana/provisioning/contact-points/contact-points.yml` with Telegram + email
- `config/grafana/provisioning/notification-policies/policies.yml` with the digest timing
- A bootstrap step that prompts for `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` and writes them into the contact-points file
- One `runbook.md` file per severity, linked from the alert annotations
- An update to `profiles/it_admin/skills/grafana-mcp.md` documenting the new rules and how to disable them if they're too noisy in a specific environment

**Why no Loki alerts in Phase 0:** Per BACKLOG #27, host logs aren't even visible in the dashboard yet. Shipping Loki alerts before the customer can verify the data is a recipe for "I got a Telegram at 3 AM, I checked, I don't see anything, the alert is broken." Wait for the dashboard panel to ship first, then layer alerts on top.

**Why no container alerts in Phase 0:** Per `config/alloy.yml` (current shipped state), `prometheus.exporter.cadvisor` is NOT configured. The container metrics referenced in `ARCHITECTURE.md:62-67` are not flowing. Alerting on `container_start_time_seconds` with no data means either silent no-ops (worse than missing) or false alerts. **The first task of v0.2 should be to add the cadvisor exporter to alloy.yml and resolve BACKLOG #A.**

### 6.2 Phase 1 — v0.2 (after BACKLOG #A is resolved + BACKLOG #27 panel ships)

**Adds Loki-based alerts and container alerts. Assumes the new data sources are working and visible in the dashboard.**

**Ship list (in priority order, 14 rules):**

15. 3.4.1 container crash loop — critical (requires cAdvisor)
16. 3.4.2 container OOMKilled — critical (requires cAdvisor)
17. 3.4.3 container CPU throttled — warning (requires cAdvisor)
18. 3.4.4 AIAMSBS container itself down — critical (requires cAdvisor)
19. 3.5.1 docker daemon error spike — warning
20. 3.5.2 SSH auth failure surge — warning
21. 3.5.3 sudo auth failure — warning
22. 3.5.4 kernel OOM message — critical
23. 3.5.5 loki process dying in its own logs — critical
24. 3.5.6 prometheus process dying in its own logs — critical
25. 3.5.7 grafana provisioning errors — warning
26. 3.5.8 hermes-gateway errors — warning
27. 3.5.9 hermes-gateway process restarting — critical
28. 3.5.10 network device severity spike — info

**Required deliverables:**
- `config/grafana/provisioning/alerting/rules-loki.yml` (or similar) with the 14 new rules
- An update to `config/alloy.yml` to add `prometheus.exporter.cadvisor` and a corresponding `prometheus.scrape` block
- A LogQL sanity check at install time (e.g., `curl http://localhost:3100/loki/api/v1/query?query=...` in `verify_installation`) that confirms the customer has logs flowing before alerts are enabled
- A "test alert" flow that fires a no-op critical alert to Telegram during install so the customer can verify the contact point works

### 6.3 Phase 2 — v1.0 (after Phase 1 is stable in production for 30+ days)

**Adds AIAMSBS-specific backup alerts and inventory alerts. These depend on the customer having a stable install for enough days to validate the alert thresholds.**

**Ship list (8 rules):**

29. 3.3.7 disk INODE pressure — warning
30. 3.6.1 dashboard backup cron failure — warning
31. 3.6.2 no fresh backup archive — warning
32. 3.6.3 hermes-gateway systemd service down — critical
33. 3.6.5 hermes dashboard basic auth fail — warning
34. 3.6.6 cert expiry — warning
35. 3.8.3 kb-mcp down — warning (requires adding a blackbox probe for :8002)
36. 3.8.4 nmap-discovery unresponsive — warning

**Required deliverables:**
- A `node_exporter textfile_collector` (or a small custom exporter) for the AIAMSBS-specific metrics (3.6.1, 3.6.2) — the current `prometheus.exporter.unix` doesn't expose arbitrary file-based metrics
- A blackbox probe for `kb-mcp` on `:8002` (currently missing from `config/prometheus.yml`)
- A new BACKLOG item for the cert-expiry flow (BACKLOG #7 "TLS/HTTPS" is Medium priority, not yet started; the alert depends on the deployment actually having TLS)

### 6.4 Phase 3 — v1.0+ (deferred, network/inventory-aware)

**Adds the network and inventory alerts. These are gated on the customer having populated inventory.**

37. 3.7.1 inventory MCP down — critical (duplicate of 3.2.6 but tagged as inventory-class for routing)
38. 3.7.2 inventory DB size warning — info
39. 3.7.3 discovered device count sudden change — info
40. 3.7.4 nmap-discovery last-run stale — warning
41. 3.7.5 network device syslog flow stopped — warning
42. 3.7.6 network device link state change — info

### 6.5 Signal-to-noise + data-source availability matrix

This is the single table that justifies the phasing. An "X" means "we have the data, the alert can fire." A "?" means "we need to verify." A "—" means "blocked by a prerequisite."

| Alert | Phase | `up{}` / `probe_success` | `node_*` | `container_*` | Loki | Custom |
|---|---|---|---|---|---|---|
| 3.1.x (services up) | 0 | X | — | — | — | — |
| 3.2.x (blackbox probes) | 0 | X | — | — | — | — |
| 3.3.1–3.3.4 (host CPU/mem) | 0 | — | X | — | — | — |
| 3.3.5–3.3.8 (disk) | 0 | — | X | — | — | — |
| 3.4.x (container) | 1 | — | — | — | — | blocked by BACKLOG #A |
| 3.5.x (logs) | 1 | — | — | — | ? | needs panel + cAdvisor |
| 3.6.x (backup/gateway) | 2 | — | — | — | — | needs textfile collector |
| 3.7.x (inventory) | 3 | — | — | — | — | needs inventory populated |
| 3.8.x (MCP) | 0/2 | partial | — | — | — | kb-mcp probe missing |

---

## 7. Open questions

These are decisions Ryland needs to make (or questions that need more research) before the BACKLOG #3 PR can land cleanly. **None of them block Phase 0 — every Phase 0 alert can be configured with a default answer that the customer can change later.** The questions are about getting the defaults right for the most-common customer.

1. **Disk-fill thresholds: 80/90 or 85/95?**
   The current health-check dashboard uses yellow@80, red@90 (visible in `health-check.json:506-512` for the disk gauge). This document recommends the same for the alerts. Alternative is 85/95: ext4 reserves 5% for root, so 95% is the actual "no space left" point, and 85% gives a 10% warning band. **Recommend 80/90 to match the dashboard, but flag for Ryland's review.**

2. **Backup cron failure: page immediately or batch into the daily digest?**
   This document recommends warning (batched into the 09:00 daily digest per §4). The argument for critical (immediate page) is: if the customer's disk died and the cron can't write the archive, they have no safety net, and they should know now. The argument for warning: a single missed cron is rarely urgent — the customer can recover from "yesterday's backup is missing" with "today's backup ran fine." **Recommend warning. Flag for Ryland's review.**

3. **Should we alert on the AIAMSBS-bundled dashboards themselves vs. the infrastructure underneath?**
   The current health-check dashboard is auto-provisioned from `config/grafana/provisioning/dashboards/`. If a customer modifies a panel and breaks it, that's a dashboard-level problem, not an infrastructure problem. **Recommend: do not alert on dashboard-level breakage (the customer is in the loop; if their edit breaks something, they see it). Do alert on infrastructure-level breakage (3.1.x, 3.2.x, 3.5.7).** This is consistent with `profiles/it_admin/skills/non-destructive-operations.md`'s "don't act on customer-authored state without approval" principle.

4. **The `job="integrations/unix"` label drift.**
   `config/alloy.yml:4-12` configures `prometheus.exporter.unix "self"` and `prometheus.scrape "host"` without a `job_name` override. The verified-working health-check dashboard at `config/grafana/provisioning/dashboards/health-check.json:489` queries `job="integrations/unix"`. The live state on VM 220 (per BACKLOG #2 verification) is that this label is present. **Either (a) the live alloy config differs from the repo, (b) there's a `prometheus.relabel` step not committed, or (c) the `job` label is being set by a separate `prometheus.scrape` block we don't see.** Need to reconcile before the alert PR — otherwise the alert queries won't match the metric labels and will silently never fire.

5. **Should `nmap-discovery` and `kb-mcp` get blackbox probes in the default config?**
   `nmap-discovery` uses `network_mode: host` and has no published port (`inventory-stack/docker-compose.yml:26-41`). Probing it requires a different approach (process check, systemd unit check, or a custom exporter). `kb-mcp` exposes `:8002` and is missing from `config/prometheus.yml` blackbox jobs. **Recommend: add the kb-mcp probe in Phase 2 alongside the kb-mcp alert. Skip nmap-discovery in the default — gate it on the customer enabling the `discovery` profile.**

6. **Should we ship a Hermes-gateway health check via a `node_exporter` systemd collector or via Loki log scraping?**
   The current `config/alloy.yml` does not configure `prometheus.exporter.unix` with the `systemd` collector enabled (or any systemd-specific collector at all). Adding it would let us query `node_systemd_unit_state` directly. The Loki fallback (3.5.8, 3.5.9) works without the collector but is harder to write tests for. **Recommend: enable the `systemd` collector in `prometheus.exporter.unix` so the Prometheus-side alerts are clean, and keep the Loki alerts as a backup for customers who disable the collector.**

7. **What's the right "AIAMSBS bundle" for the `node_textfile` collector?**
   BACKLOG #3 doesn't currently plan to add `node_textfile` to `config/alloy.yml`. But 3.6.1 (backup cron failure) and 3.6.2 (no fresh backup archive) really want a textfile metric. Options:
   - Add `node_exporter` textfile collector to the alloy config (but the current setup uses `prometheus.exporter.unix`, not the binary `node_exporter` — may not have textfile support).
   - Ship a tiny custom Python exporter that writes `/metrics` on a port and have Prometheus scrape it.
   - Use a cron job that writes a file and rely on the `unix` exporter's `textfile` collector if it has one.
   **Recommend: ship a tiny custom exporter (~50 lines of Python) at `services/aiamsbs-exporter/`, scraped on `:9117`, that wraps the backup script's exit code and timestamp. This is a v1.0 task, not Phase 0.**

8. **Should alert rules be in Grafana Unified Alerting (the Grafana-native engine) or in a separate Prometheus rule_files with a Prometheus-side alertmanager?**
   AIAMSBS does not currently ship a separate `alertmanager` container. Grafana 13.x can evaluate Prometheus rules itself (Grafana Unified Alerting). The recommendation in this document assumes Grafana Unified Alerting. **This is the right call for a small shop** — fewer moving parts, no separate alertmanager to monitor. **Confirm with Ryland before BACKLOG #3 PR.**

9. **Multi-host future: when the customer has more than one AIAMSBS server, how do alerts route?**
   BACKLOG #10 ("Add hostname label to Alloy metrics") is the prerequisite. Per this document, every alert that uses `by (instance)` would automatically scope to a host once the `hostname` label is added. The severity matrix (§4) is per-alert, not per-host. **For Phase 0, design the rule queries to include `{cluster="aiamsbs"}` (already in `config/prometheus.yml:7`) and `by (instance)` aggregations so they're multi-host-safe from day one.**

10. **The "send a test alert during install" flow.**
    Bootstrap could fire a one-shot Telegram message at the end of install to confirm the contact point works. This is a UX improvement, not a strict requirement. **Recommend: ship in Phase 0 — the 30 seconds of bootstrap time is well worth the "I know my alerts will actually arrive" confidence for the customer.** Implementation: a `test_telegram_contact_point` function in `bootstrap.sh` that POSTs a `grafana/alerting/notification/test` request.

11. **Documentation surface: should runbook actions be in alert annotations (visible in the Telegram message) or in a separate `runbooks/` directory the alert links to?**
    Alert annotations have a size limit (~10KB per the [Grafana alertmanager template docs](https://prometheus.io/docs/alerting/latest/notifications/)). Short, actionable runbook hints fit ("run `docker compose restart prometheus` and check `docker logs prometheus --tail 100`"). Detailed runbooks should be in a separate file. **Recommend: short hint in annotation, full runbook in `config/grafana/provisioning/alerting/runbooks/<alert-name>.md` linked from the annotation via a `runbook_url` label.**

12. **Cert expiry thresholds when BACKLOG #7 (TLS/HTTPS) ships.**
    This document assumes 30-day warning, 14-day critical as the initial values. When the TLS work is done, the right value depends on how the cert is renewed (certbot auto-renewal = 14-day is fine; manual = 30-day is the floor). **Defer to BACKLOG #7 implementation.**

---

## Appendix A: Documented alert rules (PromQL + LogQL reference)

This appendix collects every query in this document in one place for copy/paste into the Grafana rule provisioning YAML. Comments document the `for:` duration; the YAML key would be `for:` per rule.

### Prometheus rules (Phase 0)

```yaml
# 3.1.1 - 3.1.5: per-service up{} down
- expr: up{job="prometheus"} == 0
  for: 2m
  labels: { severity: critical, category: service-availability }
- expr: up{job="alloy"} == 0
  for: 2m
  labels: { severity: critical, category: service-availability }
- expr: up{job="grafana"} == 0
  for: 2m
  labels: { severity: critical, category: service-availability }
- expr: up{job="loki"} == 0
  for: 2m
  labels: { severity: critical, category: service-availability }
- expr: up{job="blackbox_exporter"} == 0
  for: 2m
  labels: { severity: critical, category: service-availability }

# 3.1.6: composite — all observability down
- expr: count(up{job=~"prometheus|alloy|grafana|loki|blackbox_exporter"} == 1) == 0
  for: 2m
  labels: { severity: critical, category: service-availability }

# 3.2.1 - 3.2.8: blackbox probe failures (sample for grafana)
- expr: probe_success{job="blackbox", instance="http://localhost:3000/api/health"} == 0
  for: 2m
  labels: { severity: critical, category: blackbox }
# (repeat for each blackbox job+instance)

# 3.3.1: host CPU sustained high
- expr: avg by (instance) (100 - (rate(node_cpu_seconds_total{mode="idle", job="integrations/unix"}[5m])) * 100) > 90
  for: 15m
  labels: { severity: warning, category: host-health }

# 3.3.3: host memory pressure
- expr: (1 - (node_memory_MemAvailable_bytes{job="integrations/unix"} / node_memory_MemTotal_bytes{job="integrations/unix"})) * 100 > 90
  for: 10m
  labels: { severity: warning, category: host-health }

# 3.3.4: host memory critical (OOM imminent)
- expr: (1 - (node_memory_MemAvailable_bytes{job="integrations/unix"} / node_memory_MemTotal_bytes{job="integrations/unix"})) * 100 > 97
  for: 2m
  labels: { severity: critical, category: host-health }

# 3.3.5: filesystem critical
- expr: node_filesystem_avail_bytes{mountpoint=~"/|/var", job="integrations/unix"} / node_filesystem_size_bytes{mountpoint=~"/|/var", job="integrations/unix"} * 100 < 10
  for: 5m
  labels: { severity: critical, category: host-health }

# 3.3.6: filesystem fill prediction
- expr: predict_linear(node_filesystem_avail_bytes{mountpoint="/var/lib/docker", job="integrations/unix"}[6h], 7 * 24 * 3600) < 0
  for: 30m
  labels: { severity: warning, category: host-health }

# 3.3.8: filesystem read-only
- expr: node_filesystem_readonly{mountpoint=~"/|/var", job="integrations/unix"} == 1
  for: 1m
  labels: { severity: critical, category: host-health }
```

### Loki rules (Phase 1)

```yaml
# 3.5.1: docker daemon error spike
- expr: sum(rate({job="docker", source="aiamsbs_host"} |~ "(?i)error|panic|fatal" [5m])) > 5
  for: 5m
  labels: { severity: warning, category: log-based }

# 3.5.2: SSH auth failure surge
- expr: sum(rate({job="systemd", source="aiamsbs_host"} |~ "sshd.*(Failed password|Invalid user|Connection closed by)" [5m])) > 0.5
  for: 10m
  labels: { severity: warning, category: log-based }

# 3.5.4: kernel OOM message
- expr: sum(rate({job="systemd", source="aiamsbs_host", _TRANSPORT="kernel"} |~ "Out of memory: Killed process" [5m])) > 0
  for: 1m
  labels: { severity: critical, category: log-based }

# 3.5.7: grafana provisioning errors
- expr: sum(rate({job="docker", compose_service="grafana"} |~ "Failed to load dashboard|Dashboard title cannot be empty|provisioning" [10m])) > 0.1
  for: 10m
  labels: { severity: warning, category: log-based }
```

---

## Appendix B: References

### AIAMSBS files cited in this document

- `BACKLOG.md` — item #3 (Default alerting rules, this research), #5 (Log retention, RESOLVED), #11 (Test syslog, RESOLVED), #26 (Blackbox probes, RESOLVED), #27 (Host logs in health dashboard, in flight), #A (Fix container metrics, prerequisite for Phase 1), #B (Add hostname label, future-proofing)
- `docker-compose.yml:81` — `grafana/grafana:13.0.1` (Grafana 13.x, Unified Alerting)
- `docker-compose.yml:7` — `prom/prometheus:v2.54.1`
- `docker-compose.yml:27` — `grafana/loki:3.2.0`
- `config/prometheus.yml` — scrape job definitions (8 blackbox jobs, 5 self-scrape jobs)
- `config/blackbox.yml:13-50` — 4 blackbox modules: `http_2xx`, `http_2xx_login`, `http_2xx_or_404`, `tcp_connect`
- `config/loki.yml:36` — `retention_period: 2160h` (90 days)
- `config/loki.yml:43-46` — compactor configuration (Loki 3.x in-process)
- `config/alloy.yml` — `prometheus.exporter.unix "self"` (note: no cadvisor currently), `loki.source.docker "containers"`, `loki.source.journal "systemd"`
- `config/promtail.yml:14-21` — `job="network_syslog"`, `source="network_device"`
- `config/grafana/provisioning/dashboards/health-check.json` — verified-working panel queries that the alerts must match
- `docker-compose.mcp.yml` — `grafana-mcp` on `:8000`
- `inventory-stack/docker-compose.yml:8-24` — `inventory-mcp` on `:8001`
- `inventory-stack/docker-compose.yml:26-41` — `nmap-discovery` (network_mode host, no published port)
- `kb-stack/docker-compose.yml:14` — `kb-mcp` on `:8002`
- `~/.hermes/cron/jobs.json` — existing Telegram delivery pattern (`deliver: "telegram:8704545814"`)
- `~/.hermes/cron/jobs.json` — Daily Backlog Reminder (09:00 cron, suitable target for warning digest)
- `profiles/it_admin/SOUL.md` — non-destructive operating policy, Confirmation Standard
- `profiles/it_admin/skills/monitoring-observability.md:54-63` — Alert Quality Rules (actionable, low-noise, severity-based)
- `profiles/it_admin/skills/grafana-mcp.md` — `alerting_manage_rules` MCP tool, alerting workflow
- `profiles/it_admin/skills/dashboard-backup.md` — `AIAMSBS Dashboard Backup` cron, gateway-dependency
- `profiles/it_admin/skills/non-destructive-operations.md` — confirmation flow for write operations
- `profiles/it_admin/skills/security-baseline.md` — referenced for sudo / SSH triage

### External references

- Grafana Alerting fundamentals — https://grafana.com/docs/grafana/latest/alerting/fundamentals/
- Grafana Telegram contact point — https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/#telegram
- Grafana Unified Alerting group timing — https://grafana.com/docs/grafana/latest/alerting/fundamentals/notifications/#grouping
- Grafana ntfy contact point (webhook) — https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/#webhook
- Prometheus alerting rules — https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
- Prometheus `predict_linear` — https://prometheus.io/docs/prometheus/latest/querying/functions/#predict_linear
- Loki LogQL — https://grafana.com/docs/loki/latest/query/
- Loki alerting best practices (per-query limit, splitting by tenant) — https://grafana.com/docs/loki/latest/alert/

### Companion research

- `research/multi-oem-skill-research-2026-06-22.md` — multi-vendor monitoring patterns
- `research/multi-oem-path-forward-2026-06-22.md` — strategic ship sequence
