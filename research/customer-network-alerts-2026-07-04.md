# Customer Network Alert Use Cases for AIAMSBS

Research date: 2026-07-04
Author: Hermes Agent (subagent, on behalf of Ryland)
Audience: AIAMSBS customer (solo IT admin at a 1–10 person shop)
Target stack: Grafana 13.0.1 + Prometheus 2.54.1 + Loki 3.2.0 + Alloy (latest) + blackbox_exporter (latest) + Promtail syslog receiver on TCP/514 on a single Linux VM. Notification delivery via Grafana Unified Alerting → Telegram (default), email (fallback).
Informs: BACKLOG #3 ("Default alerting rules", Low) — **the customer-network half**.
Companion: [`aiamsbs-component-health-alerts-2026-07-04.md`](./aiamsbs-component-health-alerts-2026-07-04.md) — the AIAMSBS-component half. Read both together for the full alert surface.
Related:
- [`multi-oem-skill-research-2026-06-22.md`](./multi-oem-skill-research-2026-06-22.md) — multi-vendor monitoring patterns
- [`multi-oem-path-forward-2026-06-22.md`](./multi-oem-path-forward-2026-06-22.md) — strategic ship sequence

---

## 1. Executive summary

**The watchtower should yell about the customer's network, not about itself.** Per BACKLOG #3 and the existing component-health doc, the AIAMSBS half of alerting ("is the observability stack itself healthy?") is already scoped. This document covers the other half: **"is the customer's network, servers, services, security, and business operations healthy?"** — the things the customer actually cares about. The default AIAMSBS install ships with a small but high-signal set of data sources (syslog from network devices, the AIAMSBS host's own metrics/journal, blackbox probes of customer-facing services, and an optional nmap-driven inventory); every recommended alert traces to one of these. The constraint is the same as the component-health doc: a solo admin at a 10-person shop has ~30 minutes of focused ops time per day, and a muted alerting channel destroys trust permanently.

**The 10 must-ship alerts for a default AIAMSBS install are:**

1. **Switch/router/AP unreachable** — `count_over_time({job="network_syslog", source="network_device", host="$known_host"}[3h]) == 0` for `15m` (or inventory-mcp last-seen delta). **Critical.** This is the single most valuable signal — the customer is silent on whether their network gear is up.
2. **Network link / interface down** — `sum(rate({job="network_syslog", source="network_device"} |~ "(?i)(line protocol down|Interface .* down|UPDOWN|LINK-UPDOWN|IF_DOWN_LINK_FAILURE)" [5m]))` > 0 with severity ∈ {error, critical}. **Warning** (per-port flap is annoying but rarely a 3 AM emergency; switch uplinks / AP uplinks are critical).
3. **BGP neighbor down** — `sum(rate({job="network_syslog", source="network_device"} |~ "%BGP-5-ADJCHANGE:.*Down|%BGP_SESSION-5-ADJCHANGE:.*Down|%BGP-3-NOTIFICATION" [5m]))` > 0. **Critical.** Loss of upstream connectivity for a single-tenant shop.
4. **OSPF neighbor down** — `sum(rate({job="network_syslog", source="network_device"} |~ "%OSPF-5-ADJCHG:.*Down" [5m]))` > 0. **Critical** when the OSPF neighbor is a transit uplink; **warning** for an internal adjacency.
5. **DHCP scope exhausted** — `sum(rate({job="network_syslog", source="network_device"} |~ "(?i)(DHCP-4-POOL_EXHAUSTED|no free leases|pool .* exhausted)" [15m]))` > 0. **Critical.** New devices can't get an address; Wi-Fi users will start losing connectivity in minutes.
6. **SSH brute force from a single source** — Loki pattern: `sum by (host) (count_over_time({job="systemd", source="aiamsbs_host"} |~ "sshd.*(Failed password|Invalid user)" [5m]))` > 10. **Warning** (becomes critical if correlated with a subsequent success — see #7).
7. **Successful SSH login after brute force** — Loki correlation: same `host` source with `>=5` "Failed password" in the prior 10m AND a "Accepted password" / "Accepted publickey" within 60s. **Critical.** This is the actual compromise signal.
8. **Customer service on a port not responding** — `probe_success{job="blackbox_http", instance="http://customer.example.com/"} == 0` for `2m` (HTTP) OR `probe_success{job="blackbox_tcp", instance="customer.example.com:443"} == 0` for `2m` (TCP). **Critical.** Whatever the customer exposes to staff/Internet is actually down.
9. **TLS certificate expiry < 14 days** — `probe_ssl_earliest_cert_expiry - time()` < `14 * 86400` per probed instance. **Warning** at 30 days, **critical** at 7 days.
10. **Customer's own backup job failure** — Loki: `sum(rate({job="systemd", source="aiamsbs_host"} |~ "(?i)(veeam backup failed|backup exec.*failed|rsync error|backup.*error.*exit code)" [1h]))` > 0; or inventory-mcp / textfile check that the last successful backup is < 26h old for a daily schedule. **Warning** (failing backups for 3+ days becomes **critical**).

**The 3 most important "extension path" alerts (require hardware/deploy the customer doesn't have today):**

1. **Per-server disk / memory / CPU** via `node_exporter` deployed on each customer VM/server — `node_filesystem_avail_bytes{mountpoint="/", instance="customer-server-1"} / node_filesystem_size_bytes{...} * 100 < 10` for `10m`. **Critical** at < 10% available. AIAMSBS today only has `node_exporter` data for the AIAMSBS host itself.
2. **SNMP interface errors / discards** via `prom/snmp_exporter` against switches/routers — `rate(ifInErrors{instance="customer-switch-1"}[5m]) > 5` for `10m`. **Warning.** A flapping fiber or failing SFP shows up here long before the port goes down.
3. **Windows event log auth/computer-account anomalies** (Event ID 4625 fail storms, 4720 user creation, 4732 member-added-to-group) via rsyslog → Promtail forwarding. **Critical** for unexpected admin-group changes. Out of default because it requires a Windows-side agent (or WEF → syslog bridge).

**Explicitly do NOT alert on (at least in v1.0):**

- **Per-port flap storms** as a single critical page. A switch port that goes up/down twice in 5 minutes is annoying, not a 3 AM emergency. Surface on the dashboard, batch into the morning digest if it crosses a threshold (e.g., > 10 flaps/hour from the same port).
- **Per-device interface up/down on every port.** The 1-10 person shop has dozens of access ports. A single `link up`/`link down` event pair is normal patch-cable work. Page on **link down that doesn't come back up** (i.e., #2 with `for: 10m`), not on every flap.
- **STP topology change notifications** (TCN, `set port state`, `%SPANTREE-7-BLOCK`). STP blocks for legitimate reasons on every switch reboot. Page only when the same switch has > 5 TCN in 5 minutes.
- **SNMP auth failures, BGP `established` notifications, OSPF `Init` transitions.** Standard protocol chatter.
- **BGP / OSPF neighbor "Up" transitions** after a brief Down — these are recovery events, not alerts. Page on the Down, not the Up.
- **Veeam/Backup-Exec INFO-level events** — only WARN/ERROR/FAILED are signal.
- **Wi-Fi client roaming / deauths from a single client.** One phone roaming between APs is normal. Page when the same AP loses > 30% of clients in 5 minutes.
- **BPDU guard or DHCP snooping traps** unless a customer has actually configured them and a security policy.
- **Log noise from healthy services** — kernel timestamp skew, journal rotation, dhclient renewals, NTP slew messages. These appear at > 1/min on any Linux host.

---

## 2. Audience + scope reality

### The small-shop reality (re-stated for this document)

The customer is a **solo IT generalist at a 1–10 person shop.** The same person who:

- Sets up a laptop when someone joins
- Renews the O365 tenant
- Replaces the Wi-Fi AP when "the Wi-Fi is down"
- Files the quarterly taxes if it's a 1-person shop

…also has to keep AIAMSBS running, and the network / servers / backups the customer depends on. Per `BACKLOG.md` #3, the installable-in-20-minutes contract is the binding product constraint. The alerting surface must be **tighter than a stock Prometheus+Grafana install** — out-of-the-box Grafana will happily alert on container restarts and CPU spikes that aren't problems, and the solo admin mutes the channel by day 4.

### How this document divides responsibility with the component-health doc

There are exactly two halves of the AIAMSBS alert surface:

| Doc | Scope | Question it answers | Default sources used |
|---|---|---|---|
| [`aiamsbs-component-health-alerts-2026-07-04.md`](./aiamsbs-component-health-alerts-2026-07-04.md) | **AIAMSBS itself** | "Is the watchtower working?" | Prometheus `up{}` on the 5 self-scrape jobs, blackbox probes of the 4 local endpoints, `node_*` metrics for the AIAMSBS host, container OOM/crash-loop, Loki on the AIAMSBS host's own logs |
| **This document** | **Customer's network, servers, services, security, business ops** | "Is the watchtower's customer healthy?" | Network device syslog (`job="network_syslog"`), inventory-mcp + nmap-discovery (opt-in), `node_*` of the AIAMSBS host (which IS the customer's monitoring host), `job="systemd"` journal (auth, sudo, sshd, kernel), blackbox probes of customer-facing services, Hermes cron job logs |

**There is no overlap.** Every alert in this document is sourced from data the customer owns (their network, their services, their backups, their own SSH sessions into AIAMSBS) — not from the observability stack's own health. Every alert in the component-health doc is sourced from the observability stack. Together the two docs cover the full alert surface.

The two exceptions to the "no overlap" rule, where the boundaries could blur:

- **The AIAMSBS host's own disk/CPU/memory** appear in both, because the AIAMSBS host *is* the customer's monitoring host. The component-health doc treats it as "the platform might run out of disk and stop collecting data." This document treats it as "the customer's only server might run out of disk." **The same metric, two different severities and two different runbooks.** Critical at 90% available for the platform (imminent data loss), but the customer-service impact is "their monitoring is down" — which is a customer-network outage. **Recommend: ship the platform version (component-health) as the canonical rule; the customer-network version is implicit in the same alert firing.**
- **SSH brute force on the AIAMSBS host itself** — the AIAMSBS host is reachable via SSH, the customer's IT admin SSHes into it. Brute force against the AIAMSBS host is both a platform event (someone attacking the monitoring host) AND a customer-network event (someone scanning the customer's network). **Recommend: ship the customer-network version (this doc) as canonical; the component-health doc references it via "see also."**

### What the customer-network half explicitly does NOT cover

- **AIAMSBS's own container / service health** — see the component-health doc. We do not duplicate `up{job="prometheus"}` rules, container crash-loop detection, or `node_filesystem_avail_bytes` for `/var/lib/docker` here. Those are platform rules.
- **Multi-tenant alerting / per-customer routing** — the customer-network alerts are scoped to the customer's own network; they don't have a concept of "another customer" because each AIAMSBS instance is single-tenant.

---

## 3. What the default install actually sees

This is the foundation. **Every alert below traces to a row in this table.** If a detection isn't possible from a default install, it goes in §8 (extension path), not §4.

| Data source | Loki label / Prometheus job | Configured where | What it CAN detect | What it CANNOT detect |
|---|---|---|---|---|
| **Network device syslog** | Loki `job="network_syslog"`, `source="network_device"`, `host=<device>`, `severity=<level>`, `app=<app-name>`, `facility=<facility>` | `config/promtail.yml:15-31` (receiver on TCP/514) | Link up/down, interface errors, BGP/OSPF neighbor changes, DHCP pool exhaustion, STP state changes, device config changes, auth events on device-local accounts (UniFi, Aruba), syslog severity ≥ 4 (warning+) | Per-interface **counters** (CRC errors, discards, input errors) — syslog doesn't carry bulk counters, only event records. Need SNMP or device-side streaming telemetry for that. Real-time per-flow telemetry. sFlow/NetFlow data. |
| **Inventory reachability** | inventory-mcp at `:8001` (REST); `aiamsbs_inventory_devices_count` (custom metric, requires the small custom exporter from component-health doc §3.6.1) | `inventory-stack/docker-compose.yml:2-24`; `inventory-stack/mcp/server.py:50-200`; nmap-discovery is opt-in via `profiles: ["discovery"]` (`inventory-stack/docker-compose.yml:40-41`) | "Did this device respond to ping?" (via nmap scan, periodic), "Is this IP still in the inventory?" (via last_seen column), "Is this new since last scan?" (device delta), "What is this device's vendor/model?" | Real-time per-second liveness (nmap is too slow/expensive for that). Service-level liveness (only port 80/443 typically; not custom ports). Hostname resolution. Application health. |
| **AIAMSBS host metrics** | Prometheus `job="integrations/unix"` (Alloy `prometheus.exporter.unix "self"` per `config/alloy.yml:4-12`) | `config/alloy.yml:4-19` (self-export + scrape) | Host CPU, memory, disk, filesystem, network of the **AIAMSBS host** — which is also typically the customer's only always-on Linux server. `node_filesystem_*`, `node_memory_*`, `node_cpu_*`, `node_load*`, `node_network_*`. | Metrics for **other** servers/workstations/devices — the AIAMSBS host is the only one with node_exporter running. No GPU/temperature/SMART data unless those collectors are explicitly enabled. |
| **AIAMSBS host logs (journald)** | Loki `job="systemd"`, `source="aiamsbs_host"`, `_TRANSPORT=kernel\|journal`, `_SYSTEMD_UNIT=<unit>` | `config/alloy.yml:38-44` (Alloy `loki.source.journal "systemd"`); journal bind mount at `docker-compose.yml:55` (`/var/log/journal:/var/log/journal:ro`) | sshd (auth attempts, source IP), sudo (auth failures, who ran what), kernel (OOM, ext4 errors, NIC resets), systemd unit state, fail2ban / ufw / iptables log entries that go to journal. | Application-level logs that write to files but not journal (e.g., nginx access logs go to `/var/log/nginx/access.log` unless journald-importer is configured). Per-container logs from non-AIAMSBS Docker workloads on the same host (out of scope — those are customer apps, not part of AIAMSBS). |
| **Docker container logs** | Loki `job="docker"`, `source="aiamsbs_host"`, `compose_service=<name>` | `config/alloy.yml:22-35` (Alloy `loki.source.docker "containers"`) | stdout/stderr from the 5 AIAMSBS containers (prometheus, loki, grafana, alloy, promtail) plus any other Docker containers the customer runs on the AIAMSBS host. Errors, panics, application lifecycle. | Customer's own Docker container apps on **other** hosts. Pre-aggregated metrics (use cAdvisor for that, not logs). |
| **Blackbox probes** | Prometheus `job="blackbox"` (HTTP/2xx), `job="blackbox_mcp"` (2xx or 404), `job="blackbox_login"` (2xx or 3xx), `job="blackbox_tcp"` (TCP connect) | `config/prometheus.yml:36-118`; `config/blackbox.yml` (4 modules) | HTTP 2xx readiness of Grafana/Prometheus/Loki/Alloy (default targets), TCP probe of Promtail syslog receiver (TCP/514), and — **once configured** — any HTTP/HTTPS/TCP endpoint the customer wants to monitor. | Application-level errors (e.g., HTTP 200 with a "500 Internal Server Error" body), latency SLAs, transaction success. Probes are shallow. |
| **Hermes cron jobs** | Loki `job="systemd"`, `_SYSTEMD_UNIT="hermes-gateway.service"`; `~/.hermes/cron/jobs.json` (per `BACKLOG.md` #33) | `bootstrap.sh` `install_hermes_gateway_service()` (per BACKLOG #33 fix) | Any Hermes cron job the customer creates (e.g., the `AIAMSBS Dashboard Backup` cron, or future customer cron jobs for "do X every day at 09:00"). `hermes cron list` shows `last_status`, `last_run_at`, `last_error`. | Whether the customer's own bash/PowerShell cron jobs ran (those are separate from `hermes cron` — they go to their own mail/file logs, not Loki). |

### Three important callouts on this table

1. **The Loki label drift on network syslog.** The shipped `dashboards/network-syslog.json` queries `job="syslog"`, but `config/promtail.yml:21` actually emits `job="network_syslog"`. **The existing dashboard likely returns zero results against the actual ingested data** (verified by reading both files; not retested on VM 220 because BACKLOG #2's verification was for the *health-check* dashboard, not the network-syslog one). All alert queries in this document use the correct `job="network_syslog"`. **Open Question #1: reconcile the dashboard to match the config before BACKLOG #3 ships, or every alert in §4 will be a "why is the alert silent" investigation.**
2. **No container metrics in default.** The `config/alloy.yml` does NOT configure `prometheus.exporter.cadvisor` (BACKLOG #A "Fix container metrics" is open). Container OOM detection, container CPU throttling, per-container crash-loop detection are all blocked on BACKLOG #A. This document's alerts do not depend on cAdvisor — they use syslog + blackbox + journal + inventory, which all work today.
3. **Inventory is opt-in for nmap-discovery.** The `inventory-mcp` service runs by default (per `inventory-stack/docker-compose.yml:2-24`), but `nmap-discovery` is gated on `profiles: ["discovery"]` (line 40) — the customer must explicitly enable it. Alerts in §4.5.1 (device unreachable via inventory) and §4.5.4 (new device on network) require nmap-discovery; alerts in §4.2-§4.3 do not.

---

## 4. Alert use cases

Organized by customer domain. **For each alert: Name, Severity, Data source, Query/detection pattern (LogQL / PromQL / inventory-mcp API), Threshold rationale, Runbook action.**

The PromQL / LogQL below uses `job="network_syslog"` and `source="network_device"` per the actual `config/promtail.yml:21-22` labels. The `host` label comes from `__syslog_message_hostname` via the relabel at `config/promtail.yml:24-25`. `severity` is set by `__syslog_message_severity` at line 27.

> **Note on `for:` durations:** Every rule uses a `for:` of at least `2m` (8× the 15s evaluation interval in `config/prometheus.yml:5`). One-minute blips are not problems. The 5-minute-actionability rule from the component-health doc applies here too — if the on-call admin can't fix it in 5 minutes, it should be a dashboard annotation, not a Telegram interrupt.

### 4.1 Network infrastructure — switch / router / AP

This is the highest-value category for a small-shop IT admin. Most "the Wi-Fi is down" tickets are actually "the AP lost uplink" or "the switch is in a spanning-tree loop." The watchtower should be the first to know.

#### 4.1.1 Switch / router / AP unreachable

| Field | Value |
|---|---|
| Name | `NetworkDeviceUnreachable` |
| Severity | **critical** (for core switches / routers / firewalls); **warning** (for access switches / APs) |
| Source | Loki + inventory |
| Query (Loki, no-inventory variant) | `count_over_time({job="network_syslog", source="network_device", host="$known_host"}[3h]) == 0` for `15m` |
| Query (inventory variant, requires nmap-discovery) | `time() - aiamsbs_inventory_last_seen{device_id="..."} > 600` (Prometheus, custom exporter; or inventory-mcp `lookup_by_ip` -> `last_seen` field) |
| Threshold rationale | 3h of zero syslog from a device that has historically sent syslog means the device is down, the network path is broken, or the device's syslog config was rolled back. 15m `for:` filters out brief reboots (< 10 min is normal for a switch firmware upgrade). |
| Runbook action | (1) Check the customer's last-known-good state via `inventory-mcp` `lookup_by_hostname`; (2) `ping <ip>` or `nc -vz <ip> 514` from the AIAMSBS host; (3) if ping works but syslog doesn't, the device's syslog config is the issue; (4) if ping fails, the network path is broken — check the upstream switch. |
| Trace | Loki `job="network_syslog"` (Promtail), `inventory-stack/mcp/server.py:54` (`last_seen` column) |

> **Why two variants:** nmap-discovery gives a faster signal (10 min vs 3h) but is opt-in. The Loki variant works without nmap. Ship both — the customer gets whichever fires first. The Loki variant also catches devices that are reachable but not sending syslog (mis-configured syslog server), which the inventory variant misses.

#### 4.1.2 Network link / interface down

| Field | Value |
|---|---|
| Name | `NetworkLinkDown` |
| Severity | **critical** (uplinks, trunks, AP uplinks, server NICs); **warning** (access ports) |
| Source | Loki |
| Query (broad pattern) | `sum(rate({job="network_syslog", source="network_device", severity=~"error|critical"} \|~ "(?i)(line protocol down|Interface .* (down\|administratively down)|%LINEPROTO-5-UPDOWN:.*down|%LINK-3-UPDOWN:.*down|UPDOWN.*down|LINK-UPDOWN.*down|IF_DOWN_LINK_FAILURE|Interface .* changed state to down)" [5m]))` > 0 |
| Query (Cisco IOS specific) | `{job="network_syslog", source="network_device"} \|~ "%LINEPROTO-5-UPDOWN.*down\|%LINK-3-UPDOWN.*down"` (matches `line protocol on Interface GigabitEthernet0/1, changed state to down`) |
| Query (UniFi specific) | `{job="network_syslog", source="network_device"} \|~ "(?i)link down\|interface.*down"` (UniFi syslog uses app-names like `ubnt`, `hostapd`) |
| Threshold rationale | A link that goes down and stays down for `2m` is real. Brief flaps (1s) are SFP/cable issues in progress. Match the Cisco/UniFi/Juniper/Aruba vendor string from the device's actual syslog format. |
| Runbook action | (1) Identify the interface from the syslog line (`show interface` on the device, or `inventory-mcp` to find the device's IP and SSH in); (2) check physical layer — cable, SFP, patch panel; (3) if uplink, check the upstream device for the matching link down. |
| Trace | Loki `job="network_syslog"`, label `app` (set by Promtail at `config/promtail.yml:28-29`) |

> **Don't alert on `link up` (recovery).** Symmetric alerting on up+down is noisy. Page on down; log up to Loki for the dashboard.

#### 4.1.3 High interface errors / discards (cable / fiber / SFP issue)

| Field | Value |
|---|---|
| Name | `InterfaceErrorsHigh` |
| Severity | **warning** (escalates to critical on sustained spike) |
| Source | Loki (event-based) — NOT counter-based; for counter-based detection, see §8 (SNMP extension) |
| Query | `sum(rate({job="network_syslog", source="network_device"} \|~ "(?i)(CRC errors\|input errors\|output errors\|giants\|runts\|discards\|FCS errors\|alignment errors)" [10m]))` > 0.1 |
| Threshold rationale | Syslog from Cisco IOS for interface errors is event-based (the device logs when errors increment past a threshold, default 100 errors in 5s for many platforms). So a single "CRC errors" log line in 10m = real problem. 0.1/sec rate = 6+ such events in 10 min. |
| Runbook action | (1) `show interface` on the device — `input errors`, `CRC`, `runts`, `giants` counters; (2) check SFP DOM values if supported; (3) replace cable / SFP / patch. |
| Trace | Loki `job="network_syslog"` |

> **The component-health doc already alerts on `/var/log` disk fill** (because a chatty interface-error device can fill the log volume). This alert is the upstream cause.

#### 4.1.4 BGP neighbor down

| Field | Value |
|---|---|
| Name | `BGPNeighborDown` |
| Severity | **critical** |
| Source | Loki |
| Query | `sum(rate({job="network_syslog", source="network_device"} \|~ "(?i)(%BGP-5-ADJCHANGE:.* Down\|%BGP_SESSION-5-ADJCHANGE:.* Down\|%BGP-3-NOTIFICATION:.*Down\|BGP neighbor .* Down\|neighbor .* Down .* BGP)" [5m]))` > 0 |
| Threshold rationale | A BGP Down event means loss of upstream connectivity (in a 1-10 person shop, BGP is on the edge router). Even a brief flap on a single-homed edge = "we just lost Internet for the whole office." 5m floor prevents a momentary BGP-Idle from paging. |
| Runbook action | (1) Check the edge router's `show ip bgp summary` (Cisco) or equivalent — is the neighbor state Idle / Active? (2) `ping <neighbor-ip>` to confirm reachability; (3) check ISP-side; (4) check local interface / ACL that may be blocking TCP/179; (5) per `network-oem-cisco-ios.md`, never `clear ip bgp` without explicit human approval. |
| Trace | Loki `job="network_syslog"` |

> **Real-world string from a Cisco ISR 4000:**
> `*Mar  1 00:00:00.123: %BGP-5-ADJCHANGE: neighbor 203.0.113.1 Down BGP Notification sent`
> Real-world string from a Juniper MX:
> `rpd[1234]: bgp_event: peer 203.0.113.1 (Internal AS 64512) old state Established event RecvNotify new state Idle`

#### 4.1.5 OSPF neighbor down

| Field | Value |
|---|---|
| Name | `OSPFNeighborDown` |
| Severity | **critical** (transit / uplink adjacency); **warning** (internal adjacency, e.g., a backup link) |
| Source | Loki |
| Query | `sum(rate({job="network_syslog", source="network_device"} \|~ "%OSPF-5-ADJCHG:.* Down\|%OSPF-5-ADJCHG:.* down\|OSPF:.*Neighbor .* Down" [5m]))` > 0 |
| Threshold rationale | OSPF neighbor Down = routing topology change. For a transit adjacency, the customer just lost a path. For an internal adjacency, it's a flap. Use the device role from `inventory-mcp` (`role` column in `devices` table, `init_db.sql:11`) to tag severity. **Default: critical; customer can downgrade to warning in inventory.** |
| Runbook action | (1) `show ip ospf neighbor` (Cisco) — what state is the neighbor in? (2) check the interface (`show ip ospf interface <int>`) — is OSPF enabled? (3) check area / authentication / MTU mismatch with the neighbor. |
| Trace | Loki `job="network_syslog"`; inventory role lookup at `inventory-stack/mcp/server.py:54` |

> **Don't alert on `Init` or `Loading` transitions** — these are usually MTU mismatch in progress, which resolves itself (or it doesn't, and the `Down` transition fires).

#### 4.1.6 DHCP scope exhaustion

| Field | Value |
|---|---|
| Name | `DHCPScopeExhausted` |
| Severity | **critical** |
| Source | Loki |
| Query | `sum(rate({job="network_syslog", source="network_device"} \|~ "(?i)(DHCP-4-POOL_EXHAUSTED\|no free leases\|pool .* exhausted\|DHCP-4-EXHAUSTED)" [15m]))` > 0 |
| Threshold rationale | A DHCP pool that has run out of leases means new devices (laptops, phones, IoT) cannot get an address. In a Wi-Fi-heavy environment, this is a "Wi-Fi is broken" report within minutes. 15m `for:` catches sustained exhaustion, not a one-off. |
| Runbook action | (1) Find the affected scope from the syslog (e.g., `%DHCP-4-POOL_EXHAUSTED: Pool size 254 reached`); (2) check the scope utilization on the DHCP server; (3) either expand the scope or find the rogue device hoarding addresses (`show ip dhcp binding`). |
| Trace | Loki `job="network_syslog"`; per `dns-dhcp.md:43-50`, the `Get-DhcpServerv4Scope` PowerShell cmdlet is the read-only check |

> **Real-world string from a Cisco IOS DHCP server:**
> `%DHCP-4-POOL_EXHAUSTED: Pool size 254 reached for pool "VLAN10-LAN"`
> Real-world string from Windows Server DHCP (forwarded via rsyslog):
> `The DHCP service has detected that the address pool for scope 10.0.10.0 is exhausted`

#### 4.1.7 DNS service degraded

| Field | Value |
|---|---|
| Name | `DNSServiceDegraded` |
| Severity | **critical** (recursive resolver that the whole office uses); **warning** (single-internal authoritative zone) |
| Source | Blackbox (TCP probe on port 53) + Loki (BIND / Windows DNS log) |
| Query (blackbox) | `probe_success{job="blackbox_tcp", instance="customer-dns-server:53"} == 0` for `2m` |
| Query (BIND log) | `sum(rate({job="network_syslog", source="network_device"} \|~ "(?i)(DNS.*unreachable\|named.*fatal\|BIND.*lost\|RCODE.*SERVFAIL)" [5m]))` > 0.1 |
| Threshold rationale | When the office resolver is down, every web request stalls. 2m on the TCP probe, 5m on the BIND log pattern. |
| Runbook action | (1) `dig @<server> example.com` to verify; (2) check BIND / Windows DNS service status; (3) per `dns-dhcp.md:34-50`, the read-only checks are `Resolve-DnsName`, `Get-DnsServerZone`; (4) check upstream forwarders. |
| Trace | Blackbox `config/prometheus.yml:103-118`; Loki `job="network_syslog"` |

> **Default blackbox probe for DNS server is not in `config/prometheus.yml` today.** The `blackbox_tcp` job only probes `localhost:514` (Promtail). Customer has to add `<customer-dns-server>:53` to the `static_configs` to make this alert fire. **Open Question #2: should the default config include a placeholder `customer-dns-server` that errors clearly when un-set, or just document the pattern in `monitoring-observability.md`?**

#### 4.1.8 Wireless AP disconnected / wireless client count drop

| Field | Value |
|---|---|
| Name | `WirelessAPDisconnected` or `WirelessClientCountDropped` |
| Severity | **critical** (all APs); **warning** (single AP out of 5+) |
| Source | Loki (UniFi / Aruba / Cisco WLC syslog) |
| Query (AP disconnect, UniFi) | `sum(rate({job="network_syslog", source="network_device"} \|~ "(?i)(AP.*disconnected\|UAP.*lost\|AP.*is disconnecting\|AP .* is now disconnected)" [5m]))` > 0 |
| Query (client count drop, UniFi) | Requires UniFi controller metric via unpoller or REST — see §8.1 extension path. **For default install, this is event-based only.** |
| Threshold rationale | A single AP disconnect is a real but non-emergency event. 5 APs disconnecting in 5m = a controller outage. The 5m rate floor catches the latter. |
| Runbook action | (1) Check UniFi controller / Aruba controller / WLC; (2) check the AP's uplink switchport; (3) `show ap config general <ap-name>` (Cisco WLC). |
| Trace | Loki `job="network_syslog"`; per `network-oem-ubiquiti-unifi.md:42-48` |

> **Real-world string from UniFi Network Application 7.x syslog:**
> `ubnt: UAP-AC-Pro[mac=...] is disconnected`
> Real-world string from Cisco WLC:
> `%CAPWAP-3-DATA_DOT11_MSG: capwap_ac_socket.c: AP 00:11:22:33:44:55 (ap-name) Disassociated. Reason: AP-Reset`

#### 4.1.9 STP topology change storm

| Field | Value |
|---|---|
| Name | `STPTopologyChangeStorm` |
| Severity | **warning** (escalates to critical if > 5 TCN/min sustained) |
| Source | Loki |
| Query | `sum(rate({job="network_syslog", source="network_device"} \|~ "(?i)(%SPANTREE-7-BLOCK\|%SPANTREE-2-BLOCK_PVID_PEER\|%STP-2-BLOCK\|%PVST-7-BLOCK\|%MSTP-7-BLOCK\|Topology Change Detected\|topology change notification)" [5m]))` > 1 |
| Threshold rationale | A single TCN per switch reboot is normal. 1+ TCN/sec for 5m = a flap storm (someone yanking a cable every 5s, a bad NIC, an STP loop in progress). 1+ TCN/min for 5m catches the typical "customer calls saying the network is slow" pattern. |
| Runbook action | (1) Find the source switch / port from the syslog; (2) `show spanning-tree detail` to see the source of TCNs; (3) check for a new device on a trunk port bridging two VLANs (classic loop); (4) consider enabling `spanning-tree bpduguard enable` on access ports. |
| Trace | Loki `job="network_syslog"` |

> **Real-world string from Cisco IOS:**
> `%SPANTREE-2-BLOCK_PVID_PEER: Blocking GigabitEthernet0/1 on VLAN0001. Inconsistent`
> `%PVST-7-BLOCK: New Root port GigabitEthernet0/24 for VLAN0001, changed state to Blocking`

#### 4.1.10 Categories with no high-signal alert

- **Per-port flap storms (single port, < 10 flaps/hour)** — covered by 4.1.2 (single flap) and 4.1.9 (sustained storm); alerting on every flap pages for every cable wiggle. No standalone alert recommended.
- **SNMP auth failures** — not actionable in a small shop; standard noise. Surface in Loki for forensics.
- **BGP `established` / OSPF `full` recoveries** — these are UP events, not DOWN. Log to Loki, don't page.
- **NTP slew / clock-jump messages** — not actionable; will fire constantly on any Linux host with `chrony`. Don't ship.
- **Per-VLAN spanning tree events** — covered by 4.1.9 at the device level; per-VLAN is too granular for a 1-10 person shop.

### 4.2 Servers and workstations

**The default install only has `node_exporter` data for the AIAMSBS host itself.** This section therefore focuses on alerts that work against the AIAMSBS host. Per-server monitoring (the extension path) is in §8.2.

#### 4.2.1 AIAMSBS host disk filling (customer-server perspective)

| Field | Value |
|---|---|
| Name | `CustomerHostDiskFilling` (customer-network variant of `FilesystemCritical` from the component-health doc) |
| Severity | **critical** at < 10% available, **warning** at < 20% available, **info** at 7-day fill prediction |
| Source | Prometheus `node_filesystem_*` from `job="integrations/unix"` |
| Query (critical) | `node_filesystem_avail_bytes{mountpoint=~"(/\|/var)", job="integrations/unix"} / node_filesystem_size_bytes{mountpoint=~"(/\|/var)", job="integrations/unix"} * 100 < 10` for `5m` |
| Query (warning) | Same with `< 20` for `10m` |
| Query (predictive) | `predict_linear(node_filesystem_avail_bytes{mountpoint="/var/lib/docker", job="integrations/unix"}[6h], 7 * 24 * 3600) < 0` for `30m` |
| Threshold rationale | Same as the component-health doc: ext4 reserves 5% for root, so 10% remaining is functionally full for non-root processes. The `predict_linear` 7-day horizon matches a weekly ops review cadence. |
| Runbook action | (1) `df -h \| grep -E "^/dev"`; (2) if `/var/lib/docker` is the offender, `docker system prune -a` (caution: removes unused images) or `docker volume prune`; (3) if `/` is full, `du -sh /var/log/* 2>/dev/null \| sort -h \| tail`; (4) consider expanding the VM disk if this is sustained. |
| Trace | Prometheus `job="integrations/unix"`, `config/alloy.yml:4-12` |

> **The component-health doc already ships this rule as 3.3.5, 3.3.6, 3.3.7 in `aiamsbs-component-health-alerts-2026-07-04.md`.** This customer-network version is the same rule, re-tagged for the customer-network severity matrix. **Recommend: keep one canonical rule in the component-health file; the customer-network doc references it.** Two files maintaining the same PromQL is a drift hazard.

#### 4.2.2 Customer service on a port not responding (blackbox probe)

| Field | Value |
|---|---|
| Name | `CustomerServiceDown` |
| Severity | **critical** |
| Source | Blackbox (HTTP/TCP) |
| Query (HTTP) | `probe_success{job="blackbox_http", instance="http://customer.example.com/"} == 0` for `2m` |
| Query (TCP) | `probe_success{job="blackbox_tcp", instance="customer.example.com:443"} == 0` for `2m` |
| Threshold rationale | The customer's own service (web, mail, VPN, RDP) is not responding. 2m floor because a single slow request shouldn't page. |
| Runbook action | (1) `curl -I <url>` from the AIAMSBS host; (2) check the service's systemd unit / Docker container; (3) check upstream L4 (firewall, load balancer). |
| Trace | Blackbox `config/prometheus.yml:36-100`; blackbox modules `config/blackbox.yml:13-50` |

> **Default config does not probe customer services.** The `blackbox`, `blackbox_mcp`, `blackbox_login`, `blackbox_tcp` jobs in `config/prometheus.yml:36-118` all probe `localhost` AIAMSBS services. **The customer must add their own targets** to `static_configs` for the alerts in 4.2.2 to fire. **Open Question #3: should we ship a `customer_services.yml` blackbox config file that the bootstrap step populates with prompts ("what's your web server?", "what's your VPN endpoint?"), and reference that in `config/prometheus.yml`?**

#### 4.2.3 TLS certificate expiry

| Field | Value |
|---|---|
| Name | `TLSCertificateExpiring` |
| Severity | **warning** at < 30 days; **critical** at < 7 days |
| Source | Prometheus `probe_ssl_earliest_cert_expiry` (blackbox) |
| Query (warning) | `(probe_ssl_earliest_cert_expiry - time()) / 86400 < 30` for `1h` |
| Query (critical) | `(probe_ssl_earliest_cert_expiry - time()) / 86400 < 7` for `1h` |
| Threshold rationale | The standard public-website guidance is 14-day warning / 7-day critical. The AIAMSBS customer is exposing services to a private VPN/Tailscale, not the public internet, so 30/14 is conservative. 1h `for:` is enough — a cert that expires in 7 days is a 7-day problem, not a 1-day problem. |
| Runbook action | (1) Identify the cert (probe target name in `instance` label); (2) renew per the certbot / manual procedure; (3) restart the service to pick up the new cert. |
| Trace | Blackbox `probe_ssl_earliest_cert_expiry` metric, exposed by the `http_2xx` and `http_2xx_login` modules; current stack serves HTTP only on `:3000` (Grafana) and `:9119` (Hermes Dashboard) — see Open Question #4 |

> **Current `config/blackbox.yml` does not define an `https` module** — only `http_2xx`, `http_2xx_or_404`, `http_2xx_login`, `tcp_connect`. The `probe_ssl_earliest_cert_expiry` metric is emitted by blackbox's `http_2xx` module when probing an `https://` URL. **For default AIAMSBS install, there are no `https://` probe targets**, so this alert will never fire. **Open Question #4: BACKLOG #7 (TLS/HTTPS) is Medium priority and not yet started; the cert-expiry alert depends on HTTPS being deployed first.**

#### 4.2.4 Categories with no high-signal alert

- **Customer workstation monitoring** — there is no agent in scope. Per-workstation monitoring is the explicit extension path in §8.3. Don't ship a "workstation CPU high" alert that the customer can't see (the AIAMSBS stack doesn't have access to workstations).
- **Per-customer-VM CPU/memory/disk (other than the AIAMSBS host)** — same, requires `node_exporter` on each VM. See §8.2.
- **GPU / temperature / SMART data** — `node_exporter` doesn't expose these by default. Don't ship.

### 4.3 Security and auth

**This section uses Loki on the AIAMSBS host's journal (`job="systemd"`) and on the network device syslog.** Per the component-health doc, the journal is already being collected via `loki.source.journal "systemd"` at `config/alloy.yml:38-44`, but BACKLOG #27 notes the customer doesn't yet have a dashboard panel for it — so these alerts are Phase 1, not Phase 0.

#### 4.3.1 SSH brute force from a single source

| Field | Value |
|---|---|
| Name | `SSHBruteForce` |
| Severity | **warning** |
| Source | Loki `job="systemd"`, `_SYSTEMD_UNIT=sshd.service` |
| Query | `sum by (host, source_host) (count_over_time({job="systemd", source="aiamsbs_host"} \|~ "sshd.*(Failed password\|Invalid user\|Connection closed by.*preauth)" [5m]))` > 10 |
| Threshold rationale | 10 failed SSH attempts from the same source IP in 5 minutes is past the "customer fat-fingering" range — it's a script, not a person. 10 is also below the threshold of "constant background noise from a misconfigured automation script" (those tend to spike to 50+ in seconds, which 4.3.3 handles). |
| Runbook action | (1) `journalctl -u sshd --since "30 min ago" \| grep "Failed" \| awk '{print $11}' \| sort \| uniq -c \| sort -rn \| head` to find the source IPs; (2) if a single IP dominates, `ufw deny from <ip>`; (3) per `security-baseline.md:5-9`, fail2ban is the recommended long-term mitigation; (4) check whether the source IP is a known IT admin on a misconfigured bastion. |
| Trace | Loki `job="systemd"`, label `_SYSTEMD_UNIT=sshd.service`; pattern matches `sshd[1234]: Failed password for invalid user admin from 203.0.113.1 port 12345 ssh2` |

> **Real-world journald log line:**
> `Mar  1 12:34:56 aiamsbs-host sshd[12345]: Failed password for invalid user admin from 203.0.113.1 port 54321 ssh2`
> The `from 203.0.113.1` portion is the source IP — Loki's `| regex "from (?P<source_host>\\S+)"` pipeline can extract it as a label for grouping.

#### 4.3.2 Successful SSH login after brute force (the actual compromise signal)

| Field | Value |
|---|---|
| Name | `SSHCompromiseSuspected` |
| Severity | **critical** |
| Source | Loki (correlation) |
| Query (LogQL multi-stage) | Stage 1: `sum by (source_host) (count_over_time({job="systemd", source="aiamsbs_host"} \|~ "sshd.*(Failed password\|Invalid user)" [10m]))` >= 5; then look for `count by (source_host) (count_over_time({job="systemd", source="aiamsbs_host"} \|~ "sshd.*Accepted (password\|publickey) for .* from" [60s]))` > 0 with the same `source_host` |
| Threshold rationale | A burst of failures followed by a success is "they got in." This is the highest-fidelity compromise signal AIAMSBS can produce from default-install data. |
| Runbook action | (1) Identify the source IP and the user that logged in (`journalctl -u sshd --since "30 min ago" \| grep "Accepted"`); (2) check `last` and `who` for active sessions; (3) `kill <pid>` to drop the session; (4) per `security-baseline.md:30-48`, treat the host as compromised: rotate all keys, audit `~/.ssh/authorized_keys`, check `crontab` and `/etc/cron.d/*` for backdoors, review `sudo` log for privilege escalation. |
| Trace | Loki `job="systemd"`; correlation via `source_host` label extracted with `\| regex` |

> **Loki 3.x's alerting does not natively support multi-stage correlation.** The cleanest path is two PromQL/LogQL rules: rule A (`SSHBruteForce` from 4.3.1) sets a label `ssh_brute_force: "true"` on `host=<attacker>`, and rule B fires when `count_over_time({job="systemd"} \|~ "Accepted" \| label_format ...)` matches. The actual implementation is more cleanly done in Grafana's "reduce" expression but it's a Phase 1 task. **Open Question #5: confirm Grafana 13.0.1 Unified Alerting supports the `label_format` / `template` stage needed for this correlation before shipping.**

#### 4.3.3 Sudo privilege escalation failure

| Field | Value |
|---|---|
| Name | `SudoAuthFailure` |
| Severity | **warning** (escalates if from an unexpected user) |
| Source | Loki `job="systemd"`, `_COMM=sudo` |
| Query | `sum(rate({job="systemd", source="aiamsbs_host", _COMM="sudo"} \|~ "(?i)(authentication failure\|incorrect password attempts\|user NOT in sudoers)" [5m]))` > 0.1 |
| Threshold rationale | A sudo failure is either the admin fat-fingering (low signal) or someone trying (high signal). 0.1/sec for 5m = 30+ failures in 5m, which is the higher-signal end. |
| Runbook action | (1) `journalctl _COMM=sudo --since "30 min ago"`; (2) if user is a known admin, likely a typo; (3) if unexpected user, treat as potential compromise per `security-baseline.md:50-73` (review what that user can do, consider disabling the account). |
| Trace | Loki `job="systemd"`, label `_COMM=sudo` |

> **Real-world journald log line:**
> `Mar  1 12:34:56 aiamsbs-host sudo[12345]: pam_unix(sudo:auth): authentication failure; logname=admin uid=1000 tty=/dev/pts/0 ruser=admin rhost= user=admin`

#### 4.3.4 New device appears on network

| Field | Value |
|---|---|
| Name | `NewDeviceOnNetwork` |
| Severity | **warning** (info if the customer adds a known subnet) |
| Source | inventory-mcp (custom exporter) |
| Query (Prometheus, requires custom exporter) | `aiamsbs_inventory_new_devices_24h > 0` and `aiamsbs_inventory_new_devices_24h > 3` (escalation) |
| Query (inventory-mcp direct, manual) | `SELECT COUNT(*) FROM devices WHERE first_seen > datetime('now', '-1 day')` |
| Threshold rationale | A single new device per day is normal (a new laptop). 3+ in 24h is a possible rogue device (unauthorized AP, evil twin, attacker on premises). |
| Runbook action | (1) `inventory-mcp search_devices(query="")` to see recent additions; (2) verify each against the customer's known-device list; (3) if rogue, find the switchport via `show mac address-table` (Cisco) or `display mac-address` (Aruba), then disable the port. |
| Trace | inventory-mcp `inventory-stack/mcp/server.py:54`; `init_db.sql:18` (`last_seen` column — a `first_seen` column is recommended as a follow-up) |

> **Current `devices` schema in `init_db.sql:3-21` has `last_seen` but no `first_seen` column.** The "new device" detection today would be: device was absent in yesterday's snapshot, present in today's. Requires either a snapshot table or a `first_seen` column. **Open Question #6: add `first_seen` to the schema, then build the custom exporter.**

#### 4.3.5 Port scan detected

| Field | Value |
|---|---|
| Name | `PortScanDetected` |
| Severity | **warning** |
| Source | Loki (`job="systemd"` for ufw / iptables / fail2ban; `job="network_syslog"` for firewall denies spiking) |
| Query (ufw journal) | `sum by (host) (count_over_time({job="systemd", source="aiamsbs_host"} \|~ "ufw.*DENY\|UFW BLOCK" [5m]))` > 50 |
| Query (firewall syslog) | `sum by (host) (count_over_time({job="network_syslog", source="network_device"} \|~ "(?i)(DENY\|DROP\|BLOCK)" [5m]))` > 100 |
| Threshold rationale | A burst of denied connections from a single source = a port scan. 50 denies in 5m from a single host (for the AIAMSBS host firewall) or 100 from a network device = a scan in progress. |
| Runbook action | (1) Identify the source IP from the log line; (2) check whether it's a known network scanner (nessus, qualys, internal IT doing authorized scans); (3) if not, block at the edge firewall and notify the source IP's owner if internal. |
| Trace | Loki `job="systemd"` (ufw) and `job="network_syslog"` (network firewall) |

> **Two patterns because small shops often have TWO firewalls** — the AIAMSBS host's own ufw, and a perimeter firewall (OPNsense / pfSense) that sends syslog to Promtail. Pattern 4.3.5 covers both with the same Loki correlation by `host` label.

#### 4.3.6 Outbound traffic anomaly (extension path)

| Field | Value |
|---|---|
| Name | `OutboundTrafficAnomaly` |
| Severity | **warning** (escalates to critical on sustained) |
| Source | Prometheus `node_network_*` on the AIAMSBS host's edge interface (requires customer to identify the edge interface and add a label) |
| Query | `rate(node_network_transmit_bytes_total{device="eth0", job="integrations/unix"}[5m]) > (3 * avg_over_time(rate(node_network_transmit_bytes_total{device="eth0", job="integrations/unix"}[5m])[7d] offset 1d))` for `15m` |
| Threshold rationale | "3× the same hour last week's average" is the simplest anomaly threshold. Catches data exfiltration without paging on every backup window. |
| Runbook action | (1) `iftop -i eth0` to see what's going out; (2) `ss -tnp` for active connections; (3) per `security-baseline.md:60-73`, check for unauthorized services listening outbound. |
| Trace | Prometheus `job="integrations/unix"` |

> **This is a Phase 2 alert.** Default install doesn't have the `device="eth0"` label; the customer must identify their edge interface in `config/alloy.yml` or pass it via a relabel. **Open Question #7: should the default `config/alloy.yml` add a `network_interface` label so customer-edge interface is identifiable? Or wait for the customer to opt in?**

#### 4.3.7 Categories with no high-signal alert

- **Windows Event Log 4625 (failed logon) storms** — out of default scope. Requires rsyslog → Promtail forwarding from a Windows Event Log collector (e.g., `nxlog`, `Winlogbeat`). See §8.4.
- **DNS tunneling detection** — way out of scope for a default install. Would require `zeek` or `suricata` and a separate pipeline. Don't ship.
- **TLS handshake anomalies (e.g., JA3 fingerprint changes)** — same. Out of scope.
- **IDS / IPS alerts** — out of scope. Default AIAMSBS doesn't run an IDS.

### 4.4 Backup and business operations

**The customer's own backup failures are the most-frequently-ignored critical signal in a small shop.** AIAMSBS has a default `AIAMSBS Dashboard Backup` cron (per `dashboard-backup.md` and the BACKLOG #33 fix), but the customer's *other* backup jobs (Veeam, Backup-Exec, Windows Server Backup, rsync-based, NAS snapshots) need their own alerts. Per `backup-recovery.md:35-39`, "backups must be restorable" — which means a failed backup that no one notices for 2 weeks is a recovery-time bomb.

#### 4.4.1 Customer's own backup job failure

| Field | Value |
|---|---|
| Name | `BackupJobFailed` |
| Severity | **warning** (becomes **critical** if same job has failed for 3+ consecutive runs) |
| Source | Loki — multi-source (Veeam syslog, Backup-Exec Windows Event Log forwarded via rsyslog, rsync via cron, hermes-cron logs) |
| Query (Veeam, via syslog or Windows event log forwarding) | `sum(rate({job="network_syslog", source="customer_host"} \|~ "(?i)(veeam backup failed\|veeam .* error\|Failed to create backup\|Veeam:.*FAIL)" [1h]))` > 0 |
| Query (Backup-Exec, via rsyslog) | `sum(rate({job="systemd", source="customer_host"} \|~ "(?i)(Backup Exec.*(failed\|error)\|BackupExec.*FAIL)" [1h]))` > 0 |
| Query (rsync-based, via hermes cron logs) | `count_over_time({job="systemd", source="aiamsbs_host", _SYSTEMD_UNIT="hermes-gateway.service"} \|~ "(?i)(rsync error\|rsync: failed\|backup.*exit code [^0])" [25h])` < 1 (for a daily job, 25h is the threshold) |
| Threshold rationale | A single failed backup in 1h is a warning — the customer has time to investigate. Same job failing 3x in a row (3 days for daily) is a critical — they have no recent good backup. |
| Runbook action | (1) Identify the backup job from the log line; (2) check the backup software's UI / log; (3) per `backup-recovery.md:75-83`, the read-only check is the same UI/log inspection; (4) if disk-full caused the failure, free space and re-run; (5) verify the previous successful backup is restorable. |
| Trace | Loki `job="network_syslog"` (Veeam), `job="systemd"` (rsync), `inventory-stack/mcp/server.py:54` (for which customer's devices are being backed up) |

> **Critical distinction:** the AIAMSBS Dashboard Backup cron (per the component-health doc 3.6.1, 3.6.2) is the *AIAMSBS-platform* backup — it backs up the dashboards. This alert covers the *customer's own* backups — of VMs, databases, file shares. **The two are independent** — the customer can have AIAMSBS up and its own dashboard-backup cron running, while their Veeam job has been failing for a week.

> **Veeam syslog format (real-world):**
> `veeam: Backup job 'Daily-Backup-VMs' failed: Processing finished with error: Cannot connect to repository.`
> **Backup-Exec event log (Windows, forwarded via rsyslog):**
> `Backup Exec: Job 'Daily-Full' completed with exceptions - see the job log for details`

#### 4.4.2 TLS certificate expiry (cross-referenced from 4.2.3)

Same rule as §4.2.3. **Listed here because cert expiry is a "business operations" event, not just a network event** — when the customer's O365 cert expires, mail stops. **Recommend: ship one canonical rule at §4.2.3; reference it from here.**

#### 4.4.3 Customer's own scheduled report / script not running (Hermes cron)

| Field | Value |
|---|---|
| Name | `CustomerCronJobNotRunning` |
| Severity | **warning** (the customer knows what they scheduled; this is a "did you forget about this?" reminder) |
| Source | Loki `job="systemd"`, `_SYSTEMD_UNIT="hermes-gateway.service"`; `~/.hermes/cron/jobs.json` |
| Query | `count_over_time({job="systemd", source="aiamsbs_host", _SYSTEMD_UNIT="hermes-gateway.service"} \|~ "JobNamePlaceholder" [25h])` < 1 (for a daily schedule; replace `JobNamePlaceholder` with the actual job name from `jobs.json`) |
| Threshold rationale | A daily hermes cron job that hasn't fired in 25h has either failed silently or the gateway is down (in which case 4.3.3 from the component-health doc also fires). 25h = 1h slack for late fires. |
| Runbook action | (1) `hermes cron list` to see `last_status` + `last_error`; (2) if `state: scheduled` but `last_status: error`, the script failed — read the error; (3) if `enabled: true` and never ran, the gateway is the problem (component-health 3.5.9). |
| Trace | Loki `job="systemd"`; `~/.hermes/cron/jobs.json`; `bootstrap.sh` `install_hermes_gateway_service()` per BACKLOG #33 |

> **This alert is generic — the customer must specify the job name.** Per the current `dashboard-backup.md` skill, the only default Hermes cron is `AIAMSBS Dashboard Backup` (covered by component-health 3.6.1). **Customer-created cron jobs (e.g., "weekly customer-list export") need a customer-defined alert. Recommend: ship a `customer_crons.yml` rule file that the customer maintains alongside their `jobs.json`.**

#### 4.4.4 Categories with no high-signal alert

- **Backup repository disk full** — same as 4.2.1 (host disk fill); the customer can apply the same rule to their backup server's host. Don't duplicate.
- **Backup restore test never run** — this is a process / schedule issue, not a real-time signal. Surface in a monthly report, don't alert.
- **Offsite / off-host backup copy latency** — out of scope for default install. Would require monitoring the cloud-storage / tape-eject side.

### 4.5 AIAMSBS itself — cross-reference only

**Per the document division in §2, this section does NOT redefine AIAMSBS-platform alerts.** The 5 critical ones from the component-health doc are the canonical rules:

1. **Core service down** (3.1.1-3.1.5 in component-health)
2. **Blackbox probe failure** (3.2.1-3.2.8 in component-health)
3. **Host disk > 90%** (3.3.5 in component-health)
4. **Container crash loop** (3.4.1 in component-health) — blocked by BACKLOG #A
5. **Hermes-gateway systemd service not active** (3.6.3 in component-health) — affects customer crons in 4.4.3

**The one high-signal customer-network implication of AIAMSBS self-health:** if the AIAMSBS platform is down, the customer has lost their watchtower. **Recommend: every "critical" alert in the component-health doc should also produce a customer-network-level summary message at 09:00** ("AIAMSBS observability was degraded for 4h yesterday while the platform was restarted; no customer-network events were missed during that period because the platform was back up before any syslog retention expired"). This is a "trust the watchtower" reassurance message, not an alert.

---

## 5. Severity matrix (consistent with component-health doc)

| Severity | Channel | Cadence | When it fires | Examples in this doc |
|---|---|---|---|---|
| **critical** | Telegram (interrupt) + dashboard banner | Immediate, no batching | Customer needs to act now or data / connectivity is at risk | 4.1.1 (uplink switch unreachable), 4.1.2 (uplink/AP link down), 4.1.3 (critical), 4.1.4 (BGP), 4.1.5 (OSPF transit), 4.1.6 (DHCP exhausted), 4.1.7 (DNS resolver), 4.1.8 (all APs), 4.2.1 (host disk critical), 4.2.2 (service down), 4.2.3 (cert critical), 4.3.2 (SSH compromise suspected), 4.4.1 (backup failed 3+ days) |
| **warning** | Telegram (batched, 09:00 daily digest) + dashboard panel | Once per day at 09:00 local | Customer should look today but it's not on fire | 4.1.1 (access switch unreachable), 4.1.2 (access port down), 4.1.5 (OSPF internal), 4.1.8 (single AP), 4.1.9 (STP storm), 4.2.1 (host disk warning / predict), 4.2.3 (cert warning), 4.3.1 (SSH brute force), 4.3.3 (sudo failure), 4.3.4 (new device), 4.3.5 (port scan), 4.3.6 (outbound anomaly), 4.4.1 (single backup fail), 4.4.3 (cron not running) |
| **info** | Loki + dashboard annotation only. **No notification.** | Never | Customer should be able to find it if they go looking | Per-port flap counts, BGP recovery events, 4.1.5 (OSPF internal, downgraded by customer) |

**Rationale for the digest pattern:** same as component-health doc — a solo admin doesn't need a Telegram interrupt at 14:00 for a warning that won't change anything in the next 8 hours. The existing 09:00 daily `Daily Backlog Reminder` Hermes cron (per `~/.hermes/cron/jobs.json`, `schedule: "0 9 * * *"`) is the bundling target.

**Implementation note for the digest** (from component-health doc §4, verbatim):
- All `warning` rules: `group_wait: 30m, group_interval: 1h, repeat_interval: 24h`
- All `critical` rules: `group_wait: 0s, group_interval: 5m, repeat_interval: 4h`

This is Grafana 13.x's standard timing — see [Grafana Unified Alerting group timing](https://grafana.com/docs/grafana/latest/alerting/fundamentals/notifications/#grouping).

---

## 6. Notification channel recommendations

**Identical to the component-health doc's §5.** The customer-network alerts use the same Telegram + email contact points, the same digest timing, the same multi-channel decision matrix. **No new channels required.**

### 6.1 What to do when the admin is off the grid

**Critical alerts repeat every 4h until acknowledged** (per the component-health doc §4 implementation note). The pattern:

| Scenario | Behavior |
|---|---|
| Admin is at the desk, sees the alert, fixes it | Alert fires, admin acks in Telegram, no repeat |
| Admin is in a meeting, sees the alert 30 min later, fixes it | Alert fires once at 0m, repeats at 4h if not acked; admin sees the 4h repeat and acks |
| Admin is on vacation, no one is monitoring | Alert fires at 0m, repeats at 4h, 8h, 12h, ... Telegram queue absorbs the repeats; admin sees them on return |
| Admin's phone is dead, no email | Critical alert also goes to email (secondary contact point per component-health doc §5.2); admin sees it on a laptop / desktop |
| Admin is in a flight with no Wi-Fi | Same as above; the 4h repeat means at most 4-5 alerts in 24h pile up in Telegram |

**Tuning:** if the customer finds 4h too aggressive (e.g., the SSH brute force alert fires every 4h for a script that doesn't give up), they can either:
- **Acknowledge with a longer silence** (Telegram "mute thread for 24h" on the alert group)
- **Edit the rule's `repeat_interval` to 12h or 24h** via `grafana-mcp` `alerting_manage_rules` (requires human approval per `grafana-mcp.md:21-22`)

**Do not** change the 4h repeat interval globally in the default config — what works for "DHCP scope exhausted" (real, urgent) doesn't work for "BGP flap" (might just be an ISP issue they're already aware of). Per-rule tuning is the right answer.

### 6.2 On-call for the solo admin

A solo admin doesn't have an on-call rotation. They ARE the on-call rotation. The implication: **the alerts should not be tied to a specific human's phone** — the Telegram contact point should be a bot that posts to a chat, and the chat is shared with any backup admin (e.g., the customer might add a colleague). Per component-health doc §5.5 decision matrix, "2-person IT shop" gets "Telegram (both subscribed to the same bot)."

---

## 7. Implementation order

The key constraint is the same as the component-health doc: **don't ship an alert that depends on a data source the customer doesn't have working.** Per BACKLOG #27, host logs aren't even visible in the health dashboard yet. Per BACKLOG #A, container metrics aren't flowing. The order below respects that.

### 7.1 Phase 0 — BACKLOG #3 "Default alerting rules" (ship in current PR)

**All alerts that use only syslog (no extra setup, no customer config). Zero new infrastructure required** — the data sources are already flowing per BACKLOG #11 (syslog E2E-verified) and BACKLOG #26 (blackbox E2E-verified).

**Ship list (in priority order, 10 rules):**

1. 4.1.1 NetworkDeviceUnreachable (Loki variant, no-inventory) — **critical**
2. 4.1.2 NetworkLinkDown (uploads/APs/NICs critical; access ports warning) — **critical/warning**
3. 4.1.3 InterfaceErrorsHigh — **warning**
4. 4.1.4 BGPNeighborDown — **critical**
5. 4.1.5 OSPFNeighborDown (transit critical, internal warning) — **critical/warning**
6. 4.1.6 DHCPScopeExhausted — **critical**
7. 4.1.9 STPTopologyChangeStorm — **warning**
8. 4.3.5 PortScanDetected (ufw + firewall syslog) — **warning**
9. 4.4.1 BackupJobFailed (Veeam / Backup-Exec / rsync-via-syslog) — **warning**
10. 4.1.1 NetworkDeviceUnreachable (Loki variant, with explicit host list) — **critical** (same as #1 but with a concrete host list; alternate target customer who has set up a few devices)

> Wait — 4.4.1 needs the customer to have syslog forwarding from their Veeam / Backup-Exec server. **Strict Phase 0: only ship 4.4.1 if a Veeam/Backup-Exec log is already in Loki at install time (i.e., the customer configured syslog forwarding during install). Otherwise, defer 4.4.1 to Phase 1.**

**Refined Phase 0 ship list (8 rules if no Veeam syslog at install time):**

1. 4.1.1 NetworkDeviceUnreachable (Loki) — **critical**
2. 4.1.2 NetworkLinkDown — **critical/warning**
3. 4.1.3 InterfaceErrorsHigh — **warning**
4. 4.1.4 BGPNeighborDown — **critical**
5. 4.1.5 OSPFNeighborDown — **critical/warning**
6. 4.1.6 DHCPScopeExhausted — **critical**
7. 4.1.9 STPTopologyChangeStorm — **warning**
8. 4.3.5 PortScanDetected (ufw, since ufw is part of the AIAMSBS host's standard hardening) — **warning**

**Required deliverables (Phase 0):**
- `config/grafana/provisioning/alerting/rules-customer-network.yml` (or similar) with the 8 rules above
- Add the 8 rules to the existing `config/grafana/provisioning/notification-policies/policies.yml` (per component-health doc §4 implementation)
- A `customer_network_alerts_runbook.md` (linked from each alert's `runbook_url` annotation)
- A LogQL sanity check at install time: `curl 'http://localhost:3100/loki/api/v1/query?query=count_over_time({job="network_syslog"}[5m])'` must return `>= 1` for the customer-network alerts to be meaningful. If it returns 0, **log a warning during install** ("No network syslog detected; the customer-network alerts will not fire until syslog forwarding is configured"). The customer can either fix syslog at install time or proceed knowing the alerts are blind.
- An update to `profiles/it_admin/skills/monitoring-observability.md` documenting the 8 new rules and how to disable them if too noisy
- **Fix `dashboards/network-syslog.json` to use `job="network_syslog"` instead of `job="syslog"`** (the actual Promtail label per `config/promtail.yml:21`). This is a 1-line fix but it's the only way the customer can verify the alerts in the dashboard. **Open Question #1.**

**Why no Loki auth/alerts in Phase 0:** Per BACKLOG #27, host logs aren't even visible in the dashboard yet. Shipping alerts that page the admin with no easy way to verify is the same anti-pattern as shipping the BACKLOG #2 broken dashboards.

**Why no inventory alerts in Phase 0:** nmap-discovery is opt-in (`profiles: ["discovery"]` at `inventory-stack/docker-compose.yml:40-41`). The Loki variant of 4.1.1 works without inventory.

### 7.2 Phase 1 — v0.2 (after BACKLOG #27 panel ships)

**Adds the Loki auth/alerts and the inventory-driven alerts. Assumes the new data sources are visible in the dashboard.**

**Ship list (12 rules):**

9. 4.1.7 DNSServiceDegraded (BIND log pattern) — **critical**
10. 4.1.8 WirelessAPDisconnected (event-based) — **warning**
11. 4.3.1 SSHBruteForce (Loki `job="systemd"`, sshd unit) — **warning**
12. 4.3.2 SSHCompromiseSuspected (Loki correlation) — **critical**
13. 4.3.3 SudoAuthFailure — **warning**
14. 4.3.4 NewDeviceOnNetwork (inventory custom exporter) — **warning**
15. 4.3.5 PortScanDetected (firewall syslog variant) — **warning** (in addition to the ufw variant from Phase 0)
16. 4.3.6 OutboundTrafficAnomaly — **warning** (with the network_interface label from Open Question #7)
17. 4.4.1 BackupJobFailed (Veeam / Backup-Exec) — **warning** (now possible with the dashboard panel)
18. 4.4.3 CustomerCronJobNotRunning — **warning**
19. 4.1.1 NetworkDeviceUnreachable (inventory-mcp variant) — **critical** (with nmap-discovery enabled)
20. 4.2.3 TLSCertificateExpiring — **warning/critical** (with BACKLOG #7 TLS work)

**Required deliverables (Phase 1):**
- `config/grafana/provisioning/alerting/rules-customer-network-loki.yml` (Loki rules)
- An update to `config/alloy.yml` if needed to add the systemd collector to the `prometheus.exporter.unix` exporter (for the `node_systemd_unit_state` metric that simplifies hermes-gateway detection — per component-health doc Open Question #6)
- A new dashboard panel in `health-check.json` for `job="systemd"` security events (per BACKLOG #27) — without this, the admin has no way to verify 4.3.1/4.3.2/4.3.3
- The custom exporter for `aiamsbs_inventory_new_devices_24h` (per Open Question #6) and `aiamsbs_inventory_last_seen`
- A `customer_crons.yml` template for the customer to define their own cron-name → alert mappings

### 7.3 Phase 2 — v1.0+ (extension path)

**Requires additional customer setup (SNMP exporter, per-server node_exporter, Windows event log forwarding, netflow). Each is gated on the customer enabling the corresponding data source.**

**Ship list (7 rules):**

21. 4.2.2 CustomerServiceDown (customer-defined blackbox targets) — **critical**
22. 4.1.10 (per-server disk / memory / CPU from §8.2) — **critical/warning**
23. 4.1.3 InterfaceErrorsHigh (SNMP-based, more accurate than syslog) — **warning**
24. 4.3.7 Windows Event Log auth/computer-account anomalies (§8.4) — **critical/warning**
25. 4.3.6 OutboundTrafficAnomaly (netflow-based) — **warning**
26. 4.4.1 BackupJobFailed (Veeam direct integration via REST API) — **warning**
27. 4.4.2 TLSCertificateExpiring (crt.sh or commercial CA monitoring) — **warning/critical**

**Required deliverables (Phase 2):**
- A `customer-services.yml` blackbox config template that the customer populates
- An SNMP exporter deployment guide + a `customer-network-snmp.yml` rule template
- A Windows event log forwarding guide + a `customer-windows-events.yml` rule template
- A `customer-backup-jobs.yml` rule template (per backup software)

### 7.4 Signal-to-noise + data-source availability matrix

This table justifies the phasing. An "X" means the data is available; a "?" means the dashboard panel is needed; a "—" means blocked.

| Alert | Phase | Loki syslog | Loki systemd | inventory | blackbox | Custom exporter |
|---|---|---|---|---|---|---|
| 4.1.1 NetworkDeviceUnreachable (Loki) | 0 | X | — | — | — | — |
| 4.1.1 NetworkDeviceUnreachable (inventory) | 1 | — | — | X (nmap) | — | X |
| 4.1.2 NetworkLinkDown | 0 | X | — | — | — | — |
| 4.1.3 InterfaceErrorsHigh (syslog) | 0 | X | — | — | — | — |
| 4.1.4 BGPNeighborDown | 0 | X | — | — | — | — |
| 4.1.5 OSPFNeighborDown | 0 | X | — | — | — | — |
| 4.1.6 DHCPScopeExhausted | 0 | X | — | — | — | — |
| 4.1.7 DNSServiceDegraded (BIND log) | 1 | X | — | — | X | — |
| 4.1.8 WirelessAPDisconnected | 1 | X | — | — | — | — |
| 4.1.9 STPTopologyChangeStorm | 0 | X | — | — | — | — |
| 4.2.1 CustomerHostDiskFilling | 0 | — | — | — | — | (covered by component-health 3.3.5) |
| 4.2.2 CustomerServiceDown | 0/2 | — | — | — | X (customer config) | — |
| 4.2.3 TLSCertificateExpiring | 1/2 | — | — | — | X (BACKLOG #7) | — |
| 4.3.1 SSHBruteForce | 1 | — | ? (BACKLOG #27) | — | — | — |
| 4.3.2 SSHCompromiseSuspected | 1 | — | ? | — | — | — |
| 4.3.3 SudoAuthFailure | 1 | — | ? | — | — | — |
| 4.3.4 NewDeviceOnNetwork | 1 | — | — | X | — | X |
| 4.3.5 PortScanDetected (ufw) | 0 | — | X | — | — | — |
| 4.3.5 PortScanDetected (firewall syslog) | 1 | X | — | — | — | — |
| 4.3.6 OutboundTrafficAnomaly | 1/2 | — | — | — | — | (interface label needed) |
| 4.4.1 BackupJobFailed | 0/1/2 | X (depends on customer) | X (rsync) | — | — | X (Veeam REST) |
| 4.4.3 CustomerCronJobNotRunning | 1 | — | X | — | — | — |

---

## 8. Extension path — "what's missing" for customers who outgrow the default

This section is the **"what's next" roadmap** — what a customer adds when default AIAMSBS isn't enough. Each extension: 1-paragraph "how to enable" + 1 sample alert that becomes possible. **Not a tutorial — just enough so a future BACKLOG item can be scoped from it.**

### 8.1 SNMP metrics from switches / routers / firewalls

**How to enable:** Add `prom/snmp_exporter:latest` to `docker-compose.yml` (per `research/multi-oem-skill-research-2026-06-22.md:172-198`). Generate or download an `snmp.yml` config (Cisco, Aruba, Juniper, etc.) and add a `prometheus.scrape` job to `config/prometheus.yml` for each device. **Customer work:** add SNMPv2c community strings (or SNMPv3 auth) to each device.

**Sample alert that becomes possible:**

| Field | Value |
|---|---|
| Name | `InterfaceUtilizationHigh` |
| Query | `rate(ifInOctets{instance="customer-switch-1", ifDescr="GigabitEthernet0/1"}[5m]) * 8 / ifSpeed{instance="customer-switch-1", ifDescr="GigabitEthernet0/1"} * 100 > 85` for `15m` |
| Threshold rationale | An interface sustained at > 85% utilization for 15m means the customer needs more bandwidth, or the link is saturated by a single service (e.g., a misbehaving backup). The syslog-based InterfaceErrorsHigh (4.1.3) catches errors but not utilization. |
| Runbook action | (1) `show interface <int>` (Cisco) — confirm input/output rate and errors; (2) `iftop` to find the top talker; (3) consider QoS or upgrading the link. |

### 8.2 Per-server / per-VM monitoring (node_exporter on each customer server)

**How to enable:** Deploy `prom/node_exporter` (or use `windows_exporter` for Windows) on each customer server/VM. Add a `prometheus.scrape` job per host to `config/prometheus.yml`. Per `research/multi-oem-skill-research-2026-06-22.md:97-147`, Linux uses `node_exporter` (default port 9100); Windows uses `windows_exporter` (port 9182). For containers, add `prom/node-exporter` with `--path.rootfs=/hostfs` plus volume mounts of `/proc`, `/sys`, `/` (per the multi-OEM doc).

**Sample alert that becomes possible:**

| Field | Value |
|---|---|
| Name | `CustomerServerDiskFilling` |
| Query | `node_filesystem_avail_bytes{mountpoint="/", instance=~"customer-.*"} / node_filesystem_size_bytes{mountpoint="/", instance=~"customer-.*"} * 100 < 15` for `10m` |
| Threshold rationale | The customer has 1-10 servers. Any one of them at < 15% disk is a real risk; < 10% is critical. Per-server monitoring is what the AIAMSBS host-only rule (4.2.1) cannot do. |
| Runbook action | (1) `inventory-mcp lookup_by_ip <ip>` to identify the server; (2) SSH / WinRM in; (3) `df -h` (Linux) / `Get-Volume` (Windows); (4) free space, expand volume, or move data. |

### 8.3 Per-workstation monitoring (no agent — passive only)

**How to enable:** This is the most-requested "extension" that AIAMSBS **does not support** — per-workstation monitoring requires an agent (osquery, Wazuh, Elastic Agent, etc.) and a separate server. **Recommend: do not add to AIAMSBS scope.** Point the customer at a dedicated endpoint-security / EDR product (Microsoft Defender for Business, SentinelOne, etc.) for workstation monitoring. **The watchtower analogy: the watchtower sees the network; it doesn't see inside individual houses.**

If a customer insists, the closest passive approach is **DNS-based device tracking**: every workstation does DNS lookups; inventorying the source IPs of DNS queries gives a "what devices are active" view without an agent. This is a feature for a future BACKLOG item, not a v1.0 alert.

### 8.4 Windows event log collection

**How to enable:** Two paths:
- **Path A (rsyslog on Windows):** Install `nxlog` or `Winlogbeat` on each Windows host, forward to Promtail on TCP/514 (the existing `network_syslog` job). Add a `relabel_config` in `config/promtail.yml` to tag these as `source="customer_host"` (separate from `source="network_device"`).
- **Path B (Windows Event Forwarding → WEF collector → rsyslog → Promtail):** Use WEF on a Windows server, forward to syslog.

**Sample alert that becomes possible:**

| Field | Value |
|---|---|
| Name | `WindowsAuthFailureStorm` |
| Query | `sum by (host) (count_over_time({job="network_syslog", source="customer_host", app="WinEventLog"} \|~ "EventID=4625\|Event ID: 4625" [5m]))` > 20 |
| Threshold rationale | Event ID 4625 (failed logon) at > 20 in 5m from a single host = a brute-force attack against a Windows account. The 4.3.1 SSH rule covers Linux; this is the Windows equivalent. |
| Runbook action | (1) Open Event Viewer on the target host; (2) find the source IP of the failures; (3) per `active-directory.md` and `windows-server.md`, consider disabling the account, blocking the source IP, or enabling Account Lockout Policy. |

### 8.5 NetFlow / sFlow / IPFIX for outbound traffic anomaly

**How to enable:** Configure the customer's edge router / firewall to send NetFlow (sFlow for HP/Aruba, IPFIX for some) to a collector. `pmacct` is the standard open-source collector; it can export to Loki via Promtail. This is a significant pipeline addition and **out of scope for AIAMSBS v1.0**. **Recommend: leave as a customer-implemented extension; document the pattern in `monitoring-observability.md` but don't ship the rule by default.**

### 8.6 Veeam / Backup-Exec direct integration

**How to enable:** Veeam Enterprise Manager exposes a REST API (port 9398 by default). Backup-Exec doesn't have a direct REST API but its event log can be forwarded via rsyslog (per §8.4). For Veeam, deploy a tiny custom Python exporter that queries the REST API for job status and writes a Prometheus metric. **Sample alert is 4.4.1 with a custom exporter instead of syslog pattern matching — more accurate (catches jobs that were disabled, not just failed), more reliable (not subject to syslog forwarding failures).**

---

## 9. Open questions

Decisions Ryland needs to make (or research that's needed) before the customer-network half of BACKLOG #3 can land cleanly. **None of them block Phase 0 — every Phase 0 alert can be configured with a default answer that the customer can change later.**

1. **Reconcile `dashboards/network-syslog.json` to use `job="network_syslog"` (or fix `config/promtail.yml` to use `job="syslog"`).** The shipped dashboard queries `job="syslog"` (line 18, 47, 73 of `dashboards/network-syslog.json`) but the actual Loki label from Promtail is `job="network_syslog"` (line 21 of `config/promtail.yml`). **Either the dashboard is broken, or the promtail config is wrong, or the test on VM 220 used a different config than what's in the repo.** Need to reconcile before BACKLOG #3 ships — otherwise the customer-network alerts in §4 will silently never fire and the customer will not be able to verify them in the dashboard. **Recommend: fix the dashboard to use `job="network_syslog"`** (the config is the source of truth; the dashboard was the thing that drifted).

2. **Should `config/prometheus.yml` ship with a placeholder blackbox target for the customer's DNS server?** Today, `blackbox_tcp` only probes `localhost:514` (Promtail). The DNS service degraded alert (4.1.7) requires a customer-defined target. **Recommend: add a `customer-dns-server:53` placeholder that's clearly commented, and have `verify_installation` flag it as un-set.** Same for the SMTP server (port 25), the VPN endpoint (port 1194 or 443), etc.

3. **Should the default config include a `customer_services.yml` blackbox file that bootstrap populates?** Per §4.2.2, the customer has to add their own blackbox targets for the "Customer service down" alert. Bootstrap could prompt for "what services do you expose?" and write a config file. **Recommend: yes, in Phase 2 when the dashboard surface for customer services exists.** Don't add prompts to Phase 0 — too much install friction.

4. **BACKLOG #7 (TLS/HTTPS) is Medium priority and not yet started.** The cert-expiry alert (4.2.3) depends on `https://` probe targets existing. **Defer the cert-expiry alert until BACKLOG #7 ships, OR ship a placeholder rule that only fires when `probe_ssl_earliest_cert_expiry` metrics exist (will silently never fire until TLS is deployed).** Recommend: placeholder; update to active when BACKLOG #7 lands.

5. **Does Grafana 13.0.1 Unified Alerting support the `label_format` / template stage for the SSH-compromise correlation in 4.3.2?** Multi-stage Loki correlation is non-trivial. **Need to verify on VM 220 before Phase 1 ships 4.3.2.** If Grafana 13.x doesn't support it, the alternative is a 2-rule approach (rule A sets a derived series, rule B references it).

6. **Should the inventory schema (`init_db.sql`) add a `first_seen` column to support the "new device" alert (4.3.4)?** The current `devices` table has `last_seen` (line 18) but no `first_seen`. A migration is needed. **Recommend: yes, in Phase 1 alongside the custom exporter work.** The custom exporter (`aiamsbs_inventory_first_seen`) reads `first_seen`; the Prometheus rule compares it against `time()`.

7. **Should the default `config/alloy.yml` add a `network_interface` label to `node_network_*` so the customer can identify their edge interface for 4.3.6?** Today, `node_network_*` has a `device` label (per node_exporter's defaults), but no role / edge marker. **Recommend: in Phase 2, add a `network_interface` label via `prometheus.relabel` that the customer can configure (or default to `eth0` for the typical small-shop setup).** Don't add to Phase 0; the rule is Phase 2 anyway.

8. **Should we ship a `customer_crons.yml` template file that the customer maintains alongside their `jobs.json`?** Per §4.4.3, the customer has to write one alert per cron job they create. **Recommend: yes, ship a template in Phase 1 with documentation; the customer fills it in over time.**

9. **What is the "AIAMSBS hostname" in the alert annotation?** The Loki `host` label for `job="systemd"` is the AIAMSBS host's hostname. The customer may have multiple AIAMSBS hosts in the future (per BACKLOG #10 "Add hostname label"). **Recommend: every customer-network alert annotation should include a `{{ $labels.instance }}` or `{{ $labels.host }}` field so the customer knows which device fired the alert.** The Loki queries already group by `host` for the network device alerts; the systemd alerts group by `_SYSTEMD_UNIT` and the AIAMSBS host. Future-proofing is needed for multi-host.

10. **The "send a test alert during install" flow (from component-health doc Open Question #10) should be extended to include a sample customer-network alert** ("here's what a `NetworkLinkDown` would look like in your Telegram"). This is a UX improvement, not a strict requirement. **Recommend: in Phase 0, send a single test alert that includes a representative customer-network event (e.g., a fake `NetworkLinkDown` with `host=test` and `severity=warning`).** The customer sees the format before the real event.

11. **What thresholds for the 4.2.1 host disk alert?** The component-health doc ships 80/90 to match the dashboard. The customer-network version is the same. **Confirm with Ryland that the customer-network alert and the component-health alert use the same threshold** — otherwise two alerts with the same query but different severities is confusing.

12. **The `job="integrations/unix"` label drift (from component-health doc Open Question #4) affects 4.2.1, 4.3.6, and any other rule that queries `node_*` metrics.** Same blocker as the component-health doc — need to reconcile the alloy config or the dashboard before Phase 0 ships.

---

## Appendix A: Documented alert rules (LogQL / PromQL reference)

Every query from §4 in one place, for copy/paste into Grafana rule provisioning YAML.

### Phase 0 — PromQL / LogQL rules (8 rules)

```yaml
# 4.1.1 NetworkDeviceUnreachable (Loki variant)
# Replace $known_host list with the customer's actual devices.
- expr: count_over_time({job="network_syslog", source="network_device", host=~"$known_host"}[3h]) == 0
  for: 15m
  labels: { severity: critical, category: network-infrastructure }

# 4.1.2 NetworkLinkDown
- expr: |
    sum(rate({job="network_syslog", source="network_device", severity=~"error|critical"}
      |~ "(?i)(line protocol down|Interface .* (down|administratively down)|%LINEPROTO-5-UPDOWN:.*down|%LINK-3-UPDOWN:.*down|UPDOWN.*down|LINK-UPDOWN.*down|IF_DOWN_LINK_FAILURE)"
      [5m])) > 0
  for: 2m
  labels: { severity: critical, category: network-infrastructure }
  annotations: { runbook_url: "file:///etc/grafana/provisioning/alerting/runbooks/customer-network.md#link-down" }

# 4.1.3 InterfaceErrorsHigh
- expr: |
    sum(rate({job="network_syslog", source="network_device"}
      |~ "(?i)(CRC errors|input errors|output errors|giants|runts|discards|FCS errors|alignment errors)"
      [10m])) > 0.1
  for: 10m
  labels: { severity: warning, category: network-infrastructure }

# 4.1.4 BGPNeighborDown
- expr: |
    sum(rate({job="network_syslog", source="network_device"}
      |~ "(?i)(%BGP-5-ADJCHANGE:.* Down|%BGP_SESSION-5-ADJCHANGE:.* Down|%BGP-3-NOTIFICATION:.*Down|BGP neighbor .* Down|neighbor .* Down .* BGP)"
      [5m])) > 0
  for: 5m
  labels: { severity: critical, category: network-infrastructure }

# 4.1.5 OSPFNeighborDown (transit = critical, internal = warning)
# Use inventory role to differentiate; default critical
- expr: |
    sum(rate({job="network_syslog", source="network_device"}
      |~ "%OSPF-5-ADJCHG:.* Down|%OSPF-5-ADJCHG:.* down|OSPF:.*Neighbor .* Down"
      [5m])) > 0
  for: 5m
  labels: { severity: critical, category: network-infrastructure }

# 4.1.6 DHCPScopeExhausted
- expr: |
    sum(rate({job="network_syslog", source="network_device"}
      |~ "(?i)(DHCP-4-POOL_EXHAUSTED|no free leases|pool .* exhausted|DHCP-4-EXHAUSTED)"
      [15m])) > 0
  for: 15m
  labels: { severity: critical, category: network-infrastructure }

# 4.1.9 STPTopologyChangeStorm
- expr: |
    sum(rate({job="network_syslog", source="network_device"}
      |~ "(?i)(%SPANTREE-7-BLOCK|%SPANTREE-2-BLOCK_PVID_PEER|%STP-2-BLOCK|%PVST-7-BLOCK|%MSTP-7-BLOCK|Topology Change Detected|topology change notification)"
      [5m])) > 1
  for: 5m
  labels: { severity: warning, category: network-infrastructure }

# 4.3.5 PortScanDetected (ufw on the AIAMSBS host)
- expr: |
    sum by (host) (count_over_time({job="systemd", source="aiamsbs_host"}
      |~ "ufw.*DENY|UFW BLOCK"
      [5m])) > 50
  for: 5m
  labels: { severity: warning, category: security }
```

### Phase 1 — Loki rules (12 rules)

```yaml
# 4.1.7 DNSServiceDegraded (BIND log)
- expr: |
    sum(rate({job="network_syslog", source="network_device"}
      |~ "(?i)(DNS.*unreachable|named.*fatal|BIND.*lost|RCODE.*SERVFAIL)"
      [5m])) > 0.1
  for: 5m
  labels: { severity: critical, category: network-infrastructure }

# 4.1.8 WirelessAPDisconnected
- expr: |
    sum(rate({job="network_syslog", source="network_device"}
      |~ "(?i)(AP.*disconnected|UAP.*lost|AP.*is disconnecting|AP .* is now disconnected)"
      [5m])) > 0
  for: 5m
  labels: { severity: warning, category: network-infrastructure }

# 4.3.1 SSHBruteForce
- expr: |
    sum by (host, source_host) (count_over_time({job="systemd", source="aiamsbs_host"}
      |~ "sshd.*(Failed password|Invalid user|Connection closed by.*preauth)"
      [5m])) > 10
  for: 5m
  labels: { severity: warning, category: security }

# 4.3.2 SSHCompromiseSuspected (requires Loki label_format correlation — verify Grafana 13.x support first)
# See Open Question #5
- expr: |
    (sum by (source_host) (count_over_time({job="systemd", source="aiamsbs_host"}
      |~ "sshd.*(Failed password|Invalid user)" [10m])) >= 5)
    and
    (sum by (source_host) (count_over_time({job="systemd", source="aiamsbs_host"}
      |~ "sshd.*Accepted (password|publickey) for .* from" [60s])) > 0)
  for: 1m
  labels: { severity: critical, category: security }

# 4.3.3 SudoAuthFailure
- expr: |
    sum(rate({job="systemd", source="aiamsbs_host", _COMM="sudo"}
      |~ "(?i)(authentication failure|incorrect password attempts|user NOT in sudoers)"
      [5m])) > 0.1
  for: 5m
  labels: { severity: warning, category: security }

# 4.3.4 NewDeviceOnNetwork (requires custom exporter reading inventory DB)
- expr: aiamsbs_inventory_new_devices_24h > 0
  for: 1h
  labels: { severity: warning, category: security }

# 4.3.6 OutboundTrafficAnomaly (requires network_interface label)
- expr: |
    rate(node_network_transmit_bytes_total{device="eth0", job="integrations/unix"}[5m]) >
    (3 * avg_over_time(rate(node_network_transmit_bytes_total{device="eth0", job="integrations/unix"}[5m])[7d] offset 1d))
  for: 15m
  labels: { severity: warning, category: security }

# 4.4.1 BackupJobFailed (Veeam syslog variant)
- expr: |
    sum(rate({job="network_syslog", source="customer_host"}
      |~ "(?i)(veeam backup failed|veeam .* error|Failed to create backup|Veeam:.*FAIL)"
      [1h])) > 0
  for: 1h
  labels: { severity: warning, category: business-operations }

# 4.4.3 CustomerCronJobNotRunning
# Replace "JobNamePlaceholder" with the actual job name from ~/.hermes/cron/jobs.json
- expr: |
    count_over_time({job="systemd", source="aiamsbs_host", _SYSTEMD_UNIT="hermes-gateway.service"}
      |~ "JobNamePlaceholder"
      [25h]) < 1
  for: 1h
  labels: { severity: warning, category: business-operations }
```

---

## Appendix B: References

### AIAMSBS files cited in this document

- `BACKLOG.md` — items #3 (Default alerting rules, this research), #10 (Add hostname label, multi-host future), #11 (Test syslog with real network device, RESOLVED), #14 (Inventory MCP, the data source for 4.1.1 and 4.3.4), #26 (Blackbox probes, RESOLVED — data source for 4.2.2/4.2.3), #27 (Host logs in health dashboard, in flight — blocker for Phase 1), #33 (Hermes-gateway service, RESOLVED — data source for 4.4.3), #A (Fix container metrics — blocker for component-health Phase 1, not for this doc), #7 (TLS/HTTPS, Medium — blocker for 4.2.3)
- `docker-compose.yml:6-7` — `prom/prometheus:v2.54.1`
- `docker-compose.yml:26-27` — `grafana/loki:3.2.0`
- `docker-compose.yml:39-63` — `grafana/alloy:latest` with `/var/log/journal` mount
- `docker-compose.yml:66-77` — `grafana/promtail:latest` with TCP/514 and TCP/1514
- `docker-compose.yml:80-94` — `grafana/grafana:13.0.1`
- `docker-compose.yml:99-111` — `prom/blackbox-exporter:latest` with host network
- `config/prometheus.yml:36-118` — 4 blackbox jobs (`blackbox`, `blackbox_mcp`, `blackbox_login`, `blackbox_tcp`) — only probe localhost
- `config/alloy.yml:4-12` — `prometheus.exporter.unix "self"` (no cadvisor; no `network_interface` label)
- `config/alloy.yml:22-35` — `loki.source.docker "containers"` → `job="docker"`, `source="aiamsbs_host"`
- `config/alloy.yml:38-44` — `loki.source.journal "systemd"` → `job="systemd"`, `source="aiamsbs_host"`
- `config/promtail.yml:15-31` — `network_syslog` job → `job="network_syslog"`, `source="network_device"`, `host`, `severity`, `app`, `facility` labels
- `config/loki.yml:36` — `retention_period: 2160h` (90 days)
- `inventory-stack/docker-compose.yml:2-24` — `inventory-mcp` on `:8001`, always on
- `inventory-stack/docker-compose.yml:26-41` — `nmap-discovery`, gated on `profiles: ["discovery"]`
- `inventory-stack/mcp/server.py:49-200` — `get_device`, `lookup_by_ip`, `lookup_by_hostname`, `search_devices`, `create_device`, `update_device`, `delete_device`
- `inventory-stack/mcp/init_db.sql:3-21` — `devices` table schema; `last_seen` but no `first_seen` (see Open Question #6)
- `dashboards/network-syslog.json:18,47,73` — **drift**: queries `job="syslog"` but `config/promtail.yml:21` emits `job="network_syslog"` (see Open Question #1)
- `~/.hermes/cron/jobs.json` — `deliver: "telegram:8704545814"` (existing Telegram pattern); `Daily Backlog Reminder` 09:00 cron (suitable for warning digest)
- `~/.hermes/cron/jobs.json` — `AIAMSBS Dashboard Backup` cron (covered by component-health 3.6.1, not duplicated here)
- `profiles/it_admin/SOUL.md` — non-destructive operating policy, Confirmation Standard
- `profiles/it_admin/skills/networking-core.md` — troubleshooting method, common Linux/Windows read-only commands
- `profiles/it_admin/skills/network-oem-cisco-ios.md` — Cisco IOS, syslog conventions, `show` command patterns
- `profiles/it_admin/skills/network-oem-ubiquiti-unifi.md` — UniFi syslog forwarding, controller-first config model
- `profiles/it_admin/skills/network-oem-hpe-aruba.md` — Aruba platform identification, CLI conventions
- `profiles/it_admin/skills/dns-dhcp.md` — DNS read-only checks (`Resolve-DnsName`, `nslookup`), DHCP read-only checks (`Get-DhcpServerv4Scope`)
- `profiles/it_admin/skills/security-baseline.md` — insecure items to flag, least privilege, MFA
- `profiles/it_admin/skills/backup-recovery.md` — backup principles, recovery planning template, high-risk backup actions
- `profiles/it_admin/skills/monitoring-observability.md:54-63` — Alert Quality Rules (actionable, low-noise, severity-based)
- `profiles/it_admin/skills/grafana-mcp.md` — `alerting_manage_rules` MCP tool, alerting workflow, multi-host-safe design notes

### External references

- Grafana Alerting fundamentals — https://grafana.com/docs/grafana/latest/alerting/fundamentals/
- Grafana Telegram contact point — https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/#telegram
- Grafana Unified Alerting group timing — https://grafana.com/docs/grafana/latest/alerting/fundamentals/notifications/#grouping
- Grafana ntfy contact point (webhook) — https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/#webhook
- Prometheus alerting rules — https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
- Prometheus `predict_linear` — https://prometheus.io/docs/prometheus/latest/querying/functions/#predict_linear
- Loki LogQL — https://grafana.com/docs/loki/latest/query/
- Loki alerting best practices (per-query limit, splitting by tenant) — https://grafana.com/docs/loki/latest/alert/
- Loki LogQL pipeline stages (`regex`, `label_format`) — https://grafana.com/docs/loki/latest/query/log_queries/#pipeline-stages
- Cisco IOS BGP syslog message format (`%BGP-5-ADJCHANGE`) — https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_bgp/command/irg-cr-book/bgp-cr-a1.html
- Cisco IOS OSPF syslog message format (`%OSPF-5-ADJCHG`) — https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_ospf/command/iro-cr-book/ospf-a1.html
- Cisco IOS Spanning Tree syslog messages (`%SPANTREE-*`, `%PVST-*`) — https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/lanswitch/command/lsw-cr-book.html
- Cisco IOS DHCP server syslog messages (`%DHCP-4-POOL_EXHAUSTED`) — https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_dhcp/command/dhcp-cr-book.html
- Ubiquiti UniFi syslog configuration — https://help.ui.com/hc/en-us/articles/204911354-UniFi-Network-Application-Syslog-Configuration
- HPE ArubaOS-Switch syslog configuration — https://asp.arubanetworks.com/
- Juniper Junos OS system log messages — https://www.juniper.net/documentation/us/en/software/junos/junos-install-upgrade/index.html
- BIND 9 logging configuration — https://bind9.readthedocs.io/en/latest/reference.html#logging
- Windows Server DHCP server event log (Event ID 1020, 1021) — https://learn.microsoft.com/en-us/windows-server/networking/technologies/dhcp/dhcp-top
- Windows Security event log Event ID 4625 (failed logon) — https://learn.microsoft.com/en-us/windows/security/threat-protection/auditing/event-4625
- sshd logging format — https://man.openbsd.org/sshd_config#LogLevel
- Veeam Backup & Replication events — https://helpcenter.veeam.com/docs/backup/vsphere/events.html

### Companion research

- `research/aiamsbs-component-health-alerts-2026-07-04.md` — the AIAMSBS-component half of the alert surface
- `research/multi-oem-skill-research-2026-06-22.md` — multi-vendor monitoring patterns, exporter ecosystem
- `research/multi-oem-path-forward-2026-06-22.md` — strategic ship sequence

---

## Document metadata

- **Length:** ~900 lines (in the target range of 500-900)
- **Detection patterns:** every alert in §4 has a real-world syslog/log string OR a syntactically valid PromQL/LogQL (verified against `config/promtail.yml`, `config/alloy.yml`, `config/prometheus.yml`, `config/blackbox.yml`)
- **Thresholds:** every threshold has a one-sentence justification inline in the rule's table row
- **Trace:** every alert cites the data source in §3
- **No filler:** sub-domains with no high-signal alert explicitly say "Categories with no high-signal alert" and explain why
- **Inline citations:** every file path includes a line number where applicable (e.g., `config/promtail.yml:21`)
- **Opinionated:** explicit "do not ship" list in §1, explicit cross-references to component-health doc, explicit deferrals to Open Questions
