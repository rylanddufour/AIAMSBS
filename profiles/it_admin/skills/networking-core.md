# skills/networking-core.md — LAN/WAN Networking Core

## Purpose

This skill provides vendor-neutral LAN/WAN networking knowledge for design, troubleshooting, documentation, and safe change planning.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Read-only checks may be recommended directly. Configuration changes require explicit human approval.

## Core Competencies

The agent understands:

- OSI and TCP/IP models
- Ethernet switching
- VLANs and 802.1Q tagging
- Access ports and trunk ports
- Native VLAN risks
- Spanning Tree Protocol
- LACP and link aggregation
- MAC address learning
- ARP and neighbor discovery
- IPv4 and IPv6 addressing
- Subnetting and summarization
- Static routing
- OSPF concepts
- BGP concepts
- NAT and PAT
- ACLs and firewall policy concepts
- Site-to-site VPNs
- Remote access VPNs
- MTU and fragmentation
- QoS concepts
- DNS and DHCP interactions
- Packet capture basics
- Network monitoring and telemetry
- Datacenter network patterns

## Troubleshooting Method

For connectivity issues:

1. Confirm source, destination, protocol, and port.
2. Confirm scope of issue.
3. Check physical/link state.
4. Check VLAN assignment and tagging.
5. Check IP address, mask, gateway, and route table.
6. Check ARP or neighbor table.
7. Check DNS resolution if names are involved.
8. Check local firewall on source and destination.
9. Check upstream firewall or ACL policy.
10. Check NAT if traffic crosses zones or internet boundaries.
11. Check asymmetric routing.
12. Check MTU.
13. Validate with packet capture if needed.

## Common Linux Read-Only Commands

```bash
ip addr
ip route
ip neigh
ping <target>
traceroute <target>
tracepath <target>
ss -tulpn
dig <name>
nslookup <name>
tcpdump -i <interface> host <target>
```

## Common Windows Read-Only Commands

```powershell
ipconfig /all
route print
arp -a
Test-NetConnection <target> -Port <port>
Resolve-DnsName <name>
tracert <target>
pathping <target>
netsh advfirewall show allprofiles
```

## Output Expectations

When responding to network issues, include:

- Likely failure domain
- Read-only tests to isolate the issue
- Commands for relevant platforms
- Explanation of what each command proves
- Safe remediation proposal
- Rollback guidance for any configuration change

## Safety Rules

Do not recommend immediate changes to routing, spanning tree, trunks, port channels, firewall rules, VPNs, or management interfaces.

Always include rollback steps for proposed network changes.

Warn if a change may disconnect remote management.
