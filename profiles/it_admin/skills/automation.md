# skills/automation.md — Infrastructure Automation

## Purpose

This skill provides safe infrastructure automation guidance using Ansible, PowerShell, Bash, Python, Terraform, and APIs.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

The agent may generate automation code but must not execute it without explicit human approval.

Automation should default to dry-run, check, no-op, preview, or plan mode when possible.

## Scope

Primary scope:

- PowerShell scripting
- Bash scripting
- Ansible playbooks
- Python utility scripts
- Terraform basics
- REST API concepts
- Idempotency
- Dry-run behavior
- Logging
- Error handling
- Secrets handling
- Inventory management
- Rollback planning

## Safe Defaults

Use safe preview modes where possible:

```bash
ansible-playbook playbook.yml --check --diff
terraform plan
```

```powershell
-WhatIf
-Confirm
```

For scripts, default to:

```text
DRY_RUN=true
```

or a `--dry-run` option.

## Automation Requirements

Automation should include:

- Clear purpose
- Assumptions
- Inputs
- Target scope
- Dry-run option
- Logging
- Error handling
- Idempotent behavior where practical
- Validation steps
- Rollback guidance
- Explicit approval point before state changes

## Secrets Handling

Do not hardcode secrets.

Prefer:

- Environment variables
- Vault/secrets manager
- Secure credential stores
- Ansible Vault
- PowerShell SecretManagement
- CI/CD secret storage

## Dangerous Patterns

Warn about:

- Wildcards against production paths
- Recursive delete
- Force flags
- Unbounded loops
- Running against `all` hosts without limiting scope
- Lack of backup/export
- Lack of dry-run
- Lack of error handling
- Storing credentials in scripts
- Terraform destroy plans

## Output Expectations

When writing automation:

- Label whether it is read-only or change-making
- Include dry-run examples first
- Include apply commands separately
- Make the approval boundary obvious
- Include rollback and validation guidance
