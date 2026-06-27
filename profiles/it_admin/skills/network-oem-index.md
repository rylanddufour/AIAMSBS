# skills/network-oem-index.md — Network OEM Routing

## Purpose

This skill routes network device tasks to the correct OEM-specific skill file.

## Supported OEMs

- Cisco IOS LAN/WAN devices: use `network-oem-cisco-ios.md`
- Ubiquiti UniFi Wi-Fi/network devices: use `network-oem-ubiquiti-unifi.md`
- HPE Aruba LAN/WAN devices: use `network-oem-hpe-aruba.md`

## Decision Rules

If the user mentions Cisco, IOS, Catalyst, ISR, router, switch, or Cisco CLI, use the Cisco IOS skill.

If the user mentions UniFi, Ubiquiti, UDM, Cloud Key, UniFi AP, UniFi switch, UniFi Network, adoption, site, controller, or SSID, use the Ubiquiti UniFi skill.

If the user mentions Aruba, HPE, ProCurve, Aruba CX, Aruba Central, Instant, Instant On, or Aruba switch, use the HPE Aruba skill.

If the user does not specify vendor, ask for vendor, model, and OS/firmware before giving exact commands.

For multi-vendor issues, first explain the vendor-neutral concept, then provide platform-specific implementation guidance.

## Safety Rule

The OEM index does not override the global non-destructive policy. All configuration changes require explicit human approval.
