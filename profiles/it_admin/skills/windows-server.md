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
