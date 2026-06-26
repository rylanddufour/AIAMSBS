---
name: systemd-journal-search
title: Systemd Journal Search
description: Run structured journalctl queries against a Linux Managed device with safe flag handling. Triggered when the user asks about logs from a systemd service.
trigger: When the user asks "show me logs for service X", "what does this journal error mean?", "filter logs from host Y for OOM since boot", or wants structured journal access on a Linux Managed device.
---

# Systemd Journal Search

Run structured `journalctl` queries against a Managed device with safe
flag handling. Returns filtered entries as JSON so the Agent can correlate
them with other evidence (e.g. apt history, service status).

## When to use this skill

Trigger this skill when the user says any of:

- "Show me the last 100 lines of `<svc>` from 2 a.m. last night."
- "Filter `<host>` logs for `OOM` since the boot."
- "What does this journal error mean?"
- "Did service X crash? When?"
- "Find all `err`-level entries for `<unit>` today."

## How to use it

1. **Extract filters** from the prompt — `--since`, `--until`, `--unit`,
   `--priority`, `--regex`, `--boot`, etc. If the user just says "show me
   the logs", default to `--since "1 hour ago" --priority err`.

2. **Run the journal search script**:
   ```bash
   $JOURNAL_DIR/scripts/systemd-journal-search.py \
       --unit hermes-dashboard --since "1 hour ago" --priority err
   ```
   `$JOURNAL_DIR` is the directory this SKILL.md lives in.

3. **Report the summary** + the most relevant entries.

## What the script does

`scripts/systemd-journal-search.py`:

1. **Calls `journalctl`** with the requested flags + `--no-pager -o json`
   so output is machine-parseable.
2. **Parses each entry** into `{timestamp, priority, unit, pid, uid,
   syslog_identifier, message}`.
3. **Sorts** newest-first.
4. **Limits** to `--limit N` (default 100).
5. **Summarizes** priority breakdown + top units.
6. **Prints JSON** to stdout. Human summary on stderr.

## Defaults

| Knob | Default | Override |
|---|---|---|
| Limit | 100 entries | `--limit 500` |
| Target host | `localhost` | `--target HOST` (v1: only `localhost` accepted; exit 1 otherwise) |
| Sort | newest-first | always |

## Supported filters (subset of journalctl)

| Flag | Maps to |
|---|---|
| `--since STR` | `--since` (e.g. `"1 hour ago"`, `"2026-06-25"`) |
| `--until STR` | `--until` |
| `--unit NAME` | `--unit` (systemd unit) |
| `--priority LEVEL` | `-p` (emerg/alert/crit/err/warning/notice/info/debug) |
| `--boot` | `-b` (only this boot) |
| `--pid N` | `_PID=N` |
| `--uid N` | `_UID=N` |
| `--regex PATTERN` | `--grep` (regex on MESSAGE) |

## Output shape

```json
{
  "target": "localhost",
  "query_args": ["--unit", "hermes-dashboard", "--priority", "err"],
  "entry_count": 5,
  "summary": {
    "total": 5,
    "first_timestamp": "2026-06-26 04:13:12+00:00",
    "last_timestamp": "2026-06-26 04:13:55+00:00",
    "priority_breakdown": {"err": 5},
    "top_units": {"hermes-dashboard.service": 5}
  },
  "entries": [
    {
      "timestamp": "2026-06-26 04:13:55+00:00",
      "priority": "err",
      "unit": "hermes-dashboard.service",
      "pid": 23581,
      "uid": 0,
      "syslog_identifier": "hermes",
      "message": "Auth backend failed: ..."
    }
  ]
}
```

## Out of scope (v1)

- **SSH to managed devices** — script exits 1 if `--target` is not
  `localhost`. SSH support is future work.
- **Boot-id filtering** — `--boot` covers "this boot"; historical boots
  need `--boot=-1` etc. (future).
- **Binary journal access** — script uses `journalctl`; doesn't open
  journal files directly (sufficient for 99% of cases).
- **Mutation** — read-only. The Agent reads entries and proposes changes;
  the Customer approves separately.

## Version

- Added: 2026-06-26 (Task: implement linux_admin Skills)
- Status: v1, localhost-only
- Depends on: `linux_admin` profile, systemd on the target host