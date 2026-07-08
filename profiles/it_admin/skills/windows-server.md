# skills/windows-server.md — Windows Server Administration

## Purpose

This skill provides Windows Server administration knowledge beyond the base OS, including services, roles, management tools, PowerShell, networking, certificates, and operational troubleshooting.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Read-only PowerShell `Get-*`, `Test-*`, and diagnostic commands may be recommended directly.

Service restarts, role changes, firewall changes, registry edits, user/group changes, permission changes, patching, reboots, and configuration changes require explicit human approval.

## Scope

Primary scope:

- Windows Server roles and features
- Server Manager
- Windows Admin Center concepts
- Services
- Event Viewer
- PowerShell
- Windows Firewall
- Local users and groups
- Storage
- Certificates
- Scheduled tasks
- Windows Update
- Remote management
- WinRM
- Performance counters
- Server roles/features

## Read-Only PowerShell Examples

```powershell
Get-ComputerInfo
Get-Service
Get-EventLog -LogName System -Newest 50
Get-WinEvent -LogName System -MaxEvents 50
Get-NetIPAddress
Get-NetRoute
Test-NetConnection <target> -Port <port>
Resolve-DnsName <name>
Get-WindowsFeature
Get-LocalUser
Get-LocalGroup
Get-SmbShare
Get-Volume
Get-PhysicalDisk
```

## Change Commands Requiring Approval

Examples:

```powershell
Restart-Service
Stop-Service
Start-Service
Install-WindowsFeature
Uninstall-WindowsFeature
New-LocalUser
Add-LocalGroupMember
Set-NetFirewallRule
New-NetFirewallRule
Set-ItemProperty
Restart-Computer
Remove-Item
```

## Troubleshooting Areas

### Service Issues

Check:

- Service state
- Dependencies
- Event logs
- Account used by service
- File permissions
- Network ports
- Certificates if TLS is involved

### Remote Management

Check:

- WinRM state
- Firewall rules
- DNS resolution
- Authentication
- Local administrator or delegated rights
- PowerShell remoting policy

## Output Expectations

When helping with Windows Server:

- Prefer PowerShell for repeatability
- Provide GUI path when useful
- Label read-only vs change commands
- Include `-WhatIf` when available
- Include rollback or restore guidance for changes

## References

### Windows Exporter (Prometheus agent on the monitored Windows host)

The `windows_exporter` binary runs on the customer Windows host (`.246` in dev: `192.168.0.246:9182`) and exposes Prometheus metrics for AIAMSBS to scrape. When iterating on Windows dashboards, the **per-collector docs are the source of truth for metric names and labels** — not the Prometheus output, not the grafana.com community dashboards.

- **Repo:** https://github.com/prometheus-community/windows_exporter
- **Per-collector docs:** https://github.com/prometheus-community/windows_exporter/tree/master/docs/ — one page per collector (e.g., `collector.os.md`, `collector.system.md`, `collector.process.md`, `collector.service.md`, `collector.logical_disk.md`, `collector.net.md`, `collector.cpu.md`, `collector.memory.md`). Each page lists the metric names, label sets, and the WMI/Performance-Counter data sources.
- **Currently pinned version in AIAMSBS:** `v0.31.7` (verified 2026-07-07). Pin from the actual binary on the host, not from memory:
  ```powershell
  (Get-Item "C:\Program Files\windows_exporter\windows_exporter.exe").VersionInfo.FileVersion
  ```

**Gotchas already hit (2026-07-07):**

- The `cs` (Computer System) collector was **removed in v0.30**. The `windows_cs_hostname` and `windows_computer_system_info` metrics do NOT exist anymore — replaced by `windows_os_hostname` from the `os` collector (which provides `domain`, `fqdn`, `hostname` labels).
- The `system` collector exposes `windows_system_boot_time_timestamp` (Unix epoch), **not** a pre-computed `windows_system_system_uptime`. Uptime = `time() - windows_system_boot_time_timestamp`.
- Collector lists can change between minor versions. When a panel shows "No data" with the same `host=` selector that works for other panels, **first check the per-collector doc for the current exporter version** before assuming the metric should exist.
- `honor_labels: true` on the AIAMSBS scrape job means if the exporter itself exposes a label (rare), it wins over the static `host:` label. Default behavior is the opposite.
