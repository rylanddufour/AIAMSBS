# skills/troubleshooting-methodology.md — Infrastructure Troubleshooting Method

## Purpose

This skill provides a consistent troubleshooting framework across networking, Linux, Windows, Active Directory, DNS/DHCP, file services, vSphere, and automation.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Troubleshooting should begin with read-only checks.

## Troubleshooting Sequence

1. Define the problem.
2. Identify the user or system impact.
3. Determine blast radius.
4. Identify what changed.
5. Establish timeline.
6. Confirm whether the issue is reproducible.
7. Separate symptoms from causes.
8. Test one layer or dependency at a time.
9. Prefer low-risk validation steps.
10. Document findings and next actions.

## Layered Investigation Model

When troubleshooting infrastructure, evaluate:

1. Physical or virtual attachment
2. Link state
3. VLAN or network segment
4. IP addressing
5. Routing
6. Firewall or ACL policy
7. DNS resolution
8. Time synchronization
9. Authentication
10. Authorization
11. Service state
12. Application behavior
13. Storage or resource contention
14. Recent changes
15. Logs and telemetry

## Output Format

When diagnosing an issue, provide:

- Problem summary
- Likely failure domains
- Read-only validation checks
- What each check proves
- Risk-free next steps
- Proposed remediation plan if evidence supports it
- Rollback plan for any proposed change
- Questions that materially affect safety or accuracy

## Evidence Standard

Do not conclude without evidence.

Use language such as:

- "This suggests..."
- "This points toward..."
- "This does not yet prove..."
- "The next check should confirm..."

Avoid overstating certainty.

## Escalation Criteria

Escalate or request human review when:

- Multiple production services are affected
- Root cause is unclear
- A change may increase outage impact
- Data loss is possible
- Identity, routing, firewall, storage, or hypervisor layers are implicated
- Logs suggest security compromise
