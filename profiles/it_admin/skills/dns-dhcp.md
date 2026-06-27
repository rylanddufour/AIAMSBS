# skills/dns-dhcp.md — DNS and DHCP Administration

## Purpose

This skill provides DNS and DHCP administration knowledge for Windows Server and infrastructure environments.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Read-only DNS and DHCP queries may be recommended directly.

Creating, modifying, deleting, or scavenging DNS records, DHCP scopes, reservations, options, leases, or failover settings requires explicit human approval.

## Scope

Primary scope:

- Windows DNS
- Forward lookup zones
- Reverse lookup zones
- Conditional forwarders
- DNS scavenging
- Split-horizon DNS
- DHCP scopes
- DHCP reservations
- DHCP options
- DHCP failover
- Lease troubleshooting
- DNS dependency for Active Directory

## DNS Read-Only Commands

```powershell
Resolve-DnsName <name>
nslookup <name>
Get-DnsServerZone
Get-DnsServerResourceRecord -ZoneName <zone>
Get-DnsServerForwarder
Get-DnsServerConditionalForwarderZone
```

## DHCP Read-Only Commands

```powershell
Get-DhcpServerv4Scope
Get-DhcpServerv4Lease -ScopeId <scope>
Get-DhcpServerv4Reservation -ScopeId <scope>
Get-DhcpServerv4OptionValue -ScopeId <scope>
Get-DhcpServerv4Failover
```

## Change Commands Requiring Approval

Examples:

```powershell
Add-DnsServerResourceRecordA
Remove-DnsServerResourceRecord
Set-DnsServerResourceRecord
Add-DhcpServerv4Scope
Set-DhcpServerv4Scope
Add-DhcpServerv4Reservation
Remove-DhcpServerv4Reservation
Set-DhcpServerv4OptionValue
```

## Troubleshooting DNS

Check:

- Client DNS server settings
- Forward lookup
- Reverse lookup
- Authoritative zone
- Conditional forwarder
- Recursion/forwarder behavior
- AD-integrated zone replication
- Stale or duplicate records
- TTL and caching

## Troubleshooting DHCP

Check:

- Scope active state
- Available addresses
- Exclusions
- Reservations
- Options
- Relay/IP helper
- Failover state
- Server authorization in AD
- Client VLAN/subnet alignment

## Output Expectations

When helping with DNS/DHCP:

- Separate DNS resolution from network connectivity
- Identify authoritative source
- Include read-only checks first
- Warn before deleting or scavenging records
- Include rollback for record/scope/option changes
