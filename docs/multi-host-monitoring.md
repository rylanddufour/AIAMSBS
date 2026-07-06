# Multi-Host Monitoring Setup

This guide covers installing `node_exporter` on Linux and Windows hosts and
forwarding syslog into the AIAMSBS promtail receivers, so each managed host
appears in the Grafana "Node Exporter (per-host)" dashboard
(uid `aiamsbs-node-exporter`).

The AIAMSBS host (`192.168.0.220`) is the reference target. Replace IP
addresses and hostnames as appropriate for your environment.

## Port Convention

The AIAMSBS promtail container listens on three syslog ports. **Do not
change these without updating `BACKLOG.md`.**

| Host port | Container port | Loki `source` label    | Use                       |
|-----------|----------------|------------------------|---------------------------|
| 514/TCP+UDP| 514           | `network_device`       | Network gear (Cisco, UniFi, Aruba, OPNsense) |
| 1514/TCP  | 1514          | `customer_host_linux`  | Customer Linux hosts via rsyslog |
| 2514/TCP  | 2514          | `customer_host_windows`| Customer Windows hosts via NxLog/Snare |

---

## 1. Linux `node_exporter` install

`node_exporter` is the Prometheus standard for host metrics (CPU, memory,
disk, network, filesystem inodes, processes, FDs, etc.).

### Download and install

```bash
# Latest stable release (check https://github.com/prometheus/node_exporter/releases for the current version)
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

---

## 2. Windows `node_exporter` install

`node_exporter` runs on Windows as a Windows service via the `.msi`
installer.

### Download and install

1. Grab the latest `.msi` from
   <https://github.com/prometheus/node_exporter/releases> (look for
   `node_exporter-<version>.windows-amd64.msi` or
   `node_exporter-<version>.windows-386.msi` for 32-bit).
2. Copy to the Windows host.
3. Install from an elevated `cmd.exe` or PowerShell:

   ```cmd
   msiexec /i node_exporter-1.8.2.windows-amd64.msi /qn
   ```

   `/qn` is a silent install. Omit it for a GUI install. The MSI
   registers `node_exporter` as a service called `node_exporter` and
   binds to `0.0.0.0:9100` by default.

4. (Optional) confirm the service is running:

   ```powershell
   Get-Service node_exporter
   # Status should be Running
   ```

5. (Optional) confirm the metrics endpoint from the Windows host itself:

   ```powershell
   (Invoke-WebRequest http://localhost:9100/metrics).Content.Split("`n") | Select-Object -First 5
   ```

### Verify from the AIAMSBS host

```bash
# From 192.168.0.220:
curl -s http://<windows-host-ip>:9100/metrics | grep node_uname_info
```

### Windows Firewall

If the AIAMSBS host can't reach :9100, allow inbound on the Windows
firewall from the AIAMSBS IP only:

```powershell
New-NetFirewallRule -DisplayName "node_exporter from AIAMSBS" `
  -Direction Inbound -LocalPort 9100 -Protocol TCP `
  -RemoteAddress 192.168.0.220 -Action Allow
```

---

## 3. Prometheus target registration

For each new host, add a `static_configs` block to the
`node_exporter` job in `config/prometheus.yml`. The `host` label is
the friendly name that appears in the Grafana dashboard dropdown.

```yaml
scrape_configs:
  - job_name: 'node_exporter'
    honor_labels: true
    scrape_interval: 30s
    scrape_timeout: 10s
    static_configs:
      - targets: ['192.168.0.220:9100']
        labels:
          host: aiamsbs-host
      # Windows file server
      - targets: ['192.168.0.50:9100']
        labels:
          host: fs01
      # Linux app server
      - targets: ['192.168.0.51:9100']
        labels:
          host: app01
```

`honor_labels: true` is critical — it prevents Prometheus from
overwriting your `host` label with the auto-generated `instance` label
(`192.168.0.50:9100`).

After editing, restart Prometheus:

```bash
docker compose restart prometheus
```

Verify the target is up:

```bash
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="node_exporter") | {host: .labels.host, health: .health}'
```

---

## 4. rsyslog snippet for Linux clients

`rsyslog` is the default syslog forwarder on most Linux distros
(Ubuntu, RHEL, Debian, CentOS, etc.). Forward everything to the
AIAMSBS host on port 1514.

### UDP (fire-and-forget, simpler)

Add to `/etc/rsyslog.d/10-aiamsbs.conf`:

```
# Forward all logs to AIAMSBS on UDP 1514
*.* @192.168.0.220:1514
```

`@` = UDP, `@@` = TCP. UDP is fine if log loss is acceptable.

### TCP (reliable, recommended)

```
# Forward all logs to AIAMSBS on TCP 1514
*.* @@192.168.0.220:1514
```

### Apply and verify

```bash
sudo systemctl restart rsyslog
# Verify the AIAMSBS host received logs:
curl -s 'http://192.168.0.220:3100/loki/api/v1/query?query={source="customer_host_linux"}' | jq
```

In Grafana, the new logs will appear in:
- The "Network Device Logs" dashboard (or a generic Loki explore) for
  streams tagged `source=customer_host_linux`
- The "Node Exporter (per-host)" dashboard's "Recent host logs" panel,
  filtered to the selected host

---

## 5. NxLog config snippet for Windows clients

`NxLog` is the standard open-source log forwarder for Windows. It
reads from the Windows Event Log and forwards to a remote syslog
endpoint. Snare or Event Log Forwarder (built into Windows Server)
also work; this guide covers NxLog as the most common option.

### Install NxLog

1. Download the community edition from
   <https://nxlog.co/products/nxlog-community-edition>.
2. Install with default options.

### NxLog config

Replace `C:\Program Files\nxlog\conf\nxlog.conf` with:

```
define ROOT     C:\Program Files\nxlog
define CERTDIR  %ROOT%\cert
define CONFDIR  %ROOT%\conf
define LOGDIR   %ROOT%\data
define LOGFILE  %LOGDIR%\nxlog.log
define DATEFMT  yyyy-MM-dd HH:mm:ss

Moduledir %ROOT%\modules
CacheDir  %ROOT%\data
Pidfile   %ROOT%\data\nxlog.pid
SpoolDir  %ROOT%\data
LogFile   %LOGFILE%
LogLevel  INFO

# Extension to parse Windows Event Log
<Extension json>
    Module      xm_json
</Extension>

# Read Security, System, and Application event logs
<Input eventlog>
    Module      im_msvistalog
    Query       <QueryList>\
                    <Query Id="0">\
                        <Select Path="Security">*[System[(Level=1 or Level=2 or Level=3)]]</Select>\
                        <Select Path="System">*[System[(Level=1 or Level=2 or Level=3)]]</Select>\
                        <Select Path="Application">*[System[(Level=1 or Level=2 or Level=3)]]</Select>\
                    </Query>\
                </QueryList>
</Input>

# Forward to AIAMSBS over TCP on port 2514
<Output aiassbs>
    Module      om_tcp
    Host        192.168.0.220
    Port        2514
    Exec        $SourceName = 'MSWinEventLog'; to_syslog_bsd();
</Output>

<Route aiassbs_route>
    Path        eventlog => aiassbs
</Route>
```

### Apply and verify

```powershell
# Restart the NxLog service
Restart-Service nxlog

# Tail the NxLog log to confirm forwarding
Get-Content 'C:\Program Files\nxlog\data\nxlog.log' -Tail 20
```

On the AIAMSBS host:

```bash
curl -s 'http://192.168.0.220:3100/loki/api/v1/query?query={source="customer_host_windows"}' | jq
```

---

## 6. Verification checklist

Run this checklist after adding any new host to confirm the full
pipeline is working.

### Prometheus scrape

```bash
# From the AIAMSBS host:
curl -s http://localhost:9090/api/v1/targets | \
  jq '.data.activeTargets[] | select(.job=="node_exporter") | {host: .labels.host, health: .health, lastError: .lastError}'
```

Expect: `health: "up"` and `lastError: ""` for every host.

### Per-host metrics

```bash
# Replace 'app01' with the host label you configured.
curl -s 'http://192.168.0.220:9090/api/v1/query?query=node_uname_info{host="app01"}' | jq
```

Expect: a single series with `nodename`, `sysname`, `release`, `version`,
`machine` labels.

### Syslog forwarder (Linux)

```bash
# On the Linux client:
logger -p auth.warning "AIAMSBS-VERIFY: test log line $(date -Iseconds)"
# Then from the AIAMSBS host:
curl -s 'http://192.168.0.220:3100/loki/api/v1/query?query={host="app01",source="customer_host_linux"}' | jq
```

### Syslog forwarder (Windows)

```powershell
# On the Windows client (PowerShell):
New-EventLog -LogName Application -Source "AIAMSBS-Verify" -ErrorAction SilentlyContinue
Write-EventLog -LogName Application -Source "AIAMSBS-Verify" -EventId 9999 -EntryType Warning -Message "AIAMSBS-VERIFY: test event $(Get-Date -Format o)"
```

```bash
# From the AIAMSBS host:
curl -s 'http://192.168.0.220:3100/loki/api/v1/query?query={host="fs01",source="customer_host_windows"}' | jq
```

### Dashboard

Open Grafana at <http://192.168.0.220:3000> and navigate to
**AIAMSBS Node Exporter (per-host)**. The `Host` dropdown should
list every host with a working `node_exporter`. Selecting a host
populates the Identity, CPU, Memory, Disk, Network, System, and Logs
rows.

### Listener health

Open Grafana → **AIAMSBS Health** dashboard → scroll to the new
**Promtail Listeners** row at the bottom. The three stat tiles
(`Listener :514`, `Listener :1514`, `Listener :2514`) should be green
once a single message has been received on each port.

---

## Troubleshooting

**Problem: target shows `health: "down"` with `context deadline exceeded`**

The AIAMSBS Prometheus container can't reach the target's port 9100.
Check:
- `node_exporter` is running on the target (`systemctl status node_exporter` or `Get-Service node_exporter`)
- The target's firewall allows 9100 from `192.168.0.220`
- `curl http://<target-ip>:9100/metrics` works from the AIAMSBS host

**Problem: logs not appearing in Loki**

- On the client, confirm the forwarder is sending: `tcpdump -i any port 1514` (Linux) or `Get-NetTCPConnection` (Windows)
- On the AIAMSBS host, confirm promtail received them: `docker logs promtail 2>&1 | tail -20`
- Check promtail's metrics: `curl http://localhost:9080/metrics | grep promtail_syslog_messages_total`

**Problem: dashboard dropdown is empty**

- Prometheus is not scraping the `node_exporter` job. Run the verification query in section 6.
- The metrics have no `host` label. Confirm the `static_configs` block has the `host:` label, and that `honor_labels: true` is set on the `node_exporter` job.

**Problem: the new `aiamsbs-node-exporter` dashboard won't load**

- Check the Grafana provisioning logs: `docker logs grafana 2>&1 | grep -i "node-exporter"`
- The dashboard JSON is at `config/grafana/provisioning/dashboards/node-exporter.json`. Validate with `jq .` and confirm Grafana is reading the provisioning directory (mounted at `/etc/grafana/provisioning` in `docker-compose.yml`).
