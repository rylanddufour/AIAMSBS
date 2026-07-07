# Multi-Host Monitoring Setup

This guide covers what to install and configure on each customer host so it
appears in AIAMSBS's Grafana dashboards alongside the AIAMSBS host itself.
Four scenarios are covered — pick the ones that match your environment:

| On each host... | Install... | So it shows up in... |
|---|---|---|
| Linux | `node_exporter` (port 9100) | Linux dashboard: `AIAMSBS Node Exporter (per-host)` |
| Linux | `rsyslog` config snippet | Loki: `{source="customer_host_linux"}` |
| Windows | `windows_exporter` (port 9182) | Windows dashboard: `AIAMSBS Windows Exporter (per-host)` |
| Windows | `NxLog` config snippet | Loki: `{source="customer_host_windows"}` |

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

| Host port | Protocol | AIAMSBS job / Loki source | Use |
|---|---|---|---|
| 514 | TCP+UDP | `network_syslog` / `source=network_device` | Network gear (Cisco, UniFi, Aruba, OPNsense) |
| 1514 | TCP | `customer_host_linux` / `source=customer_host_linux` | Customer Linux hosts via rsyslog |
| 2514 | TCP | `customer_host_windows` / `source=customer_host_windows` | Customer Windows hosts via NxLog |
| 9100 | TCP | `linux_exporter` (Prometheus) | Customer Linux hosts via node_exporter |
| 9182 | TCP | `windows_exporter` (Prometheus) | Customer Windows hosts via windows_exporter |

---

## 2. Linux: install `node_exporter`

`node_exporter` is the Prometheus standard for host metrics (CPU, memory,
disk, network, filesystem inodes, processes, file descriptors, etc.).

### Download and install

```bash
# Check https://github.com/prometheus/node_exporter/releases for the current version
NODE_EXPORTER_VERSION="1.8.2"
cd /tmp
curl -L -o node_exporter.tar.gz \
  "https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
tar xzf node_exporter.tar.gz
sudo cp node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/
sudo useradd -r -s /usr/sbin/nologin node_exporter || true
```

### systemd service

Create `/etc/systemd/system/node_exporter.service`:

```ini
[Unit]
Description=Prometheus node_exporter
Documentation=https://github.com/prometheus/node_exporter
After=network-online.target

[Service]
Type=simple
User=node_exporter
Group=node_exporter
# ARGS lets you customize the listen address or filter collectors.
# Default :9100 is fine; change if you have a port conflict.
Environment=ARGS=--web.listen-address=:9100
ExecStart=/usr/local/bin/node_exporter $ARGS
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
sudo systemctl enable --now node_exporter
sudo systemctl status node_exporter
```

### Verify locally

```bash
curl -s http://localhost:9100/metrics | head -5
# Expected: HELP/ TYPE lines for go_gc_duration_seconds, etc.

# Confirm the hostname is exposed:
curl -s http://localhost:9100/metrics | grep node_uname_info
# Expected: node_uname_info{...,nodename="<your-hostname>",...} 1.0
```

### Verify from the AIAMSBS host

```bash
# From 192.168.0.220:
curl -s http://<linux-host-ip>:9100/metrics | grep node_uname_info
```

If the firewall blocks :9100, open it from the AIAMSBS host's IP only:

```bash
sudo ufw allow from 192.168.0.220 to any port 9100 proto tcp
```

Then proceed to [§6 — Telling AIAMSBS](#6-telling-aiamsbs-to-monitor-a-new-host)
to register this host with Prometheus.

---

## 3. Linux: forward syslog to AIAMSBS (rsyslog)

`rsyslog` is the default syslog forwarder on most Linux distros
(Ubuntu, RHEL, Debian, CentOS, Alma, Rocky, etc.). Forward everything to the
AIAMSBS host on port 1514.

### TCP (recommended — reliable)

Add `/etc/rsyslog.d/10-aiamsbs.conf`:

```
# Forward all logs to AIAMSBS on TCP 1514
*.* @@192.168.0.220:1514
```

`@` is UDP, `@@` is TCP. Use TCP unless you have a specific reason not to
(UDP is fire-and-forget — log loss is acceptable in some cases).

### Apply and verify

```bash
sudo systemctl restart rsyslog
```

Then proceed to [§6](#6-telling-aiamsbs-to-monitor-a-new-host) and use the
prompt pattern for syslog registration.

> **The Loki `host` label is set automatically by Promtail** from the
> `__syslog_message_hostname` field of the syslog header. Use a meaningful
> hostname in `/etc/hostname` and rsyslog will tag every log line with it.

---

## 4. Windows: install `windows_exporter`

`windows_exporter` (the Prometheus community Windows exporter, formerly
`wmi_exporter`) exposes host metrics for Windows servers. It uses a different
binary, port, and metric namespace than the Linux `node_exporter`.

| | Linux `node_exporter` | Windows `windows_exporter` |
|---|---|---|
| Port | 9100 | 9182 |
| Metrics prefix | `node_*` | `windows_*` |
| AIAMSBS scrape job | `linux_exporter` | `windows_exporter` |
| Dashboard | `aiamsbs-node-exporter` | `aiamsbs-node-exporter-windows` |

### Download and install

1. Grab the latest installer from
   <https://github.com/prometheus-community/windows_exporter/releases>
   (look for `windows_exporter-<version>-amd64.msi`).
2. Copy to the Windows host.
3. Install from an elevated PowerShell:

   ```powershell
   msiexec /i windows_exporter-0.31.7-amd64.msi ENABLED_COLLECTORS=cpu,memory,logical_disk,net,os,service,system,logon,tcp /qn
   ```

   `/qn` is a silent install. `ENABLED_COLLECTORS` lists the WMI classes to
   expose — the list above covers CPU, memory, disk, network, OS info, services,
   system uptime, logon sessions, and TCP connections. Omit `ENABLED_COLLECTORS`
   to enable all default collectors, or pick a different set for your needs.

4. Confirm the service is running:

   ```powershell
   Get-Service windows_exporter
   # Status should be Running
   ```

5. Confirm the metrics endpoint from the Windows host:

   ```powershell
   (Invoke-WebRequest http://localhost:9182/metrics).Content.Split("`n") | Select-Object -First 5
   # Expected: HELP/ TYPE lines for windows_cpu_time_total, etc.
   ```

### Windows Firewall

Allow inbound on 9182 from the AIAMSBS IP only:

```powershell
New-NetFirewallRule -DisplayName "windows_exporter from AIAMSBS" `
  -Direction Inbound -LocalPort 9182 -Protocol TCP `
  -RemoteAddress 192.168.0.220 -Action Allow
```

Then proceed to [§6](#6-telling-aiamsbs-to-monitor-a-new-host).

---

## 5. Windows: forward event logs to AIAMSBS (NxLog)

`NxLog` Community Edition is the standard open-source log forwarder for
Windows. It reads from the Windows Event Log and forwards to a remote
syslog endpoint. Snare or the built-in Windows Event Log Forwarder also
work; this guide covers NxLog.

### Install NxLog

1. Download the community edition from
   <https://nxlog.co/products/nxlog-community-edition>.
2. Install with default options.
3. **Allow outbound 2514/TCP to the AIAMSBS host** in Windows Firewall:

   ```powershell
   New-NetFirewallRule -DisplayName "AIAMSBS Syslog 2514" `
     -Direction Outbound -Protocol TCP -RemotePort 2514 `
     -RemoteAddress 192.168.0.220 -Action Allow
   ```

### NxLog config

> **Important:** NxLog Community Edition does **not** support `<QueryList>`
> XPath filters in `im_msvistalog` (that's a NXLog Enterprise Edition
> feature). The config below uses CE-compatible syntax that reads all events
> from the three default Windows event log channels (Application, System,
> Security) and emits them as RFC5424 syslog — which is the format Promtail
> expects.

Replace `C:\Program Files\nxlog\conf\nxlog.conf` with:

```
Panic Soft
#NoFreeOnExit TRUE

define ROOT     C:\Program Files\nxlog
define CERTDIR  %ROOT%\cert
define CONFDIR  %ROOT%\conf\nxlog.d
define LOGDIR   %ROOT%\data
define LOGFILE  %LOGDIR%\nxlog.log

include %CONFDIR%\\*.conf

LogFile %LOGFILE%

Moduledir %ROOT%\modules
CacheDir  %ROOT%\data
Pidfile   %ROOT%\data\nxlog.pid
SpoolDir  %ROOT%\data

<Extension _syslog>
    Module      xm_syslog
</Extension>

<Input in>
    Module      im_msvistalog
    # Reads Application, System, and Security event logs.
    # Comment out Security if your shop restricts Security log forwarding.
    <QueryList>
        <Query Id="0">
            Select Path="Application">*</Select>
            Select Path="System">*</Select>
            Select Path="Security">*</Select>
        </Query>
    </QueryList>
</Input>

<Output out>
    Module      om_tcp
    Host        192.168.0.220
    Port        2514
    # to_syslog_ietf() emits RFC5424, which Promtail parses cleanly.
    # to_syslog_snare() (the original NxLog example) produces a
    # third-party format that Promtail rejects.
    Exec        to_syslog_ietf();
</Output>

<Route 1>
    Path        in => out
</Route>
```

> **Note on the `<QueryList>` block above:** NxLog CE ignores this block
> (it doesn't support XPath filters). All three channels are read by
> default. If you need per-channel filtering, restrict the `im_msvistalog`
> channels with NxLog's `Channel` directive, or use NXLog Enterprise Edition
> which honours `<QueryList>`.

### Apply and verify

```powershell
# Restart the NxLog service
Restart-Service nxlog

# Tail the NxLog log to confirm no errors
Get-Content 'C:\Program Files\nxlog\data\nxlog.log' -Tail 20
```

A clean startup log should show `INFO connecting to 192.168.0.220:2514` with
no `no functional input modules!` or `no routes defined!` warnings. If you
see those, the `<Input>`, `<Output>`, and `<Route>` blocks are likely
commented out — the `Module` lines alone are not enough.

Then proceed to [§6](#6-telling-aiamsbs-to-monitor-a-new-host) to tell
AIAMSBS the host's friendly name.

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
is working.

### Prometheus scrape (Linux)

```bash
# From the AIAMSBS host:
curl -s http://localhost:9090/api/v1/targets | \
  jq '.data.activeTargets[] | select(.job=="linux_exporter") | {host: .labels.host, health: .health, lastError: .lastError}'
```

Expect: `health: "up"` and `lastError: ""` for every host.

### Prometheus scrape (Windows)

```bash
curl -s http://localhost:9090/api/v1/targets | \
  jq '.data.activeTargets[] | select(.job=="windows_exporter") | {host: .labels.host, health: .health, lastError: .lastError}'
```

Expect: `health: "up"` and `lastError: ""` for every host.

### Per-host metrics (Linux)

```bash
# Replace 'app01' with the host label you configured.
curl -s 'http://localhost:9090/api/v1/query?query=up{host="app01",job="linux_exporter"}' | jq
```

Expect: a single series with `"value": ["...", "1"]`.

### Per-host metrics (Windows)

```bash
curl -s 'http://localhost:9090/api/v1/query?query=up{host="fs01",job="windows_exporter"}' | jq
```

For actual Windows-specific metrics:

```bash
curl -s 'http://localhost:9090/api/v1/query?query=windows_cpu_time_total{host="fs01"}' | jq
```

### Syslog forwarder (Linux)

```bash
# On the Linux client:
logger -p auth.warning "AIAMSBS-VERIFY: test log line $(date -Iseconds)"

# Then from the AIAMSBS host:
curl -s 'http://localhost:3100/loki/api/v1/query?query={host="app01",source="customer_host_linux"}' | jq
```

Expect: a `result` array with at least one entry containing your test
message.

### Syslog forwarder (Windows)

```powershell
# On the Windows client (PowerShell):
New-EventLog -LogName Application -Source "AIAMSBS-Verify" -ErrorAction SilentlyContinue
Write-EventLog -LogName Application -Source "AIAMSBS-Verify" -EventId 9999 -EntryType Warning -Message "AIAMSBS-VERIFY: test event $(Get-Date -Format o)"
```

```bash
# From the AIAMSBS host:
curl -s 'http://localhost:3100/loki/api/v1/query?query={host="fs01",source="customer_host_windows"}' | jq
```

### Dashboards

Open Grafana at <http://192.168.0.220:3000>:

- **AIAMSBS Node Exporter (per-host)** (uid `aiamsbs-node-exporter`) — Linux
  hosts. The `Host` dropdown should list every host with a working
  `node_exporter`. Selecting a host populates Identity, CPU, Memory, Disk,
  Network, System, and Logs rows.
- **AIAMSBS Windows Exporter (per-host)** (uid `aiamsbs-node-exporter-windows`)
  — Windows hosts. Same UX, Windows-specific metrics (`windows_*`).
- **AIAMSBS Health** → **Promtail Listeners** row at the bottom. The three
  stat tiles (`:514`, `:1514`, `:2514`) should be green once a single
  message has been received on each port.

---

## Troubleshooting

**Problem: target shows `health: "down"` with `context deadline exceeded`**

The AIAMSBS Prometheus container can't reach the target's port.

- Linux: confirm `node_exporter` is running (`systemctl status node_exporter`),
  firewall allows 9100 from `192.168.0.220`, and `curl http://<target>:9100/metrics`
  works from the AIAMSBS host.
- Windows: confirm `windows_exporter` is running (`Get-Service windows_exporter`),
  Windows Firewall inbound rule for 9182 from `192.168.0.220` exists, and
  `curl http://<target>:9182/metrics` works from the AIAMSBS host.

**Problem: Linux dashboard `Host` dropdown is empty even though a target is up**

Prometheus' `up` series for the target has a `host` label, but the dashboard's
`$host` variable query (`label_values(up{job="linux_exporter"}, host)`) may be
using a different job name. Check `config/grafana/provisioning/dashboards/node-exporter.json`
under `templating.list[0].query` and confirm the job matches.

**Problem: Windows dashboard `Host` dropdown is empty**

Same as Linux but the job should be `windows_exporter`. If the dropdown is
empty even though `curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.job=="windows_exporter")'` shows the target as `up`, the
dashboard provisioning is stale. Grafana picks up JSON changes every 10s —
wait, then refresh.

**Problem: NxLog won't start, log shows `no functional input modules! no routes defined!`**

The `<Input>`, `<Output>`, and `<Route>` blocks in `nxlog.conf` are not
all uncommented. The `Module` lines alone are not enough — NxLog needs
the block tags. Re-apply the config in [§5](#5-windows-forward-event-logs-to-aiamsbs-nxlog).

**Problem: NxLog log shows `invalid keyword: QueryList`**

NxxLog CE does not support the `<QueryList>` XPath filter. Either delete the
`<QueryList>...</QueryList>` block from the `<Input in>` section (NxLog will
read all three default channels), or use the `Channel` directive to restrict
per-channel. See [§5](#5-windows-forward-event-logs-to-aiamsbs-nxlog).

**Problem: NxLog log shows `error parsing syslog stream: expecting a version value in the range 1-999`**

NxLog is sending `to_syslog_snare()` or some other non-RFC5424 format. Promtail
expects RFC5424. Replace the `Exec` line in `<Output out>` with
`Exec to_syslog_ietf();` and restart the NxLog service.

**Problem: logs not appearing in Loki (Linux)**

- On the client, confirm the forwarder is sending:
  `tcpdump -i any port 1514` (Linux) or `Get-NetTCPConnection -RemotePort 2514` (Windows)
- On the AIAMSBS host, confirm promtail received them:
  `docker logs promtail 2>&1 | tail -20`
- Check promtail's metrics: `curl http://localhost:9080/metrics | grep syslog_target_messages_total`
- Confirm the firewall rule is bidirectional: client → AIAMSBS:1514 (or
  2514) must be allowed outbound

**Problem: a host appears in the dropdown but its panels show "No data"**

The dropdown uses `up` to list hosts, so even a down target can show up.
Check `health: "up"` for that target. If `health: "down"`, the agent on the
host has stopped (service crashed, port blocked, etc.) — start there.

**Problem: the new dashboards won't load**

- Check the Grafana provisioning logs:
  `docker logs grafana 2>&1 | grep -i "node-exporter\|windows_exporter"`
- Validate the dashboard JSON: `python3 -c "import json; json.load(open('/home/ansible/AIAMSBS/config/grafana/provisioning/dashboards/node-exporter-windows.json'))"`
- Confirm Grafana is reading the provisioning directory (mounted at
  `/etc/grafana/provisioning` in `docker-compose.yml`).

---

## Reference: where AIAMSBS itself is monitored

The AIAMSBS host is **not** in the `linux_exporter` job — it is monitored
through Alloy's `prometheus.exporter.unix "self"` (running inside the
Alloy container) which remote_writes to this Prometheus under
`job="integrations/unix"`. Adding a `node_exporter` to the AIAMSBS host
itself is intentionally out of scope. See BACKLOG #10/B in
`BACKLOG.md` for the architectural decision (Ryland 2026-07-06).
