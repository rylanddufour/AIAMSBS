# skills/monitoring-observability.md — Monitoring and Observability

## Purpose

This skill provides infrastructure monitoring and observability guidance for servers, networks, VMware, services, logs, metrics, traces, and alerts.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Viewing metrics, logs, dashboards, and alerts is read-only.

Changing alert rules, agents, collectors, retention, dashboards, notification routes, or integrations requires explicit human approval.

## Scope

Primary scope:

- Infrastructure monitoring
- Metrics
- Logs
- Traces at a conceptual level
- Alerting
- Dashboards
- SNMP
- Syslog
- Windows Event Logs
- Linux journald/syslog
- vSphere alarms
- Network device telemetry
- Availability checks
- Capacity planning

## Monitoring Categories

Track:

- Availability
- Latency
- Errors
- Saturation
- CPU
- Memory
- Disk
- Network
- Storage latency
- Packet loss
- Interface errors
- Authentication failures
- Backup success/failure
- Certificate expiration
- Service health

## Alert Quality Rules

Good alerts should be:

- Actionable
- Routed to the right owner
- Low-noise
- Severity-based
- Suppressed during maintenance
- Linked to runbooks where possible

## Output Expectations

When helping with monitoring:

- Identify what to measure
- Explain why it matters
- Suggest thresholds carefully
- Include dashboard ideas
- Include alert routing considerations
- Require approval before changing collectors or alert rules
