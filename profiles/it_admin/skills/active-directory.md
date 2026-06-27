# skills/active-directory.md — Active Directory Administration

## Purpose

This skill provides Active Directory administration, troubleshooting, and change planning knowledge.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

AD read-only queries may be recommended directly.

Creating, modifying, disabling, deleting, moving, or permissioning AD objects requires explicit human approval.

GPO changes, FSMO role changes, domain controller changes, replication changes, and authentication policy changes are high-risk and require explicit human approval.

## Scope

Primary scope:

- Domains, forests, and trees
- OUs
- Users, groups, and computers
- Group Policy
- FSMO roles
- Domain controllers
- Sites and services
- Replication
- SYSVOL
- Kerberos
- LDAP
- Time synchronization
- Domain join troubleshooting
- Secure delegation
- Common PowerShell commands

## Read-Only Commands

```powershell
Get-ADDomain
Get-ADForest
Get-ADDomainController -Filter *
Get-ADUser -Identity <user> -Properties *
Get-ADGroup -Identity <group> -Properties *
Get-ADComputer -Identity <computer> -Properties *
Get-ADReplicationFailure -Scope Forest
Get-ADReplicationPartnerMetadata -Target * -Scope Forest
dcdiag
repadmin /replsummary
nltest /dsgetdc:<domain>
w32tm /query /status
gpresult /r
```

## Change Commands Requiring Approval

Examples:

```powershell
New-ADUser
Set-ADUser
Disable-ADAccount
Remove-ADUser
New-ADGroup
Add-ADGroupMember
Remove-ADGroupMember
Move-ADObject
Set-GPLink
New-GPO
Set-GPRegistryValue
```

## Troubleshooting Method

For AD issues, check:

1. DNS health
2. Domain controller availability
3. Time synchronization
4. Replication health
5. SYSVOL health
6. Authentication path
7. Account state
8. Group membership
9. GPO application
10. Event logs

## Safety Rules

Treat the following as high-risk:

- Domain Admin changes
- Enterprise Admin changes
- GPO changes
- Domain controller demotion/promotion
- FSMO changes
- Certificate services changes
- Kerberos policy changes
- Authentication protocol changes
- Large OU moves
- Bulk account changes

## Output Expectations

When helping with AD:

- Start with read-only diagnostics
- Consider DNS and time synchronization early
- Warn about replication delay
- Include rollback or restore guidance for changes
- Require explicit approval for object or policy modifications
