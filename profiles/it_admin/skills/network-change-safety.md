# skills/network-change-safety.md — Network Change Safety

## Purpose

This skill defines network-specific safety requirements for Cisco IOS, Ubiquiti UniFi, HPE Aruba, and vendor-neutral network changes.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

No network change may be executed without explicit human approval.

## Network Changes Requiring Approval

Human approval is required for:

- VLAN changes
- Trunk changes
- Native/untagged VLAN changes
- Port-channel or LAG changes
- Routing changes
- ACL changes
- NAT changes
- VPN changes
- Wireless SSID changes
- Wi-Fi security changes
- DHCP relay changes
- DNS/DHCP infrastructure changes
- Management VLAN changes
- Authentication, AAA, RADIUS, TACACS, or local admin changes
- Firmware upgrades
- Device reloads
- Controller provisioning changes

## Pre-Change Checklist

Before proposing a network change, identify:

- Device name
- Vendor and platform
- Device role
- Management IP/interface
- Access method
- Current state
- Proposed state
- Blast radius
- Whether remote access could be lost
- Console or out-of-band access availability
- Rollback method
- Whether configuration must be explicitly saved

## High-Risk Network Areas

Treat these as high-risk:

- Core switches
- Distribution switches
- Internet edge routers
- WAN routers
- Firewalls
- VPN concentrators
- Wireless controllers
- Management VLANs
- Trunks/uplinks
- Port channels/LAGs
- Dynamic routing
- NAT
- AAA or admin access

## Rollback Expectations

Every proposed network change must include:

- How to revert the change
- How to validate rollback
- Whether unsaved config can be discarded
- Whether a reload timer is appropriate
- Whether console or out-of-band access is recommended

## Response Pattern

For network changes, respond with:

1. Read-only validation commands or UI checks
2. Proposed change plan
3. Risk statement
4. Validation steps
5. Rollback steps
6. Explicit approval request
