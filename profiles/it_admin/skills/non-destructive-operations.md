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

## Destructive Inventory Operations

The inventory MCP exposes the following destructive tool:

- `delete_device(device_id, cascade_relationships=True)` — permanently
  removes a device row from the inventory database. NOT soft-deleted;
  cannot be undone. By default also removes any rows in
  `device_relationships` where this device is source or target.

**Before invoking any destructive inventory tool, you MUST:**

1. **Search first** — use `search_devices`, `lookup_by_ip`, or
   `lookup_by_hostname` to confirm exactly which device the user means.
   If the search returns multiple matches, show them to the user and ask
   which one to act on. If zero matches, ask the user for the exact
   `device_id` or IP.
2. **Show the user what you found** — display the matching row
   (device_id, hostname, ip_address, vendor, device_type) so they can
   confirm it is the right asset.
3. **Wait for explicit confirmation** — ask the user to confirm before
   calling the destructive tool. Never infer confirmation from prior
   context. Phrase the confirmation clearly, e.g.:
   > "I found this device: dev-server-101 / 192.168.0.110 / Dell /
   > server. Confirm deletion? (yes/no)"
4. **Report the result** — after deletion, show the user the
   `deleted_record` field so they have a record of what was removed.

**Example user flow:**

> User: "Remove server 101 from inventory."
>
> Agent:
>   1. Call `search_devices(query="101")` → finds dev-server-101.
>   2. Reply: "I found: dev-server-101 (192.168.0.110, Dell, server).
>      Confirm deletion?"
>   3. (User: "yes")
>   4. Call `delete_device(device_id="dev-server-101")`.
>   5. Reply: "Deleted dev-server-101. Removed 1 device row."

**Never:**

- Skip the confirmation step, even if the user's prompt seems unambiguous.
- Delete multiple devices in one call. Confirm each separately.
- Fabricate a `device_id` to call `delete_device` with — if search
  returned nothing, ask the user for the exact id.
