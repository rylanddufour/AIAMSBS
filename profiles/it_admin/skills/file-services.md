# skills/file-services.md — Windows File Services

## Purpose

This skill provides file services administration knowledge, primarily for Windows Server SMB environments.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Read-only share, permission, and usage checks may be recommended directly.

Creating/deleting shares, modifying NTFS or share permissions, moving data, deleting data, changing quotas, changing DFS, or restoring files requires explicit human approval.

## Scope

Primary scope:

- SMB shares
- NTFS permissions
- Share permissions
- DFS namespaces
- DFS replication
- Access-based enumeration
- Quotas
- Shadow copies
- File server migration
- Auditing
- Locked file troubleshooting

## Read-Only Commands

```powershell
Get-SmbShare
Get-SmbShareAccess -Name <share>
Get-Acl <path>
Get-Volume
Get-ChildItem <path>
Get-DfsnRoot
Get-DfsnFolder -Path <path>
Get-DfsrBacklog
openfiles /query
```

## Change Commands Requiring Approval

Examples:

```powershell
New-SmbShare
Remove-SmbShare
Grant-SmbShareAccess
Revoke-SmbShareAccess
icacls <path> /grant
icacls <path> /remove
Remove-Item
Move-Item
New-DfsnFolder
Remove-DfsnFolder
```

## Permission Troubleshooting

Evaluate:

1. User identity
2. Group membership
3. Share permission
4. NTFS permission
5. Inheritance
6. Deny permissions
7. Access-based enumeration
8. DFS path vs target path
9. File lock
10. Offline files or client cache

## Safety Rules

Treat permission changes as medium to high risk depending on scope.

Treat recursive permission changes as high risk.

Treat deletes, moves, and robocopy mirror operations as destructive.

## Output Expectations

When helping with file services:

- Identify path and share name separately
- Separate share permissions from NTFS permissions
- Include read-only checks first
- Include rollback for permission changes
- Warn before recursive changes
