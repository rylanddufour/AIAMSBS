# Multi-Host Monitoring Setup

This guide covers what to install and configure on each customer host so it
appears in AIAMSBS's Grafana dashboards alongside the AIAMSBS host itself.
Four scenarios are covered — pick the ones that match your environment:

| On each host... | Install... | So it shows up in... |
|---|---|---|
| Linux | **Grafana Alloy** (single binary, River config) | Metrics: `job="integrations/unix"`; logs: `job="systemd"` (journal) + auth/syslog files. Dashboard: `AIAMSBS Node Exporter (per-host)` |
| Windows | **Grafana Alloy** (single binary, River config, LocalSystem) | Metrics: `job="integrations/windows"`; logs: `job="windows_eventlog"` (Application / System / Security). Dashboard: `AIAMSBS Windows Exporter (per-host)` |
| Network devices (switches, APs) | Nothing — they forward syslog themselves | Promtail on AIAMSBS listens on `:514` (`source="network_device"`). Network gear can't run agents, so syslog stays. |

> **Migration note (BACKLOG #44).** This guide was rewritten 2026-07-19 to describe
> the alloy cutover. The legacy pre-alloy path (Linux: `node_exporter` + `rsyslog`;
> Windows: `windows_exporter` + `NxLog`) is preserved as a **legacy appendix**
> at the bottom of this document — keep those sections only for migrating
> hosts that haven't cut over yet. **New installs use alloy.** Promtail
> `:1514`/`:2514` listeners are decommissioned in BACKLOG #44 step 10 and
> should not be enabled on new installs.

After installing the agent(s), **prompt the AIAMSBS assistant** to register the
host. AIAMSBS ships with empty scrape jobs out of the box — it does not
auto-discover new hosts. See [§6 — Telling AIAMSBS to monitor a new host](#6-telling-aiamsbs-to-monitor-a-new-host) below.

> **Reference target.** All examples use `192.168.0.220` (the AIAMSBS host) as
> the destination. Replace with your AIAMSBS host's IP or DNS name. The
> `<linux-host-ip>` / `<windows-host-ip>` placeholders are your host's
> address.

---

## 1. Port convention

Do not change these without updating `BACKLOG.md`. They are locked in
`config/promtail.yml` and `config/prometheus.yml` and tested in production.

> **Alloy cutover (BACKLOG #44).** Customer hosts no longer need inbound
> scrape ports — alloy pushes via `prometheus.remote_write` to Prometheus
> `:9090` and `loki.write` to Loki `:3100` on the AIAMSBS host. The only
> port that still receives customer traffic is `:514` (network devices).
> `:1514`/`:2514` are listed here for completeness during the cutover
> transition window; they will be decommissioned in BACKLOG #44 step 10.

| Host port | Protocol | AIAMSBS job / Loki source | Use |
|---|---|---|---|
| 514 | TCP+UDP | `network_syslog` / `source=network_device` | Network gear (Cisco, UniFi, Aruba, OPNsense) — **kept** post-cutover |
| (outbound) | HTTPS/HTTP | `integrations/unix` (Prom) / `systemd` (Loki) | Customer Linux hosts via alloy → AIAMSBS Prom `:9090` + Loki `:3100` |
| (outbound) | HTTPS/HTTP | `integrations/windows` (Prom) / `windows_eventlog` (Loki) | Customer Windows hosts via alloy → AIAMSBS Prom `:9090` + Loki `:3100` |
| 1514 | TCP | `customer_host_linux` / `source=customer_host_linux` | **Legacy: pre-alloy rsyslog forwarding.** Kept during the cutover transition window only; not for new installs. Decommissioned in BACKLOG #44 step 10. |
| 2514 | TCP | `customer_host_windows` / `source=customer_host_windows` | **Legacy: pre-alloy NxLog forwarding.** Kept during the cutover transition window only; not for new installs. Decommissioned in BACKLOG #44 step 10. |
| 9100 | TCP | `linux_exporter` (Prometheus) | **Legacy: pre-alloy `node_exporter` scrape.** Replaced by alloy `job="integrations/unix"`. Listed here for the transition window. |
| 9182 | TCP | `windows_exporter` (Prometheus) | **Legacy: pre-alloy `windows_exporter` scrape.** Replaced by alloy `job="integrations/windows"`. Listed here for the transition window. |

---

## 2. Linux: install Grafana Alloy

A single alloy instance replaces both `node_exporter` (metrics) and
`rsyslog` (logs). Metrics and logs come from the same binary — no
separate exporters, no separate syslog forwarder.

**What alloy emits on a Linux customer host:**

| Stream | Source | Destination on AIAMSBS |
|---|---|---|
| Metrics | `prometheus.exporter.unix` (CPU, mem, disk, net, fs, processes, fds) | Prom `:9090`, `job="integrations/unix"`, host label from `sys.env("HOSTNAME")` |
| Logs (journal) | `loki.source.journal "systemd"` | Loki `:3100`, `job="systemd"`, `source="customer_host_linux"`, `host` from `sys.env("HOSTNAME")` |
| Logs (auth/syslog files) | `local.file_match` + `loki.source.file` | Loki `:3100`, `job="systemd"` (or dedicated job per source) |

The River config that drives all three streams is shipped in the AIAMSBS
repo at [`config/alloy/customer-linux.river`](../../config/alloy/customer-linux.river).

### Install alloy (apt or tarball)

Pick one of the two install methods. Tarball is the safer choice if you
need a pinned version; apt is faster and gets auto-upgrades.

**Option A — apt (Debian / Ubuntu):**

```bash
# See https://grafana.com/docs/alloy/latest/setup/install/linux/ for the
# current package URL and signing key.
sudo apt-get install -y apt-transport-https software-properties-common
sudo mkdir -p /etc/apt/keyrings
wget -qO- https://apt.grafana.com/gpg.key | gpg --dearmor | \
  sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | \
  sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update
sudo apt-get install -y alloy
```

**Option B — tarball (pinned version):**

```bash
# Check https://github.com/grafana/alloy/releases for the current version
ALLOY_VERSION="1.5.1"
cd /tmp
curl -L -o alloy.tar.gz \
  "https://github.com/grafana/alloy/releases/download/v${ALLOY_VERSION}/alloy-linux-amd64.zip"
unzip alloy.tar.gz
sudo cp alloy-linux-amd64 /usr/local/bin/alloy
sudo useradd -r -s /usr/sbin/nologin alloy || true
```

### Drop the River config

Copy the AIAMSBS River config to the standard alloy path and substitute
your AIAMSBS host's address:

```bash
# Fetch the canonical customer Linux River config from the AIAMSBS repo
sudo mkdir -p /etc/alloy
sudo curl -fsSL \
  https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/config/alloy/customer-linux.river \
  -o /etc/alloy/config.alloy

# Tell alloy where to push. Two env vars override the defaults baked into
# the River file (which assume the AIAMSBS network is reachable as
# `prometheus:9090` and `loki:3100`).
sudo tee /etc/default/alloy > /dev/null <<'EOF'
ALLOY_REMOTE_WRITE_URL=http://<aiamsbs-host>:9090/api/v1/write
ALLOY_LOKI_URL=http://<aiamsbs-host>:3100/loki/api/v1/push
EOF
```

The River file's `host` label is `sys.env("HOSTNAME")` — make sure
`/etc/hostname` is a meaningful identifier (`app01`, `db-prod-01`, etc.)
so the same name shows up in every Grafana panel.

### systemd service + start

`apt` installs the systemd unit for you. If you used the tarball, drop
one in `/etc/systemd/system/alloy.service`:

```ini
[Unit]
Description=Grafana Alloy
Documentation=https://grafana.com/docs/alloy/
After=network-online.target

[Service]
User=alloy
Group=alloy
EnvironmentFile=/etc/default/alloy
ExecStart=/usr/local/bin/alloy run /etc/alloy/config.alloy --storage.path=/var/lib/alloy/data
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now alloy
sudo systemctl status alloy
```

### Verify locally

```bash
# alloy's own debug endpoint (the running service exposes :12345 by default)
curl -s http://localhost:12345/-/ready
# Expected: ready

# Confirm metrics are being pushed: hit the alloy debug UI at
# http://<host>:12345 and look for the `self` scrape component.
# Confirm the hostname is exposed in the relabel config by looking at
# /etc/alloy/config.alloy's `prometheus.relabel "customer_host"` block.

# On the AIAMSBS host, the metrics should land under job="integrations/unix"
# and logs under job="systemd".
```

### Outbound firewall

Alloy **pushes** to the AIAMSBS host. Allow outbound TCP to Prom `:9090`
and Loki `:3100` from the customer host — no inbound ports need to open
on the customer host itself:

```bash
sudo ufw allow out to <aiamsbs-host> port 9090 proto tcp
sudo ufw allow out to <aiamsbs-host> port 3100 proto tcp
```

### Once alloy is up

Proceed to [§6 — Telling AIAMSBS](#6-telling-aiamsbs-to-monitor-a-new-host)
to register this host's hostname with AIAMSBS (no `static_configs` to
add — alloy remote_writes, AIAMSBS Prom accepts the series under
`job="integrations/unix"` automatically).

---

## 3. Linux logs: handled by alloy (legacy: rsyslog)

**If you installed alloy per §2, skip this section.** Alloy's
`loki.source.journal "systemd"` block reads the systemd journal directly,
and the `local.file_match` block ships `/var/log/auth.log`,
`/var/log/syslog`, `/var/log/messages`, and similar files automatically.
There is no separate syslog forwarder to install.

### Legacy: pre-alloy rsyslog forwarding (BACKLOG #44 step 10 removed this)

This path was used before BACKLOG #44 cutover and is documented for hosts
that have not yet migrated. **Do not enable on new installs.**

`rsyslog` was the default syslog forwarder on most Linux distros
(Ubuntu, RHEL, Debian, CentOS, Alma, Rocky, etc.). It forwarded logs to
the AIAMSBS host on port 1514, which Promtail listened on under the
`customer_host_linux` syslog job.

**TCP (recommended):**

```
# /etc/rsyslog.d/10-aiamsbs.conf — legacy only
*.* @@192.168.0.220:1514
```

`@` is UDP, `@@` is TCP. Use TCP unless you have a specific reason not to
(UDP is fire-and-forget — log loss is acceptable in some cases).

**Apply and remove (during cutover):**

```bash
sudo systemctl restart rsyslog
sudo rm /etc/rsyslog.d/10-aiamsbs.conf
```

The Loki `host` label was set automatically by Promtail from the
`__syslog_message_hostname` field of the syslog header. Post-cutover the
alloy River config does the same via `sys.env("HOSTNAME")` in the relabel
block — make sure `/etc/hostname` is meaningful.

> **Cutover action.** Run `sudo ufw delete allow out to 192.168.0.220 port 1514`
> once alloy is confirmed receiving the same log lines (BACKLOG #44 step 10
> decommission closes the listener on the AIAMSBS side).

---

## 4. Windows: install Grafana Alloy

A single alloy instance replaces both `windows_exporter` (metrics) and
`NxLog` (event logs). Metrics and logs come from the same binary — no
separate exporter, no separate event-log forwarder.

**What alloy emits on a Windows customer host:**

| Stream | Source | Destination on AIAMSBS |
|---|---|---|
| Metrics | `prometheus.exporter.windows` (cpu, memory, logical_disk, net, os, service, system, process) | Prom `:9090`, `job="integrations/windows"`, host label from `sys.env("COMPUTERNAME")` (falls back to `HOSTNAME`) |
| Event logs | `loki.source.windowsevent` × 3 channels (Application, System, Security) | Loki `:3100`, `job="windows_eventlog"`, `source="customer_host_windows"`, `host` from `COMPUTERNAME` |

The River config that drives all four streams is shipped in the AIAMSBS
repo at [`config/alloy/customer-windows.river`](../../config/alloy/customer-windows.river).

> **Service-account requirements.** Alloy must run as **LocalSystem** (or
> an account with equivalent rights). The `loki.source.windowsevent`
> component needs to read the Application / System / Security channels,
> and `prometheus.exporter.windows` needs WMI access to enumerate
> services, disks, and the CPU/memory/network counters. A plain user
> account will fail the event-log reads and most WMI queries. Granting
> `Event Log Readers` group membership is sufficient for the event-log
> side only; metrics still need LocalSystem or an equivalent WMI grant.

### Install alloy (MSI)

The MSI is the canonical Windows install path. Get the current installer
from <https://github.com/grafana/alloy/releases> (look for
`alloy-windows-amd64.msi`).

```powershell
# Run from an elevated PowerShell
msiexec /i alloy-windows-amd64.msi /qn
# Default install path: C:\Program Files\GrafanaLabs\Alloy
```

The installer registers the alloy service under LocalSystem by default,
which is what we want.

### Drop the River config

Copy the AIAMSBS River config to the alloy config path and substitute
your AIAMSBS host's address:

```powershell
# Fetch the canonical customer Windows River config from the AIAMSBS repo
New-Item -ItemType Directory -Force -Path 'C:\Program Files\GrafanaLabs\Alloy\config'
Invoke-WebRequest `
  -Uri 'https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/config/alloy/customer-windows.river' `
  -OutFile 'C:\Program Files\GrafanaLabs\Alloy\config\config.alloy'

# Tell alloy where to push. These env vars override the defaults baked
# into the River file (which assume the AIAMSBS network is reachable as
# `prometheus:9090` and `loki:3100`).
[System.Environment]::SetEnvironmentVariable(
  'ALLOY_REMOTE_WRITE_URL',
  'http://<aiamsbs-host>:9090/api/v1/write',
  [System.EnvironmentVariableTarget]::Machine)
[System.Environment]::SetEnvironmentVariable(
  'ALLOY_LOKI_URL',
  'http://<aiamsbs-host>:3100/loki/api/v1/push',
  [System.EnvironmentVariableTarget]::Machine)
```

The River file's `host` label is `sys.env("COMPUTERNAME")` (with
`HOSTNAME` as fallback) — make sure `$env:COMPUTERNAME` is a meaningful
identifier (`app01`, `fs01`, etc.).

### Restart alloy

```powershell
Restart-Service alloy
Get-Service alloy
# Status should be Running

# Verify the debug endpoint (default port 12345) is responding
(Invoke-WebRequest http://localhost:12345/-/ready).Content
# Expected: ready
```

### Outbound firewall

Alloy **pushes** to the AIAMSBS host. Allow outbound TCP to Prom `:9090`
and Loki `:3100` from the customer host — no inbound ports need to open
on the Windows host itself:

```powershell
New-NetFirewallRule -DisplayName "AIAMSBS alloy to Prom 9090" `
  -Direction Outbound -Protocol TCP -RemotePort 9090 `
  -RemoteAddress <aiamsbs-host> -Action Allow
New-NetFirewallRule -DisplayName "AIAMSBS alloy to Loki 3100" `
  -Direction Outbound -Protocol TCP -RemotePort 3100 `
  -RemoteAddress <aiamsbs-host> -Action Allow
```

> **What replaces the old inbound `:9182` rule.** The previous
> `windows_exporter` install required `New-NetFirewallRule -Direction Inbound
> -LocalPort 9182 ...`. Alloy pulls no inbound port — that rule can be
> deleted post-cutover.

### Once alloy is up

Proceed to [§6 — Telling AIAMSBS](#6-telling-aiamsbs-to-monitor-a-new-host)
to register this host's hostname with AIAMSBS (no `static_configs` to
add — alloy remote_writes, AIAMSBS Prom accepts the series under
`job="integrations/windows"` automatically).

---

## 5. Windows event logs: handled by alloy (legacy: NxLog)

**If you installed alloy per §4, skip this section.** Alloy's three
`loki.source.windowsevent` blocks (one per channel: Application, System,
Security) read directly from the Windows Event Log and forward to Loki.
There is no separate event-log forwarder to install.

### Legacy: pre-alloy NxLog forwarding (BACKLOG #44 step 10 removed this)

This path was used before BACKLOG #44 cutover and is documented for hosts
that have not yet migrated. **Do not enable on new installs.**

`NxLog` Community Edition was the standard open-source log forwarder for
Windows. It read from the Windows Event Log and forwarded to Promtail on
`:2514` (RFC5424 syslog).

**Install NxLog (legacy only):**

1. Download the community edition from
   <https://nxlog.co/products/nxlog-community-edition>.
2. Install with default options.
3. Allow outbound 2514/TCP to the AIAMSBS host:

   ```powershell
   New-NetFirewallRule -DisplayName "AIAMSBS Syslog 2514" `
     -Direction Outbound -Protocol TCP -RemotePort 2514 `
     -RemoteAddress 192.168.0.220 -Action Allow
   ```

**Legacy NxLog config (informational):**

```conf
<Output out>
    Module      om_tcp
    Host        192.168.0.220
    Port        2514
    Exec        to_syslog_ietf();
</Output>
```

**Cutover action.** Remove the NxLog service + config during the cutover
window once alloy is confirmed receiving the same Application / System /
Security events. The Promtail `:2514` listener is decommissioned in
BACKLOG #44 step 10.

---

## 6. Telling AIAMSBS to monitor a new host

After installing the agent(s) on the host, **prompt the AIAMSBS assistant**
to register the host. AIAMSBS ships with empty `linux_exporter` and
`windows_exporter` Prometheus jobs — the assistant adds the `static_configs`
entry and triggers a Prometheus reload.

### Prompt patterns

Pick the prompt that matches what you installed. Replace the IP and the
friendly name (`<host-label>`) with the actual values.

| What was installed | Prompt |
|---|---|
| `node_exporter` on Linux | `add linux_exporter target <linux-host-ip>:9100 with hostname <host-label>` |
| `windows_exporter` on Windows | `add windows_exporter target <windows-host-ip>:9182 with hostname <host-label>` |
| `rsyslog` on Linux | `add customer_host_linux syslog target <linux-host-ip> with hostname <host-label>` (logs-only — no metrics) |
| `NxLog` on Windows | `add customer_host_windows syslog target <windows-host-ip> with hostname <host-label>` (logs-only — no metrics) |
| All four on one host | Run the relevant two metrics and two syslog prompts in sequence |

Examples:

```
add linux_exporter target 192.168.0.51:9100 with hostname app01
add windows_exporter target 192.168.0.50:9182 with hostname fs01
add customer_host_linux syslog target 192.168.0.51 with hostname app01
add customer_host_windows syslog target 192.168.0.50 with hostname fs01
```

The assistant will:

1. Edit `config/prometheus.yml` (or `config/promtail.yml` for syslog
   targets) to add the `static_configs` entry with the friendly `host` label.
2. Trigger a live reload: `curl -X POST http://localhost:9090/-/reload` (or
   `docker restart promtail` for syslog listeners).
3. Verify the new target is `up` in Prometheus' `/api/v1/targets`.
4. Confirm the host appears in the relevant Grafana dashboard's `Host`
   dropdown within 10s (Grafana's provisioning reload interval).

### What the resulting `prometheus.yml` block looks like

For a Linux host with both `node_exporter` and `rsyslog`:

```yaml
  - job_name: 'linux_exporter'
    honor_labels: true
    scrape_interval: 30s
    scrape_timeout: 10s
    static_configs:
      - targets: ['192.168.0.51:9100']
        labels:
          host: app01

  - job_name: 'customer_host_linux'   # in promtail.yml
    syslog:
      listen_address: 0.0.0.0:1514
    static_configs:
      - targets: ['192.168.0.51']
        labels:
          host: app01
```

`honor_labels: true` is critical — it prevents Prometheus from overwriting
your `host` label with the auto-generated `instance` label.

### If you'd rather edit the YAML by hand

Both files are on the AIAMSBS host at:

- `/home/ansible/AIAMSBS/config/prometheus.yml` — for metrics targets
- `/home/ansible/AIAMSBS/config/promtail.yml` — for syslog targets

Add the `static_configs` block under the relevant job, then reload:

```bash
# Metrics: Prometheus has --web.enable-lifecycle, so a live reload works
curl -X POST http://localhost:9090/-/reload

# Syslog: Promtail doesn't support hot-reload, so restart
docker restart promtail
```

After either, Grafana picks up the new host on its next provisioning
refresh (every 10s by default).

---

## 7. Verification checklist

Run this checklist after adding any new host to confirm the full pipeline
is working. **Post-cutover (alloy):** every customer host pushes via
alloy, so all checks use the alloy job labels (`integrations/unix` /
`integrations/windows` for metrics, `systemd` / `windows_eventlog` for
logs). The legacy `linux_exporter` / `windows_exporter` / Promtail
`:1514`/`:2514` checks at the bottom apply only to hosts that have not
yet migrated — new installs skip them.

### Alloy push (Linux metrics — `integrations/unix`)

```bash
# From the AIAMSBS host:
curl -s http://localhost:9090/api/v1/targets | \
  jq '.data.activeTargets[] | select(.job=="integrations/unix") | {host: .labels.host, health: .health, lastError: .lastError}'

# Expected: one entry per customer Linux host, all health="up"
# Note: alloy remote_writes don't show up as Prometheus scrape targets
# (Prom accepts them via the write API). To verify they are landing,
# query the series directly:
curl -s 'http://localhost:9090/api/v1/query?query=up{job="integrations/unix"}' | jq
# Expect: one series per host, value=1
```

### Alloy push (Windows metrics — `integrations/windows`)

```bash
curl -s 'http://localhost:9090/api/v1/query?query=up{job="integrations/windows"}' | jq
# Expect: one series per host, value=1

# For actual Windows-specific metrics:
curl -s 'http://localhost:9090/api/v1/query?query=windows_cpu_time_total{host="fs01"}' | jq
```

### Per-host metrics (Linux)

```bash
# Replace 'app01' with the host label you configured (/etc/hostname on the host).
curl -s 'http://localhost:9090/api/v1/query?query=up{host="app01",job="integrations/unix"}' | jq
```

Expect: a single series with `"value": ["...", "1"]`.

### Per-host metrics (Windows)

```bash
curl -s 'http://localhost:9090/api/v1/query?query=up{host="fs01",job="integrations/windows"}' | jq
```

### Alloy journal / event log push (Linux logs — `systemd`)

```bash
# On the Linux client:
logger -p auth.warning "AIAMSBS-VERIFY: test log line $(date -Iseconds)"

# Then from the AIAMSBS host:
curl -s 'http://localhost:3100/loki/api/v1/query?query={host="app01",job="systemd"}' | jq
```

Expect: a `result` array with at least one entry containing your test
message.

### Alloy windowsevent push (Windows logs — `windows_eventlog`)

```powershell
# On the Windows client (PowerShell):
New-EventLog -LogName Application -Source "AIAMSBS-Verify" -ErrorAction SilentlyContinue
Write-EventLog -LogName Application -Source "AIAMSBS-Verify" -EventId 9999 -EntryType Warning -Message "AIAMSBS-VERIFY: test event $(Get-Date -Format o)"
```

```bash
# From the AIAMSBS host:
curl -s 'http://localhost:3100/loki/api/v1/query?query={host="fs01",job="windows_eventlog"}' | jq
```

### Dashboards

Open Grafana at <http://192.168.0.220:3000>:

- **AIAMSBS Node Exporter (per-host)** (uid `aiamsbs-node-exporter`) — Linux
  hosts. The `Host` dropdown lists every host with alloy pushing metrics
  (the dashboard variable is `label_values(up{job="integrations/unix"}, host)`).
  Selecting a host populates Identity, CPU, Memory, Disk, Network, System,
  and Logs rows.
- **AIAMSBS Windows Exporter (per-host)** (uid `aiamsbs-node-exporter-windows`)
  — Windows hosts. The `Host` dropdown uses
  `label_values(up{job="integrations/windows"}, host)`.
- **AIAMSBS Health** → **Promtail Listeners** row at the bottom. Post-cutover
  the only stat tile that matters is `:514` (network devices). The `:1514`
  and `:2514` tiles are expected to show no traffic once all customer
  hosts are migrated; they're removed entirely in BACKLOG #44 step 10.

---

## Troubleshooting

**Problem: alloy is running but no metrics show up in Prometheus**

The alloy process is up but the AIAMSBS Prom `:9090` isn't accepting the
remote_write (or isn't receiving it). Check in order:

1. On the customer host, confirm alloy is healthy: `curl http://localhost:12345/-/ready` returns `ready`. If not, check `journalctl -u alloy -n 50` (Linux) or `Get-EventLog Application -Newest 10 -Source alloy` (Windows).
2. Confirm the env vars override the defaults: `ALLOY_REMOTE_WRITE_URL` should point at `http://<aiamsbs-host>:9090/api/v1/write` and `ALLOY_LOKI_URL` at `http://<aiamsbs-host>:3100/loki/api/v1/push`. From the customer host: `curl -v $ALLOY_REMOTE_WRITE_URL` should return HTTP 405 (Prom accepts POST for write, GET is the wrong verb — that's the right answer).
3. On the AIAMSBS host, check Prom's remote_write accept path: `curl -s 'http://localhost:9090/api/v1/query?query=up{job="integrations/unix"}' | jq`. If the series are present, the issue is the *targeting*, not the push. If empty, the push is failing — check `docker logs prometheus --since 5m | grep -i "remote_write\|integrations/unix"`.
4. Outbound firewall: confirm `ufw status` (Linux) or `Get-NetFirewallRule` (Windows) shows the rules from §2 / §4 allowing outbound TCP to Prom `:9090` + Loki `:3100`.

**Problem: alloy is pushing metrics but logs are missing**

The alloy River config has separate blocks for metrics and logs. Check
the relevant log source:

- **Linux:** `loki.source.journal "systemd"` reads from the local journal — confirm systemd journald is running (`systemctl status systemd-journald`). The auth/syslog file blocks (`local.file_match`) need read access to the files in `/var/log/`. SELinux/AppArmor denials will show up in alloy's stderr.
- **Windows:** `loki.source.windowsevent` reads the Application / System / Security channels. Alloy must run as LocalSystem or have `Event Log Readers` group membership (see §4). Confirm with `Get-Service alloy | Select-Object StartName` — `StartName` should be `LocalSystem`.

**Problem: Linux dashboard `Host` dropdown is empty even though alloy is pushing**

The dashboard variable query is `label_values(up{job="integrations/unix"}, host)`. If the dropdown is empty, query Prom directly to see whether the series are present:

```bash
curl -s 'http://localhost:9090/api/v1/query?query=up{job="integrations/unix"}' | jq
```

If series are present in Prom but the dropdown is empty, the dashboard's
templating variable is using a stale job name. Check
`config/grafana/provisioning/dashboards/node-exporter.json` under
`templating.list[0].query` — it should read
`label_values(up{job="integrations/unix"}, host)` post-cutover.

**Problem: Windows dashboard `Host` dropdown is empty**

Same as Linux but with `label_values(up{job="integrations/windows"}, host)`.
Check `config/grafana/provisioning/dashboards/node-exporter-windows.json`.

**Problem: `host` label is empty or wrong on alloy metrics**

The River config sets `host = sys.env("HOSTNAME")` (Linux) or
`sys.env("COMPUTERNAME")` (Windows, with `HOSTNAME` fallback). If the
label is missing or wrong:

- Linux: confirm `/etc/hostname` is set to a meaningful identifier
  (`app01`, `db-prod-01`). Avoid FQDNs — the dashboards assume a short
  hostname.
- Windows: confirm `$env:COMPUTERNAME` (PowerShell) is meaningful. If the
  River file's `coalesce(sys.env("COMPUTERNAME"), sys.env("HOSTNAME"))`
  fallback is hitting, set `COMPUTERNAME` as an env var to override.

**Problem: legacy NxLog won't start, log shows `no functional input modules! no routes defined!`**

(Only relevant for hosts still running the legacy NxLog path during the
cutover window.) The `<Input>`, `<Output>`, and `<Route>` blocks in
`nxlog.conf` are not all uncommented. The `Module` lines alone are not
enough — NxLog needs the block tags. Re-apply the legacy config in
[§5](#5-windows-event-logs-handled-by-alloy-legacy-nxlog).

**Problem: legacy Promtail listener still active for `:1514`/`:2514`**

These listeners stay running during the cutover transition window so that
hosts that haven't migrated yet still get their logs into Loki. They are
**decommissioned in BACKLOG #44 step 10** — do not enable them on new
installs. To check whether they are still listening:

```bash
# From the AIAMSBS host:
docker exec promtail cat /etc/promtail/config.yml | grep -E "1514|2514"
# Expect post-cutover: empty (both listeners gone)
# Expect during transition: both listeners present
```

**Problem: a host appears in the dropdown but its panels show "No data"**

The dropdown uses `up` to list hosts, but alloy-pushed series show up
under `job="integrations/unix"` / `job="integrations/windows"`. If the
series is present in Prom but no panels render, check:

- Prom variable for the panel query is using the alloy job label, not the
  legacy `linux_exporter` / `windows_exporter` label.
- For Loki panels: `job="systemd"` (Linux) or `job="windows_eventlog"`
  (Windows), not `source="customer_host_linux"` / `source="customer_host_windows"`.
- Grafana datasource has `X-Scope-OrgID` header set (see BACKLOG #45).

**Problem: the new dashboards won't load**

- Check the Grafana provisioning logs:
  `docker logs grafana 2>&1 | grep -i "node-exporter\|integrations"`
- Validate the dashboard JSON: `python3 -c "import json; json.load(open('/home/ansible/AIAMSBS/config/grafana/provisioning/dashboards/node-exporter-windows.json'))"`
- Confirm Grafana is reading the provisioning directory (mounted at
  `/etc/grafana/provisioning` in `docker-compose.yml`).

---

## Reference: where AIAMSBS itself is monitored

The AIAMSBS host is **not** in the `linux_exporter` job — it is monitored
through Alloy's `prometheus.exporter.unix "self"` (running inside the
Alloy container) which remote_writes to this Prometheus under
`job="integrations/unix"`. The customer-host River config files
(`config/alloy/customer-linux.river`, `config/alloy/customer-windows.river`)
use the same `job` label convention, so the AIAMSBS host and customer
hosts share a single per-host dashboard. Adding a `node_exporter` to the
AIAMSBS host itself is intentionally out of scope. See BACKLOG #10/B in
`BACKLOG.md` for the architectural decision (Ryland 2026-07-06).
