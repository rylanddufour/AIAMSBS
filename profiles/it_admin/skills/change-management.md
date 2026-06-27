# skills/change-management.md — Infrastructure Change Planning

## Purpose

This skill creates safe, reviewable, human-approved infrastructure change plans.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

All change plans are proposals only until explicitly approved by a human.

## Required Statement

Every change plan must include:

"This is a proposed change plan. No changes should be executed until a human reviews and explicitly approves it."

## Change Plan Template

```markdown
# Change Plan

## Objective

## Scope

## Target Systems

## Assumptions

## Risk Level

## Expected Impact

## Maintenance Window Required

## Backout/Rollback Strategy

## Pre-Checks

## Implementation Steps

## Validation Steps

## Post-Change Monitoring

## Communication Notes

## Approval Required
```

## Risk Levels

### Low

Limited blast radius, easily reversible, no expected user impact.

### Medium

Some user impact possible, rollback available, limited production scope.

### High

Production impact possible, management access risk, identity/routing/firewall/storage/hypervisor involved.

### Critical

Data loss, widespread outage, security control changes, domain-level changes, backup deletion, or irreversible operations possible.

## Change Planning Rules

- Prefer read-only pre-checks.
- Confirm current state before proposed state.
- Include exact commands or UI steps.
- Include validation steps before saving persistent network configuration.
- Include rollback steps before implementation steps for high-risk changes.
- Call out management-plane lockout risk.
- Recommend console or out-of-band access where applicable.
- Recommend backup/export/snapshot where appropriate.

## Approval Language

Use a specific approval request:

"Do you approve this proposed change for `<target>`?"

Do not proceed on vague approval.
