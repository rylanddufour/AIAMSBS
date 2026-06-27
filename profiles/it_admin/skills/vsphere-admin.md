# skills/vsphere-admin.md — VMware vSphere Administration

## Purpose

This skill provides VMware vSphere administration knowledge for ESXi, vCenter, clusters, virtual networking, storage, templates, migrations, snapshots, and operational troubleshooting.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Read-only inventory and health checks may be recommended directly.

VM power changes, host maintenance mode, migrations, snapshot changes, datastore changes, vSwitch/vDS changes, cluster changes, permission changes, upgrades, and deletions require explicit human approval.

## Scope

Primary scope:

- ESXi host administration
- vCenter administration
- Clusters
- HA and DRS
- vMotion and Storage vMotion
- Standard switches
- Distributed switches
- Port groups
- VLAN tagging
- VMkernel adapters
- Management, vMotion, storage, and fault tolerance networks
- Datastores
- VMFS and NFS storage
- iSCSI concepts
- Fibre Channel concepts
- Templates and cloning
- Snapshots and snapshot risks
- VMware Tools
- Resource pools
- CPU and memory reservations, limits, and shares
- Alarms and events
- Host profiles
- Lifecycle Manager
- Permissions and roles
- Backup considerations
- Log collection and support bundles

## Read-Only PowerCLI Examples

```powershell
Get-VM
Get-VMHost
Get-Cluster
Get-Datastore
Get-VirtualPortGroup
Get-VDPortgroup
Get-Snapshot -VM <VMName>
Get-VMHostNetworkAdapter
Get-VMHost | Get-VMHostService
Get-Task
Get-AlarmDefinition
```

## Change Commands Requiring Approval

Examples:

```powershell
Start-VM
Stop-VM
Restart-VM
Move-VM
New-Snapshot
Remove-Snapshot
Set-VM
New-VM
Remove-VM
Set-VMHost
Set-Cluster
New-VirtualPortGroup
Set-VirtualPortGroup
Set-VDPortgroup
```

## Troubleshooting Method

For VM issues, determine whether the issue is caused by:

1. Guest OS
2. VMware Tools
3. Virtual hardware
4. Port group or vSwitch configuration
5. VLAN or physical network
6. Storage latency or datastore capacity
7. Host resource contention
8. Cluster policy
9. Snapshot growth
10. Backup or replication stun
11. Permissions or vCenter inventory problems

## Common Checks

### VM Health

- Power state
- VMware Tools status
- Recent events
- Snapshot presence
- Datastore free space
- CPU ready
- Memory ballooning or swapping
- Disk latency
- Network adapter connected state
- Port group assignment

### Host Health

- Management network status
- Host connectivity in vCenter
- Datastore connectivity
- NIC link state
- Physical uplink mapping
- Time synchronization
- Hardware health
- Recent alarms
- Maintenance mode state

### Networking

Validate:

- Correct port group
- Correct VLAN
- Correct vSwitch or distributed switch
- Correct uplinks
- Correct physical switch trunking
- VMkernel network separation
- MTU consistency
- MAC address conflicts
- Security settings such as forged transmits, MAC changes, and promiscuous mode

## Snapshot Guidance

Snapshots are not backups.

Before proposing snapshots, consider:

- Datastore free space
- Expected duration
- Application consistency
- Backup interaction
- Consolidation risk
- Performance impact

Always recommend removing or consolidating snapshots after the maintenance window.

## Output Expectations

When responding to vSphere issues, include:

- Whether issue appears host-level, cluster-level, VM-level, storage-level, or network-level
- vCenter UI checks
- PowerCLI commands where helpful
- Guest OS checks when relevant
- Risk notes
- Rollback guidance
- Explicit approval request before any change
