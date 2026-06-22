# Multi-OEM Management + Monitoring Integration for AIAMSBS

Research date: 2026-06-22
Target stack: Prometheus + Loki + Grafana + Hermes agent, Docker Compose-based, for SMB IT shops

---

## 1. Windows Server (2016/2019/2022; AD DS, IIS, File Services)

### Management Interfaces

| Interface | Protocol/Method | Notes |
|-----------|----------------|-------|
| WMI | DCOM/WBEM | Legacy but universal on all Windows Server versions. Query via `python -m wmi` or PowerShell CIM. AD DS, IIS, file shares all exposed via WMI classes. |
| PDH (Performance Data Helpers) | Windows API | The engine behind Performance Monitor. `windows_exporter` uses this natively via Win32 APIs. |
| PowerShell CIM/WMI cmdlets | WinRM (port 5985/5986) | Modern replacement for WMI. Requires PSRemoting enabled. |
| WinRM | WS-Management HTTP | Default ports: 5985 (HTTP), 5986 (HTTPS). Used by Ansible, PyWinRM, `netapi32`. |
| IIS Administration API | REST (localhost) | Available on Server 2016+. HTTPS on port 8172. See [Microsoft IIS Admin API docs](https://learn.microsoft.com/en-us/iis/manage/scripting-the-iis-administration-api). |
| AD DS | LDAP/ldaps (389/636) | Standard LDAP queries. `ldap3` Python library. |
| SMB | TCP 445 | File service monitoring via SMB protocol stats. |

**Vendor Docs:**
- PDH API: https://learn.microsoft.com/en-us/windows/win32/perfctrs/pdh-start-page
- WMI: https://learn.microsoft.com/en-us/windows/win32/wmisdk/wmi-start-page
- PowerShell CIM: https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/

### Prometheus/Grafana Integration

- **Exporter:** `prometheus-community/windows_exporter` (Go, official Prometheus community project)
  - GitHub: https://github.com/prometheus-community/windows_exporter
  - Stars: ~3,600 | Forks: ~780 | 122 tagged releases
  - Active: last commit 3 days ago
  - **Collectors (44 total):** ad, adcs, adfs, cache, cpu, cpu_info, container, diskdrive, dfsr, dhcp, dns, exchange, file, fsrmquota, gpu, hyperv, iis, license, logical_disk, memory, mscluster, msmq, mssql, netframework, net, os, pagefile, performancecounter, physical_disk, printer, process, remote_fx, scheduled_task, service, smb, smbclient, smtp, system, tcp, terminal_services
  - **Key for SMB:** `iis` (IIS worker processes, requests/sec, bandwidth), `ad` (domain controllers, NTLM auth failures), `mssql` (SQL Server perf counters), `file` (file server share stats), `cpu`/`memory`/`logical_disk`/`physical_disk` (general host metrics)
  - Default port: 9182
  - Installation: MSI installer or Chocolatey `choco install windows_exporter`

- **Syslog-to-Loki:** Enable Windows Event Log forwarding via WinEventLog --> syslog-ng or nxlog, then to Promtail/Loki. Alternatively use `windows_exporter` with `--collector.evtx` collector.

- **Grafana Dashboards:**
  - `windows-exporter-dashboard` (official, included in windows_exporter repo at `dashboard/windows-exporter-dashboard.json`)
  - Search: "Windows Server" on grafana.com/dashboards for community dashboards
  - #10468: Windows Server 2019/2022 dashboard (community)
  - Node Exporter Full #1860 works for host-level metrics too (CPU, memory, disk, network)
  - #4271: Docker and System Monitoring (for Windows containers/docker)

### Potential Hermes Skill Shape

```
windows-server/
  ├── SKILL.md
  ├── manage_windows.py          # Core: pywinrm, wmi, ldap3, requests
  ├── collectors.py              # Identify which collectors to enable
  ├── service_manager.py         # Start/stop/restart Windows services via WinRM
  ├── ad_monitor.py              # LDAP queries for AD health
  ├── iis_manager.py             # IIS site/app pool management
  ├── deploy_exporter.py         # Install windows_exporter via WinRM/PSRemoting
  └── alerts.py                  # Event log-based alert rules
```

**Python libraries needed:** `pywinrm` (WinRM), `wmi` (WMI COM), `ldap3` (AD), `requests` (IIS API), `pywin32` (local only)

**Idempotent patterns:** Use `Invoke-Command` with `Test-Path`/`Get-WmiObject` checks. WinRM sessions are stateless; use `-ConnectionUri` for remote execution.

### EOL / Version Fragmentation

- **Windows Server 2012 R2** (EOL Oct 2023): Still widely deployed in SMBs. `windows_exporter` supports it but some collectors may not work. WMI is primary management interface. WinRM 2.0 (Windows 7/2008+).
- **Windows Server 2016** (extended support until 2027): Good WinRM 3.0, IIS Administration API available.
- **Windows Server 2019** (support until July 2026): Full modern management stack.
- **Windows Server 2022** (current): All features available.
- **Special handling:** 2012 R2 may need WinRM PSRemoting manually enabled. PowerShell 4.0 vs 5.1+ ( Cim vs WMI cmdlets). IIS Administration API only on 2016+.

---

## 2. Linux (Debian/Ubuntu/RHEL/CentOS)

### Management Interfaces

| Interface | Protocol/Method | Notes |
|-----------|----------------|-------|
| SSH | TCP 22 | Primary remote management. Paramiko, fabric, netmiko for automation. |
| systemd D-Bus API | D-Bus (local) | https://www.freedesktop.org/software/systemd/man/latest/dbus-org.freedesktop.systemd1.html |
| sysfs | /sys/ filesystem | Kernel parameters, device info, hardware sensors. |
| procfs | /proc/ filesystem | Process info, memory, CPU, network stats. |
| netlink | Socket API | Route tables, interface config, cgroups. |
| Container runtimes | Docker API (2376/2375), containerd (12798), podman | Manage containers, images, networks. |
| Package managers | apt (Debian/Ubuntu), dnf/yum (RHEL/CentOS) | Service/package management. |
| Configuration management | ansible (YAML), salt, puppet | Infrastructure-as-code for config drift. |

**Vendor Docs:**
- sysfs: https://www.kernel.org/doc/html/latest/filesystems/sysfs.html
- procfs: https://man7.org/linux/man-pages/man5/proc.5.html
- D-Bus: https://www.freedesktop.org/wiki/Software/dbus/
- netlink: https://man7.org/linux/man-pages/man7/netlink.7.html

### Prometheus/Grafana Integration

- **Exporter:** `prometheus/node_exporter` (Go, official Prometheus project, primary choice)
  - GitHub: https://github.com/prometheus/node_exporter
  - Stars: ~13,500 | Forks: ~2,700 | 60 tagged releases
  - Active: last commit 2 weeks ago, 2,471 commits
  - **Collectors (40+):** cpu, diskstats, edfc, entropy, filefd, filesystem, hwmon, infiniband, loadavg, logind, mdadm, memory, netclass, netdev, netstat, nfs, ntp, os, pkgstats, power supply, process, pressure, runit, selinux, smart, sockstat, stat, systemd, textfile, time, timex, thermal_zone, uname, vmstat, wifi, xfs, zfs
  - Default port: 9100
  - **Docker-specific:** `cAdvisor` (official Google container metrics) or `prometheus/node-exporter` with `--path.rootfs=/hostfs` flag for host-level metrics inside container.
  - **Container runtime metrics:** `containerd_exporter`, `cAdvisor`

- **Syslog-to-Loki:** Promtail (already in AIAMSBS stack) natively reads `/var/log/syslog`, `/var/log/messages`, journal logs.

- **Grafana Dashboards:**
  - **#1860** — "Node Exporter Full" (by rnfredri) — 136M+ downloads. Nearly all node_exporter metrics. Recommended for prometheus-node-exporter v0.18+. Arguments: `--collector.systemd --collector.processes`.
  - **#6287** — "Host Overview" (by ichasco) — CPU, RAM, NETWORK, DISK, LOAD. Simple, 5.9k downloads.
  - **#4271** — "Docker and System Monitoring" (by paulfantom) — 14.2k downloads. Host + container metrics with namespace labels.
  - **#13465** — "Docker Monitoring" — Container-level metrics.
  - cAdvisor dashboard: search "cAdvisor" on grafana.com/dashboards

- **Additional exporters:**
  - `cadvisor` (Google) — Container metrics: https://github.com/google/cadvisor
  - `process-exporter` — Per-process CPU/memory: https://github.com/ncabatoff/process-exporter
  - `logstash_exporter` — Logstash metrics: https://github.com/sabhiram/go-prometheus-exporters

### Potential Hermes Skill Shape

```
linux/
  ├── SKILL.md
  ├── manage_linux.py          # Core: fabric, ansible-runner, paramiko
  ├── service_manager.py       # systemctl wrappers (enable/disable/start/stop)
  ├── config_drift.py          # Check config files vs git baseline
  ├── package_manager.py       # apt/dnf operations
  ├── deploy_node_exporter.py  # Install node_exporter + configure collectors
  ├── journal_monitor.py       # systemd journal reading
  └── containers.py            # Docker/containerd management via API
```

**Python libraries needed:** `fabric` (SSH orchestration), `ansible-runner` (run Ansible playbooks programmatically), `paramiko` (SSH), `systemd-python` (D-Bus), `pydbus` (D-Bus), `docker` (Docker API)

**Idempotent patterns:** Use `systemctl is-active` checks before start/stop. Ansible playbooks are naturally idempotent. Package checks via `dpkg -l` or `rpm -q`.

### EOL / Version Fragmentation

- **Debian 9/10** (EOL): Still in use. Older systemd versions, different package names.
- **Ubuntu 18.04** (EOL April 2023): Systemd 237. Still has Docker packages.
- **Ubuntu 20.04/22.04/24.04**: Current LTS. Systemd 247+. snap packages may interfere.
- **CentOS 7** (EOL June 2024): systemd 219. Uses yum not dnf. `node_exporter` v0.16 compatible only.
- **RHEL 7/8/9**: RHEL 7 same as CentOS 7. RHEL 8/9 use dnf, newer systemd.
- **Special handling:** Containerized `node_exporter` requires `--path.rootfs=/hostfs` plus volume mounts of `/proc`, `/sys`, `/` (as rootfs). Non-root mount points need bind mounts.

---

## 3. Cisco Catalyst Switches (CatOS AND IOS)

### Management Interfaces

| Interface | Protocol/Method | Notes |
|-----------|----------------|-------|
| SSH | TCP 22 | Primary for IOS/IOS-XE. Requires enable-mode for show commands. |
| Telnet | TCP 23 | Legacy, but some legacy switches still use it. |
| SNMP | UDP 161/162 | SNMPv2c (community strings) or SNMPv3 (authentication+encryption). |
| RESTCONF/NETCONF | HTTPS | Available on Catalyst 9000 (IOS-XE), NX-OS. Requires API token/bearer auth. |
| CLI via TTY | Serial console | Fallback management for switches without network access. |
| Catalyst SDK | REST API | Developer-facing API for Catalyst 9000 series. |

**Vendor Docs:**
- Catalyst SDK: https://developer.cisco.com/site/catalyst-9000-sdk/
- NX-OS API: https://developer.cisco.com/docs/nx-os-9k/
- IOS XE RESTCONF: https://developer.cisco.com/docs/ios-xe-restconf/
- IOS CLI basics: https://www.cisco.com/c/en/us/support/docs/ip/basic-switch-configuration/27644-switchcli.html
- SNMP MIBs: https://www.cisco.com/c/en/us/support/docs/ip/simple-network-management-protocol-snmp/1388-75.html

### Prometheus/Grafana Integration

- **Primary approach: `prometheus/snmp_exporter`** (official Prometheus project)
  - GitHub: https://github.com/prometheus/snmp_exporter
  - Stars: ~2,100 | Forks: ~730 | 40 tagged releases
  - Active: last commit yesterday, 1,064 commits
  - **Pre-built config:** `snmp.yml` includes modules for `cisco` (generic) and specific device types
  - **Generator tool:** `generator/` directory with `gen_config.yaml` for building custom SNMP modules. Can be extended with custom MIBs.
  - Default port: 9116
  - **Config example:** Add to `snmp.yml`:
    ```yaml
    cisco:
      auth:
        community: public_v2  # or SNMPv3 config
      modules:
        default:
          get:
            - if_mib/ifIndex
            - if_mib/ifDescr
            - if_mib/ifType
            - if_mib/ifAdminStatus
            - if_mib/ifOperStatus
            - if_mib/ifInOctets
            - if_mib/ifOutOctets
            - cisco_cdp
            - cisco_bgp4
            - cisco_ospf
    ```
  - **For IOS-XE RESTCONF:** Can scrape directly via REST API or use a RESTCONF-to-prometheus bridge.

- **Alternative: `czerwonk/cisco_exporter`** (community)
  - SSH-based, similar to `junos_exporter`
  - Reads via `show` commands parsed via regex
  - Not as mature as SNMP approach

- **Syslog-to-Loki:** Cisco IOS/NX-OS send syslog to UDP/TCP. AIAMSBS already has Promtail/syslog ingesting from OPNsense at port 1514. Extend to include switch syslog. Use `severity` label mapping (info=notice, err=error, etc.).

- **Grafana Dashboards:**
  - Search "Cisco" on grafana.com/dashboards — community dashboards exist but no single definitive one
  - SNMP exporter comes with example Prometheus query patterns for interface stats
  - Generic interface monitoring via `if_mib` module works for Cisco

### Potential Hermes Skill Shape

```
cisco-catalyst/
  ├── SKILL.md
  ├── manage_cisco.py          # Core: netmiko, paramiko, ciscoconfparse
  ├── snmp_config.py           # Configure SNMP community/credentials
  ├── backup_config.py         # SCP/TFTP config backup
  ├── show_parser.py           # Parse 'show' command output (netmiko)
  ├── interface_monitor.py     # Interface status/errors via SNMP
  ├── cdp_neighbor.py          # CDP/LLDP neighbor discovery
  └── bgp_ospf_monitor.py      # Protocol health via SNMP (bgp4, ospf)
```

**Python libraries needed:** `netmiko` (multi-vendor SSH CLI), `pysnmp` (SNMP), `ciscoconfparse` (IOS config parsing), `requests` (RESTCONF), `scp` (config backup)

**Idempotent patterns:** SSH-based config changes via netmiko + textfsm parsing. SNMP set operations for configuration. RESTCONF PATCH for IOS-XE devices.

### EOL / Version Fragmentation

- **CatOS** (EOL ~2008): Legacy Catalyst 5000/6000 series. Uses CatOS CLI (`show port`, `set interface`). SNMP MIBs differ from modern IOS. Requires SNMPv1 (no v3 support on many CatOS boxes).
- **IOS 12.x** (EOL for many branches): Older IOS switches. No RESTCONF. SNMPv2c only. Limited MIB support.
- **IOS-XE 16.x/17.x**: Modern Catalyst 9000 series. RESTCONF/NETCONF available. Full MIB support.
- **NX-OS**: Datacenter switches (Nexus). Different CLI syntax from Catalyst. Separate MIBs.
- **Special handling:** CatOS needs SNMPv1 walk (no v3). IOS 12.x may need community string `public_v2` (standard read-only). RESTCONF requires `enable` mode token generation on IOS-XE.

---

## 4. Ubiquiti UniFi Wireless (Controller + APs/Gateways/Switches)

### Management Interfaces

| Interface | Protocol/Method | Notes |
|-----------|----------------|-------|
| UniFi Network API | REST (HTTPS) | Controller API. Port 8443 by default. Token-based auth via POST to `/api/auth/login`. |
| UniFi Protect API | REST/WebSocket | For cameras. Separate from Network API. |
| SNMP | UDP 161 | Available on UniFi APs, USW switches, UDM gateways. |
| SSH | TCP 22 | On USG/UDM devices. Requires UniFi OS 2.0+ or custom firmware. |
| UniFi Central | Cloud API | Enterprise management via cloud. Different from self-hosted controller. |

**Vendor Docs:**
- UniFi Network API (official guide): https://dl.ubnt.com/guides/welcome/unifi-network-application-guide/
- UniFi API (unifi-py): https://github.com/pftom/unifiprotect
- UniFi SNMP MIBs: https://www.ui.com/downloads/unifi/

### Prometheus/Grafana Integration

- **Primary option: `unpoller/unpoller`** (Go, most mature UniFi monitoring solution)
  - GitHub: https://github.com/unpoller/unpoller
  - Stars: ~2,650 | Forks: ~170 | MIT license
  - **Active:** last commit today (very active maintenance)
  - Collects ALL UniFi Controller, Site, Device & Client data
  - **Outputs to:** Prometheus (built-in), InfluxDB, JSON
  - **Docker-ready:** `golift/unpoller` on Docker Hub
  - **Exported data (comprehensive):**
    - Sites and site-level stats
    - Devices: UAP (access points), USW (switches), UCG/UDM (gateways), UVC (cameras)
    - Per-device: status, radio stats (2.4/5/6 GHz), client count, bandwidth, tx/rx power
    - Per-client: connected clients, signal strength, data usage, session time
    - Switch: port status, utilization, PoE status, LLDP neighbors
    - Gateway: WAN/LAN traffic, uptime, firmware version, VPN status
    - **Alerts:** Pre-built alerting rules for Prometheus (in `/alerts/prometheus/`)
  - **Config:** `unpoller.conf` — specifies UniFi controller URL, credentials, and polling interval
  - **Grafana dashboards included:** Yes, multiple dashboards included in the repo under `tools/grafana/` and documented at unpoller.com

- **Secondary option: `mdlayher/unifi_exporter`** (Go)
  - GitHub: https://github.com/mdlayher/unifi_exporter
  - Stars: ~260 | Forks: ~70 | MIT license
  - **Status:** Less actively maintained (last commit 2018). Exposes metrics from UniFi Controller via REST API.
  - Docker image available: `mdlayher/unifi-exporter`

- **SNMP approach:** `zygiss/snmp-exporter-unifi` (23 stars) — SNMP generator config for UniFi APs. Limited coverage vs UnPoller's API approach.

- **Syslog-to-Loki:** UniFi devices send syslog to configured server. Configure in UniFi Controller: Settings --> System --> Advanced --> Log Settings. Forward to Promtail/Loki.

- **Grafana Dashboards:**
  - UnPoller includes Grafana JSON dashboards (check `tools/grafana/` directory)
  - Search "unifi" on grafana.com/dashboards — community dashboards available
  - Dashboard IDs vary; UnPoller provides pre-configured dashboards via its Docker setup
  - Example: `unifi-poller` Grafana integration includes device overview, client overview, switch port, and AP radio dashboards

### Potential Hermes Skill Shape

```
unifi/
  ├── SKILL.md
  ├── manage_unifi.py          # Core: unifi-py or requests against UniFi Network API
  ├── discover_devices.py      # Auto-discover APs, switches, gateways via API
  ├── client_tracker.py        # Track connected clients via API
  ├── ap_config.py             # SSID, radio config, VLAN assignment
  ├── switch_config.py         # Port config, VLANs, PoE settings
  ├── backup_config.py         # Export UniFi controller config (JSON)
  └── deploy_exporter.py       # Deploy unpoller via Docker Compose
```

**Python libraries needed:** `requests` (UniFi REST API), `unifi-py` (if available) or raw API calls

**UniFi API authentication flow:** POST to `https://controller:8443/api/auth/login` with username/password, receive JWT token, use in subsequent requests as `X-UniFi-Auth` header.

**Idempotent patterns:** UniFi API is stateful — use GET to check current state before PUT/PATCH. SSID changes are idempotent if comparing against desired state. Backup config exports full controller state.

### EOL / Version Fragmentation

- **UniFi Controller versions:** 6.x (legacy), 6.5.x (common), 7.x (current). API endpoints may differ between versions.
- **UniFi OS 2.0+:** Newer gateway hardware (UDM, USG) require different SSH/API access.
- **UniFi Protect:** Separate API from Network API. Cameras only accessible via Protect API.
- **Special handling:** The UnPoller library (unpoller/unpoller) supports both legacy 6.x and modern 7.x controllers. Token auth vs cookie auth depending on controller version.

---

## 5. Aruba Networks (ArubaOS-CX, ArubaOS-Switch, InstantOS APs, Aruba Central)

### Management Interfaces

| Interface | Protocol/Method | Notes |
|-----------|----------------|-------|
| ArubaOS-CX RESTCONF/REST API | HTTPS | Modern Catalyst-equivalent. Supports RESTCONF with YANG models. |
| Aruba Instant (IAP) API | REST (HTTPS) | For Instant APs and virtual controllers. Port 443. |
| ArubaOS-Switch (ProVision) CLI | SSH/Telnet | Legacy ProVision-based switches (2530/2930M). No REST API. |
| Aruba Central API | REST (Cloud) | Cloud-managed Aruba devices. OAuth2 bearer token. |
| SSH | TCP 22 | All Aruba platforms support SSH. |
| SNMP | UDP 161/162 | All platforms support SNMPv2c/v3. |

**Vendor Docs:**
- ArubaOS-CX RESTCONF: https://developer.arubanetworks.com/aruba-os_cx/
- Aruba Instant (IAP) API: https://developer.arubanetworks.com/aruba-instant/
- Aruba Central API: https://developer.arubanetworks.com/aruba-central
- AOS-Switch CLI docs: https://developer.arubanetworks.com/aruba-docs/
- SNMP MIBs: https://www.hpe.com/us/en/support.html

### Prometheus/Grafana Integration

- **Exporter: `slashdoom/aruba_exporter`** (Go, community project)
  - GitHub: https://github.com/slashdoom/aruba_exporter
  - Stars: ~12 | Forks: ~7 | MIT license
  - **Status:** Development stage, last commit 2023-01-18, 2 open issues
  - **Protocol:** SSH-based (similar to cisco_exporter/junos_exporter pattern)
  - **Devices supported:** ArubaSwitchOS, ArubaOS-CX, ArubaOS Instant AP, ArubaOS controllers
  - **Metrics:** Basic switch/AP metrics (enabled by default, can disable per-metric)
  - Default port: 9909
  - Config: `--ssh.targets`, `--ssh.user`, `--ssh.password` or `--ssh.keyfile`
  - **Limitation:** SSH-based only; no RESTCONF support yet. Community-maintained, limited adoption.

- **Alternative approach for ArubaOS-CX:** Use SNMP exporter (`prometheus/snmp_exporter`) with Aruba MIBs. Download Aruba MIBs from HPE support portal. Build custom `snmp.yml` module.

- **Aruba Central API:** If customers use cloud-managed Aruba, scrape metrics directly from Aruba Central REST API. OAuth2 authentication.

- **Syslog-to-Loki:** Aruba devices support syslog forwarding. Configure in device settings to send to Promtail/Loki server.

- **Grafana Dashboards:**
  - No widely-known dedicated Aruba Grafana dashboard IDs
  - SNMP exporter provides base query patterns for switch interface monitoring
  - Community dashboards exist but are less common than Cisco/UniFi

### Potential Hermes Skill Shape

```
aruba/
  ├── SKILL.md
  ├── manage_aruba.py          # Core: paramiko (SSH), requests (REST API)
  ├── oscx_manager.py          # ArubaOS-CX RESTCONF management
  ├── instant_manager.py       # Aruba Instant (IAP) management
  ├── central_manager.py       # Aruba Central cloud API
  ├── aos_switch_manager.py    # Legacy ProVision-based AOS-Switch (CLI)
  ├── backup_config.py         # Config backup via SCP or REST API
  └── deploy_exporter.py       # Deploy aruba_exporter or SNMP config
```

**Python libraries needed:** `paramiko` (SSH), `requests` (REST/RESTCONF), `pyyaml` (Aruba config parsing), `ciscoconfparse` (works for Aruba CLI too in some cases)

**Idempotent patterns:** ArubaOS-CX uses RESTCONF with ETags for optimistic locking. Aruba Instant API is stateful — check before modifying. SSH config changes need diff comparison.

### EOL / Version Fragmentation

- **ArubaOS-CX 10.x** (current): Modern CX switches (6300/8320/8400). Full RESTCONF.
- **ArubaOS-Switch 16.x** (ProVision-based): Legacy switches (2530/2930/5406R). CLI-only. No REST.
- **Aruba Instant On:** Newer entry-level line. Different API from full Instant.
- **Special handling:** The `aruba_exporter` currently only covers SSH-based scraping. ArubaOS-CX RESTCONF metrics would need a separate implementation. HPE/Merger transition may affect MIB availability.

---

## 6. VMware vSphere (ESXi 7/8, vCenter)

### Management Interfaces

| Interface | Protocol/Method | Notes |
|-----------|----------------|-------|
| vCenter REST API | HTTPS | Official REST API. VMware Developer portal. |
| vSphere REST API | HTTPS | ESXi-host-level API (no vCenter required). |
| vSphere Automation API (SDK) | REST | Newer API replacing VI API. Supports Python/Java/Go SDKs. |
| VMware SDK (VI API) | SOAP/REST | Legacy API. Python SDK: pyvmomi. |
| govc | CLI | Command-line tool for vSphere. Go-based. Wraps VI API. |
| SSH | TCP 22 | ESXi shell access. Limited but available. |

**Vendor Docs:**
- vCenter REST API: https://developer.vmware.com/apis/vcenter/latest/
- vSphere REST API: https://developer.vmware.com/apis/vsphere-rest/
- govc: https://github.com/vmware/govmomi/tree/main/govc
- pyvmomi: https://github.com/vmware/pyvmomi

### Prometheus/Grafana Integration

- **Exporter: `pryorda/vmware_exporter`** (Python)
  - GitHub: https://github.com/pryorda/vmware_exporter
  - Stars: ~580 | Forks: ~220 | BSD-3-Clause license
  - **Status:** Active maintenance (last commit April 2026), but maintainer stepping down (project seeking new home)
  - **Metrics collected:**
    - Basic VM and Host metrics (CPU, memory, disk)
    - Active snapshot counts
    - Datastore size and usage
    - Snapshot creation timestamps
    - vCenter health status
  - Default port: 9272
  - **Config:** YAML config specifying vCenter hosts, credentials, and which metrics to collect
  - **Docker:** Official Docker image: `pryorda/vmware_exporter`

- **Alternative:** No other widely-known Prometheus VMware exporter with significant adoption.

- **Syslog-to-Loki:** VMware ESXi sends syslog. Configure ESXi logging to forward to Promtail/Loki server. Events and alarms can be captured via vCenter REST API.

- **Grafana Dashboards:**
  - Search "VMware" or "vCenter" on grafana.com/dashboards — community dashboards exist
  - No single definitive VMware dashboard like #1860 is for node_exporter
  - Dashboards typically visualize `vmware_exporter` metrics (datastore, VM count, host health)

### Potential Hermes Skill Shape

```
vmware/
  ├── SKILL.md
  ├── manage_vmware.py         # Core: pyvmomi (vmware.vapi), requests (REST API)
  ├── deploy_exporter.py       # Deploy vmware_exporter via Docker
  ├── vm_provision.py          # Create/clone VMs via pyvmomi
  ├── snapshot_manager.py      # Create/list/delete snapshots
  ├── datastore_monitor.py     # Datastore capacity monitoring
  ├── esxi_manager.py          # ESXi host management (reboot, maintenance mode)
  ├── alarm_manager.py         # Configure vCenter alarms
  └── health_check.py          # vCenter health, host connectivity, datastore alerts
```

**Python libraries needed:** `pyvmomi` (VMware vSphere SDK for Python, official), `requests` (REST API), `pygovc` (if using govc as subprocess)

**govc as alternative:** `govc` (https://github.com/vmware/govmomi/tree/main/govc) — official VMware CLI tool. Can be invoked from Hermes skills for management tasks. Example: `govc vm.info`, `govc datastore.info`, `govc host.info`.

**Idempotent patterns:** pyvmomi `FindByInventoryPath()` for object lookup. Check existence before create. Use `vim.Task` for async operations. REST API ETag-based locking.

### EOL / Version Fragmentation

- **ESXi 6.7** (EOL May 2024): Legacy but deployed. pyvmomi 6.7+ required.
- **ESXi 7.0** (current EOL date: May 2026): pyvmomi 7.0+. REST API available.
- **ESXi 8.0** (current): Latest. Full REST API and Automation API support.
- **vCenter 6.7/7.0/8.0:** API versions align with ESXi versions. vCenter 6.7 deprecated.
- **Special handling:** ESXi 6.x requires pyvmomi 6.7. ESXi 7+ requires pyvmomi 7.0+. SSL certificate verification is strict — may need to disable for self-signed certs. VMware acquired by Broadcom (2023) — some open source projects may lose support.

---

## Summary: Build vs Wrap Assessment

| OEM | Monitoring Exporter | Build Needed? | Complexity | Hermes Skill Priority |
|-----|--------------------|---------------|------------|----------------------|
| **Windows Server** | `windows_exporter` — mature, official, 44 collectors | Wrap | Low | **HIGH** — core SMB workload |
| **Linux** | `node_exporter` + `cadvisor` — official, 40+ collectors | Wrap | Low | **HIGH** — core infrastructure |
| **Cisco Catalyst** | `snmp_exporter` (pre-built) — good coverage | Wrap SNMP config | Medium | **MEDIUM** — network infra |
| **UniFi** | `unpoller/unpoller` — very mature, 2650 stars | Wrap | Low | **MEDIUM** — common in SMBs |
| **Aruba** | `slashdoom/aruba_exporter` — nascent, 12 stars | Build new exporter or extend SNMP | High | **LOW** — less common in SMBs |
| **VMware** | `pryorda/vmware_exporter` — maintained but seeking new home | Wrap + extend | Medium | **MEDIUM** — if customers use it |

### Key Recommendations

1. **Wrap, don't rewrite:** 5 of 6 OEMs have existing exporters that can be wrapped by Hermes skills. Focus on the management API layer, not the metrics scraping.

2. **Highest ROI targets:** Windows Server and Linux are the two most common workloads for SMB shops. Their exporters (`windows_exporter`, `node_exporter`) are mature, well-maintained, and have rich Grafana dashboards.

3. **UniFi wins for wireless:** UnPoller (`unpoller/unpoller`) is the clear choice — 2,650 stars, very active, comprehensive coverage of APs/switches/gateways/cameras, includes Grafana dashboards and Prometheus alerts.

4. **Cisco via SNMP:** Don't build a CLI-based exporter. The `snmp_exporter` from Prometheus is production-ready and handles Cisco MIBs. The skill should wrap SNMP configuration + config backup via netmiko.

5. **Aruba needs investment:** The community exporter is nascent (12 stars). Consider starting with SNMP-based monitoring via `snmp_exporter` with Aruba MIBs, then build RESTCONF scraping for ArubaOS-CX as a separate effort.

6. **VMware is optional:** Only needed if target SMBs use vSphere. The exporter exists but maintainer is stepping down. Keep an eye on community fork activity.

7. **Syslog to Loki is universal:** All 6 OEMs support syslog forwarding. This is a configuration task, not an exporter. Include in every OEM skill.
