#!/usr/bin/env python3
"""Install the 'AIAMSBS Dashboard Backup' Hermes cron job.

Idempotent: skips if a job with the same name already exists.
Also removes the legacy /etc/cron.d/aiamsbs-dashboard-backup system cron
if present (it ran the same script via system cron before the migration).

Usage: install_dashboard_backup_hermes_cron.py <hermes_home> <profile>
  hermes_home: e.g. /home/ansible/.hermes
  profile:     e.g. it_admin
"""
import json
import os
import sys
from pathlib import Path

HERMES_HOME = Path(sys.argv[1])
PROFILE = sys.argv[2]
JOB_NAME = "AIAMSBS Dashboard Backup"
SCHEDULE_EXPR = "0 1 * * *"  # daily at 01:00, same as the old system cron
LEGACY_CRON_FILE = Path("/etc/cron.d/aiamsbs-dashboard-backup")

jobs_file = HERMES_HOME / "cron" / "jobs.json"

# Load existing jobs (or empty list if file missing/malformed)
try:
    data = json.loads(jobs_file.read_text())
except (FileNotFoundError, json.JSONDecodeError):
    data = {"jobs": []}

# Idempotency: skip if a job with the same name already exists
existing = next((j for j in data.get("jobs", []) if j.get("name") == JOB_NAME), None)
if existing is not None:
    print(f"[skip] cron job {JOB_NAME!r} already exists (id={existing.get('id')})")
    print(f"       state={existing.get('state')!r} schedule={existing.get('schedule_display')!r}")
else:
    # Build the new job. The shape mirrors the existing jobs in jobs.json
    # (see ~/.hermes/cron/jobs.json for reference). The prompt is a thin
    # wrapper around the existing backup-dashboards.sh — the script is
    # the workhorse, the agent is a thin wrapper that provides logging.
    new_job = {
        "id": f"aiamsbs-backup-{PROFILE}",  # stable, deterministic for idempotency re-runs
        "name": JOB_NAME,
        "prompt": (
            "You are running the AIAMSBS dashboard backup cron job. "
            "Execute this script and report the result:\n\n"
            f"    {HERMES_HOME}/scripts/backup-dashboards.sh\n\n"
            "The script backs up every Grafana dashboard to "
            "~/backups/dashboard-backup-<timestamp>.tar.gz. Exit code 0 = success. "
            "If exit code is non-zero, capture the last 20 lines of stderr and "
            "the exit code in your report. Otherwise report the archive path, size, "
            "and dashboard count from the script's stdout."
        ),
        "skills": [f"{PROFILE}/dashboard-backup"],
        "skill": None,
        "model": None,
        "provider": None,
        "base_url": None,
        "script": None,
        "no_agent": False,
        "context_from": None,
        "schedule": {"kind": "cron", "expr": SCHEDULE_EXPR, "display": SCHEDULE_EXPR},
        "schedule_display": SCHEDULE_EXPR,
        "repeat": {"times": None, "completed": 0},
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
        # Origin/deliver intentionally NOT set. The user will configure a
        # messaging service later (per Telegram 2026-07-03). With no
        # deliver target, the cron still runs and the result is logged
        # in jobs.json's last_status / last_error fields, but no Telegram
        # ping fires. Once the user configures --deliver, re-run bootstrap
        # to update.
        "deliver": None,
        "origin": None,
        "enabled_toolsets": None,
        "workdir": str(HERMES_HOME.parent),  # the user's HOME, e.g. /home/ansible
        "profile": PROFILE,
    }
    data.setdefault("jobs", []).append(new_job)
    jobs_file.write_text(json.dumps(data, indent=2, sort_keys=False))
    jobs_file.chmod(0o600)
    print(f"[ok] installed cron job {JOB_NAME!r} (id={new_job['id']}, profile={PROFILE}, schedule={SCHEDULE_EXPR})")

# Remove the legacy system cron if present
if LEGACY_CRON_FILE.exists():
    try:
        LEGACY_CRON_FILE.unlink()
        print(f"[ok] removed legacy system cron: {LEGACY_CRON_FILE}")
    except PermissionError:
        # bootstrap.sh runs as the install user; cron.d/ is root-owned.
        # Caller (bootstrap.sh) wraps this script with sudo if needed,
        # or runs as root in the bootstrap context. If we can't write,
        # surface the error so the operator can clean up manually.
        print(f"[warn] could not remove {LEGACY_CRON_FILE} (permission denied); remove manually with sudo")
        sys.exit(2)
else:
    print(f"[skip] no legacy system cron at {LEGACY_CRON_FILE}")
