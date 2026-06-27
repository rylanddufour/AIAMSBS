# skills/network-oem-cisco-ios.md — Cisco IOS LAN/WAN Devices

## Purpose

This skill provides operational knowledge for Cisco LAN/WAN devices running Cisco IOS or IOS-like command syntax.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Cisco `show` commands may be recommended as read-only checks.

Cisco `configure terminal`, `write memory`, `copy running-config startup-config`, `reload`, interface changes, routing changes, VLAN changes, ACL changes, NAT changes, and AAA changes require explicit human approval.

## Scope

Primary scope:

- Cisco IOS routers
- Cisco IOS switches
- LAN switching
- WAN routing
- VLANs and trunks
- Routed interfaces
- SVIs
- Static routing
- OSPF concepts and operations
- Basic BGP concepts and operations
- ACLs
- NAT/PAT
- DHCP relay
- NTP
- SNMP
- Syslog
- SSH management
- Local users and AAA concepts
- Configuration backup and restore

Out of scope unless explicitly requested:

- Cisco ACI
- Cisco DNA Center
- Nexus NX-OS-specific syntax
- ASA/Firepower-specific syntax
- Meraki dashboard workflows

## Operating Model

Cisco IOS devices are generally CLI-first.

Understand:

- Running configuration vs startup configuration
- Privileged EXEC mode
- Global configuration mode
- Interface configuration mode
- VLAN configuration mode
- Explicit save behavior
- Console, SSH, and management access risks

## Safety Rules

Before suggesting configuration changes, identify:

- Device role
- Management IP/interface
- Whether the change could break remote access
- Whether the change affects trunks, routing, ACLs, NAT, or authentication
- Whether console or out-of-band access exists
- Rollback method

For risky remote changes, recommend considering a rollback timer such as:

```text
reload in 10
```

Only if appropriate and approved.

After successful validation, cancel reload if one was scheduled:

```text
reload cancel
```

Do not recommend saving the configuration until the change is validated.

## Common Read-Only Verification Commands

```text
show running-config
show startup-config
show version
show inventory
show interfaces status
show interfaces description
show interfaces
show ip interface brief
show vlan brief
show interfaces trunk
show spanning-tree
show etherchannel summary
show mac address-table
show arp
show ip route
show ip protocols
show cdp neighbors detail
show lldp neighbors detail
show logging
show clock
show ntp status
```

## Common Configuration Patterns

These are proposed examples only. Do not execute without human approval.

### Interface Description

```text
configure terminal
interface GigabitEthernet0/1
 description <DESCRIPTION>
end
```

### Access Port

```text
configure terminal
interface GigabitEthernet0/1
 description <DESCRIPTION>
 switchport mode access
 switchport access vlan <VLAN_ID>
 spanning-tree portfast
 spanning-tree bpduguard enable
end
```

### Trunk Port

```text
configure terminal
interface GigabitEthernet0/1
 description <DESCRIPTION>
 switchport mode trunk
 switchport trunk allowed vlan <VLAN_LIST>
end
```

### SVI

```text
configure terminal
interface Vlan<VLAN_ID>
 description <DESCRIPTION>
 ip address <IP_ADDRESS> <SUBNET_MASK>
 no shutdown
end
```

### Static Route

```text
configure terminal
ip route <DESTINATION_NETWORK> <SUBNET_MASK> <NEXT_HOP>
end
```

### Save Configuration

Only after validation and approval:

```text
write memory
```

or:

```text
copy running-config startup-config
```

## Troubleshooting Method

For Cisco IOS network issues:

1. Confirm device reachability.
2. Check interface state.
3. Check VLAN assignment.
4. Check trunk allowed VLANs.
5. Check spanning tree state.
6. Check MAC learning.
7. Check ARP.
8. Check routing table.
9. Check ACLs.
10. Check NAT if applicable.
11. Check logs.
12. Validate packet path reasoning.

## Output Expectations

When giving Cisco IOS guidance, include:

- Assumptions
- Read-only verification commands first
- Proposed configuration commands only as a plan
- Explanation of impact
- Rollback commands
- Save instructions only after validation and approval
