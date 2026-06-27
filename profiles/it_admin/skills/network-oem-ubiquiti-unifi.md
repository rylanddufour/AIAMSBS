# skills/network-oem-ubiquiti-unifi.md — Ubiquiti UniFi Network Devices

## Purpose

This skill provides operational knowledge for Ubiquiti UniFi network environments, especially UniFi Wi-Fi devices and controller-managed network equipment.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Controller review, status inspection, and reporting are read-only.

Changes to WLANs, networks, VLANs, switch port profiles, firewall rules, device adoption, firmware, provisioning, or gateway settings require explicit human approval.

## Scope

Primary scope:

- UniFi Network Application
- UniFi access points
- WLAN configuration
- SSIDs
- VLAN-backed wireless networks
- Guest networks
- WPA2/WPA3 concepts
- Band steering
- Channel planning
- RF troubleshooting
- Client troubleshooting
- Device adoption
- Firmware upgrades
- Controller backups
- Site management
- UniFi switches where applicable
- UniFi gateways where applicable

## Operating Model

UniFi environments are controller-first.

Prefer configuration through:

- UniFi Network Application UI
- Site settings
- Network profiles
- Wi-Fi profiles
- Switch port profiles
- Gateway/firewall settings where applicable
- Supported APIs or automation workflows where appropriate

Manual CLI changes on UniFi devices may not persist after reprovisioning. Warn before suggesting direct device CLI changes.

## Safety Rules

Before suggesting UniFi changes, identify:

- Controller location
- Site name
- Device model
- Firmware version
- Whether the device is adopted
- Whether the device is online
- Whether the change affects management VLANs
- Whether the change affects the SSID currently used for admin access
- Whether wired fallback access exists
- Whether changes will trigger provisioning

Avoid changes that could orphan APs, break adoption, or disconnect remote administrators.

## Core UniFi Concepts

Understand:

- Controller adoption
- Inform URL
- Sites
- Networks
- Wi-Fi profiles
- VLAN tagging
- Native/untagged networks
- Switch port profiles
- Guest isolation
- Client isolation
- Fast roaming
- Band steering
- Minimum RSSI
- Channel width
- 2.4 GHz vs 5 GHz vs 6 GHz behavior
- Meshing
- RF interference
- Firmware management
- Backups and restore

## Troubleshooting: AP Offline

Check:

- PoE power
- Switch port status
- VLAN/native network
- DHCP lease
- DNS resolution
- Controller reachability
- Inform URL
- Firewall rules between AP and controller
- Recent firmware or network changes

## Troubleshooting: Client Cannot Connect to Wi-Fi

Check:

- SSID enabled
- Password/security mode
- Client compatibility with WPA2/WPA3
- VLAN assignment
- DHCP availability
- RADIUS configuration if used
- Signal strength
- Minimum RSSI settings
- MAC filtering or PPSK rules if used

## Troubleshooting: Client Connects but Has No Network Access

Check:

- VLAN associated with SSID
- Switch trunk to AP
- DHCP scope
- Gateway
- Firewall rules
- DNS resolution
- Client isolation
- Guest portal state

## Troubleshooting: Poor Wi-Fi Performance

Check:

- Channel utilization
- Channel overlap
- Channel width
- AP placement
- Transmit power
- Client signal strength
- Interference
- Roaming behavior
- Wired uplink speed
- Meshing vs wired backhaul

## Preferred Response Pattern

When helping with UniFi, include:

- Where to check in the UniFi Network Application
- What setting or view to inspect
- What the finding means
- Safe proposed change, if needed
- Rollback path
- Warning if a setting may disconnect clients or devices
- Explicit approval request before any change
