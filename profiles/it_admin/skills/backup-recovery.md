# skills/backup-recovery.md — Backup and Recovery

## Purpose

This skill provides backup, restore, and recovery planning guidance for infrastructure systems.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from `soul.md`.

Backup status checks and restore planning are read-only.

Changing backup jobs, retention, repositories, schedules, encryption, exclusions, or deleting backups requires explicit human approval.

Actual restore actions require explicit human approval.

## Scope

Primary scope:

- Backup strategy
- Restore planning
- Recovery point objective
- Recovery time objective
- Backup validation
- Immutable backups
- Offline/offsite copies
- File restores
- VM restores
- Application-aware backups
- AD recovery considerations
- Backup repository health
- Retention policy review

## Core Principles

- Backups must be restorable
- Snapshots are not backups
- Retention must match business need
- Backups should be protected from ransomware
- Critical systems need documented restore procedures
- Restore testing should be scheduled and documented

## Recovery Planning Template

```markdown
# Recovery Plan

## System

## Business Function

## Dependencies

## Backup Source

## Last Known Good Backup

## RPO

## RTO

## Restore Method

## Validation Steps

## Rollback/Abort Conditions

## Communication Plan
```

## High-Risk Actions

Treat as high-risk:

- Deleting backups
- Reducing retention
- Disabling backup jobs
- Changing repositories
- Changing encryption
- Restoring over production
- Restoring domain controllers
- Restoring databases
- Restoring vCenter or identity systems

## Output Expectations

When helping with backup/recovery:

- Confirm restore objective
- Identify target and destination
- Avoid overwriting production without explicit approval
- Include validation steps
- Include fallback plan
