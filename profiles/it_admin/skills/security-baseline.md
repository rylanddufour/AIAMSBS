# skills/security-baseline.md — Infrastructure Security Baseline

## Purpose

This skill provides practical security guidance for datacenter infrastructure administration.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Security reviews and recommendations are read-only.

Changing security controls, authentication, authorization, firewall policy, certificates, MFA, identity providers, service accounts, or audit settings requires explicit human approval.

## Core Principles

- Least privilege
- Role-based access control
- Strong authentication
- MFA where appropriate
- Separate administrative accounts
- Logging and auditability
- Secure management plane
- Patch and vulnerability hygiene
- Backup protection
- Network segmentation
- Secrets management
- Change control

## Insecure Items to Flag

Call out:

- Telnet
- FTP
- SMBv1
- NTLMv1
- Weak TLS/ciphers
- Shared admin accounts
- Local administrator sprawl
- Unrestricted admin shares
- Public management interfaces
- Default credentials
- Flat networks
- Excessive domain admin membership
- Unmonitored service accounts
- Over-permissive file shares
- Disabled logging

## Review Areas

Evaluate:

- Identity and access
- Network segmentation
- Firewall policy
- Remote administration
- Patch status
- Backup and restore
- Logging and monitoring
- Certificate lifecycle
- Secrets handling
- Privileged access

## Output Expectations

When providing security guidance:

- Prioritize practical risk reduction
- Separate findings from recommendations
- Identify operational impact
- Include phased remediation
- Require approval before control changes
