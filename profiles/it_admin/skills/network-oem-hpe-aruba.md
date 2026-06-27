# skills/network-oem-hpe-aruba.md — HPE Aruba LAN/WAN Devices

## Purpose

This skill provides operational knowledge for HPE Aruba LAN/WAN network devices.

Because Aruba platforms vary, identify the exact Aruba operating model before giving syntax-specific production commands.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Show/display/status commands are read-only.

VLAN changes, port changes, trunk/tagged/untagged changes, LAG changes, routing changes, ACL changes, management access changes, firmware changes, Central template changes, and reloads require explicit human approval.

## Scope

Primary scope:

- HPE Aruba LAN switches
- HPE Aruba WAN/network edge devices where applicable
- VLANs
- Access ports
- Trunk ports
- Link aggregation
- Spanning tree
- IP interfaces
- Static routing
- Dynamic routing concepts
- ACLs
- Management access
- Firmware upgrades
- Configuration backup and restore
- Troubleshooting

## Platform Identification Required

Before giving exact commands, identify whether the device is:

- Aruba CX
- ArubaOS-Switch / ProCurve-style switching
- Aruba Instant
- Aruba Instant On
- Aruba Mobility Controller / Gateway-managed
- Aruba Central-managed

Do not assume Aruba CX syntax for older ArubaOS-Switch devices.

Do not assume ArubaOS-Switch syntax for Aruba CX devices.

## Operating Models

### Aruba CX

Modern Aruba switching platform with Aruba CX CLI and API-friendly operations.

### ArubaOS-Switch / ProCurve-style

Common on older HPE/Aruba switches. Syntax differs from Aruba CX and Cisco IOS.

### Aruba Central-managed

Configuration may be template-based or group-based. Local CLI changes may be overwritten by Central.

### Aruba Instant / Instant On

Often controllerless or cloud-managed. Configuration should generally be performed through the appropriate management interface.

## Safety Rules

Before suggesting changes, identify:

- Device model
- OS family
- Management method
- Whether Aruba Central manages the device
- Current management VLAN/interface
- Whether the change touches trunks, uplinks, routing, ACLs, or authentication
- Rollback method
- Console or out-of-band availability

Warn when local changes may be overwritten by Aruba Central or another controller.

## General Troubleshooting Method

1. Confirm platform and management model.
2. Confirm physical link state.
3. Confirm VLAN assignment.
4. Confirm trunk/tagged/untagged VLAN behavior.
5. Confirm LACP/link aggregation state.
6. Confirm spanning tree state.
7. Confirm MAC address learning.
8. Confirm ARP/neighbor entries.
9. Confirm routing table.
10. Confirm ACL/firewall behavior.
11. Confirm logs and recent changes.

## Vendor Terminology Awareness

Aruba terminology may differ from Cisco terminology.

Examples:

- Cisco access port may correspond to untagged VLAN membership.
- Cisco trunk port may correspond to tagged VLAN membership.
- Native VLAN behavior may be represented differently by platform.
- Port-channel terminology may differ from link aggregation or LAG terminology.

## Response Expectations

When helping with Aruba devices, include:

- Platform identification step
- Conceptual explanation
- Platform-specific commands only when platform is known
- UI/controller workflow if centrally managed
- Validation steps
- Rollback steps
- Explicit approval request before any change

## Unknown Platform Behavior

If the exact Aruba platform is unknown, provide conceptual guidance first and ask for model and OS family before giving exact commands.
