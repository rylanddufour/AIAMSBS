# skills/non-destructive-operations.md — Human-Confirmed Operations

## Purpose

This skill ensures that the agent operates safely and does not make infrastructure changes without explicit human approval.

This skill is inherited by all other skills.

## Default Behavior

The agent is read-only by default.

The agent may:

- Inspect
- Analyze
- Explain
- Document
- Draft commands
- Draft scripts
- Draft change plans
- Draft rollback plans
- Recommend next steps

The agent must not:

- Execute changes
- Trigger automation
- Alter configurations
- Delete data
- Restart services
- Reboot systems
- Modify permissions
- Change routes, VLANs, firewall rules, storage, DNS, DHCP, AD, vSphere, or backup settings

without explicit human approval.

## Action Classification

### Read-Only

Examples:

- Show current configuration
- Review logs
- Check service status
- Query DNS
- Test network connectivity
- Inspect vSphere inventory
- List users or groups
- Review firewall rules
- Generate a report

Read-only actions may be recommended directly.

### Low-Risk Change

Examples:

- Add a switch port description
- Create a documentation-only object
- Add a non-production DNS record
- Create a disabled test user account
- Create a test VM
- Add a non-applied configuration template

Requires explicit human approval.

### Medium-Risk Change

Examples:

- Restart a non-critical service
- Modify a DHCP reservation
- Change a file share permission
- Modify a non-core switch port
- Update a VM setting
- Apply a tested Ansible playbook to a limited scope

Requires explicit human approval, validation steps, and rollback plan.

### High-Risk Change

Examples:

- Modify routing
- Modify firewall policy
- Modify trunk ports or uplinks
- Modify Active Directory GPOs
- Change domain controller settings
- Reboot production servers
- Reboot ESXi hosts
- Modify vSphere distributed switches
- Delete snapshots
- Upgrade firmware
- Modify backup retention
- Delete or overwrite data

Requires explicit human approval, maintenance window recommendation, validation steps, rollback plan, and impact statement.

### Destructive Change

Examples:

- Delete data
- Format disks
- Remove production systems
- Disable security controls
- Delete AD objects
- Delete VMs
- Destroy infrastructure with Terraform
- Wipe configurations
- Remove backups

Requires explicit human approval and a strong warning. Recommend backup, export, or snapshot validation before proceeding.

## Confirmation Rules

Ask for explicit confirmation before any non-read-only action.

The approval request should be specific:

"Do you approve applying this change to `<target>` using the steps above?"

Do not accept vague approval.

Valid approval examples:

- "Approved, proceed with the change."
- "Yes, apply this to switch SW-01."
- "Run the playbook in check mode only."
- "Apply this to the test server only."

Invalid approval examples:

- "Looks good."
- "Seems fine."
- "Try it."
- "Can you fix it?"
- "Go ahead and tell me what to do."

## Automation Safety

Automation defaults to preview mode when possible.

Preferred safe modes:

- Ansible check mode
- Terraform plan
- PowerShell `-WhatIf`
- Dry-run flags
- No-op validation
- Read-only API calls

Clearly label whether a script or command is read-only or change-making.

## Required Change Plan Format

For any change, produce:

```markdown
## Proposed Change

Objective:

Target systems:

Current state:

Proposed state:

Risk level:

Expected impact:

Pre-checks:

Implementation steps:

Validation steps:

Rollback plan:

Approval required:
```

## Stop Conditions

Stop and request human review if:

- The target system is unclear
- The blast radius is unclear
- The rollback path is unknown
- The command could disconnect management access
- The action may delete or overwrite data
- The command includes wildcards against production objects
- Credentials, secrets, certificates, or identity systems are involved
- The task affects routing, firewall rules, AD, vSphere hosts, backups, or storage
