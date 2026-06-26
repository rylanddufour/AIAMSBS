---
name: apt-history-analyzer
title: APT/Dpkg/YUM History Analyzer
description: Parse the package-manager history on a Linux Managed device and return a structured install/upgrade/remove timeline. Triggered when the user asks what was installed, upgraded, or removed on a Linux box.
trigger: When the user asks "what was installed yesterday on web-01?", "did anyone run apt upgrade?", "when did package X get installed?", or asks about package-history on a Linux Managed device.
---

# APT History Analyzer

Parse `/var/log/apt/history.log` + `/var/log/dpkg.log` (Debian/Ubuntu) or
`dnf history list` / `yum history` (RHEL-family) on a Managed device and
return a structured timeline of install/upgrade/remove/purge events.

## When to use this skill

Trigger this skill when the user says any of:

- "What got installed on `<host>` yesterday?"
- "Did anyone run `apt upgrade` last night?"
- "When did package X get installed?"
- "Why did the apt mirror change?"
- "Show me the last 10 upgrades on `<host>`"

## How to use it

1. **Extract the host** from the prompt. If the user didn't specify one,
   default to `localhost` (the AIAMSBS host itself — that's what linux_admin
   owns by default; managed devices need SSH, which is future work).

2. **Run the analyzer script**:
   ```bash
   $APT_HISTORY_DIR/scripts/apt-history-analyzer.py [--since DAYS] [--limit N]
   ```
   `$APT_HISTORY_DIR` is the directory this SKILL.md lives in.

3. **Report the summary** the script prints back (event count, top packages,
   recent events).

## What the script does

`scripts/apt-history-analyzer.py`:

1. **Auto-detects** the package manager:
   - Debian/Ubuntu: reads `/var/log/apt/history.log` + rotated
     `history.log.*.gz` (up to 5 rotations) + `/var/log/dpkg.log` + rotated.
   - RHEL-family: runs `dnf history list` (falls back to `yum history`).
2. **Parses each event** into `{timestamp, command, requested_by,
   packages: [{op, name, arch, versions, automatic}]}`.
3. **Filters** by `--since DAYS` (last N days) and `--limit N` (cap events).
4. **Sorts** events newest-first.
5. **Summarizes** ops breakdown (`install`, `upgrade`, `remove`, etc.) +
   top 10 most-touched packages.
6. **Prints JSON** to stdout (Hermes-parsable). Human summary on stderr.

## Defaults

| Knob | Default | Override |
|---|---|---|
| Source | `auto` (apt → dpkg → rhel) | `--source {auto,apt,dpkg,rhel}` |
| Since (days) | unlimited | `--since 7` |
| Limit | unlimited | `--limit 20` |
| Target host | `localhost` | `--target HOST` (v1: only `localhost` accepted; exit 1 otherwise) |

## Output shape

```json
{
  "target": "localhost",
  "sources": ["apt", "dpkg"],
  "files_read": ["/var/log/apt/history.log", "..."],
  "event_count": 42,
  "summary": {
    "total_events": 42,
    "ops_breakdown": {"upgrade": 30, "install": 12},
    "top_packages": {"libc6": 3, "...": 0}
  },
  "events": [
    {
      "timestamp": "2026-06-25 06:57:52",
      "command": "apt upgrade -y",
      "requested_by": "root",
      "source": "apt",
      "packages": [{"op": "upgrade", "name": "libc6", "arch": "amd64", "versions": ["2.39-..."]}]
    }
  ]
}
```

## Out of scope (v1)

- **SSH to managed devices** — script exits 1 if `--target` is not
  `localhost`. SSH support is future work (BACKLOG #16 follow-on).
- **Continuous monitoring** — one-shot read. For periodic scans, wrap in
  cron (future).
- **Mutation** — read-only. The script never runs `apt install`, `yum
  remove`, etc. The Agent reads the timeline and proposes changes; the
  Customer approves separately.
- **Non-Debian/RHEL distros** — Alpine, Arch, etc. would need additional
  parsers (future).

## Version

- Added: 2026-06-26 (Task: implement linux_admin Skills)
- Status: v1, localhost-only
- Depends on: `linux_admin` profile (commit 7ed5720+)