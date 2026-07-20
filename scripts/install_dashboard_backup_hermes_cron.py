#!/usr/bin/env python3
"""Install the 'AIAMSBS Backup' Hermes cron job.

Idempotent: matches existing jobs by ``name`` (not ``id``) so that
upgrades from the older ``aiamsbs-backup-it_admin`` id layout (when
crons were mistakenly tagged with the it_admin profile name in their
metadata) get rewritten in place rather than creating duplicates.

Also removes the legacy /etc/cron.d/aiamsbs-dashboard-backup system
cron if present (it ran the older backup-dashboards.sh via system cron
before the migration to Hermes cron).

Usage: install_dashboard_backup_hermes_cron.py <hermes_home> [<profile>]
  hermes_home: e.g. /home/ansible/.hermes
  profile:     legacy arg, ignored. The cron always runs under the
               default profile because Hermes cron scheduler is the
               default-profile process (HERMES_HOME=~/.hermes). The
               ``profile`` field stored on the job is metadata only.

The file name is kept for backward compatibility with bootstrap.sh callers.
The job it installs was renamed from "AIAMSBS Dashboard Backup" to
"AIAMSBS Backup" when the script scope grew to include the hermes state,
inventory + KB DBs, and Grafana-stack yml configs (not just dashboards).
"""
import json
import os
import sys
from pathlib import Path

HERMES_HOME = Path(sys.argv[1])
# Second positional arg is legacy (used to be the profile name). Ignored.
# We hardcode "default" because that's where the cron actually runs.
JOB_NAME = "AIAMSBS Backup"
JOB_ID = "aiamsbs-backup"  # stable, deterministic for idempotency re-runs
PROFILE = "default"  # metadata only; cron scheduler runs under default profile
SCHEDULE_EXPR = "0 1 * * *"  # daily at 01:00, same as the old system cron
LEGACY_CRON_FILE = Path("/etc/cron.d/aiamsbs-dashboard-backup")

jobs_file = HERMES_HOME / "cron" / "jobs.json"

# Load existing jobs (or empty list if file missing/malformed)
try:
    data = json.loads(jobs_file.read_text())
except (FileNotFoundError, json.JSONDecodeError):
    data = {"jobs": []}

# Idempotency: match by ``name``. If an existing job has the same name
# (regardless of id), update it in place so we don't end up with two
# AIAMSBS Backup crons after a re-bootstrap. Preserve schedule state
# (state, next_run_at, last_run_at, last_status, executions.db linkage)
# by keeping the existing id.
new_prompt = (
    "You are running the AIAMSBS backup cron job. "
    "Execute this script and report the result:\n\n"
    f"    {HERMES_HOME}/scripts/aiamsbs-backup.sh\n\n"
    "The script backs up Grafana dashboards (API + provisioning files), "
    "the hermes state, the inventory + KB SQLite databases, and the "
    "Grafana-stack yml configs into a single tarball at "
    "~/backups/aiamsbs-backup-<timestamp>.tar.gz. Exit code 0 = success. "
    "If exit code is non-zero, capture the last 20 lines of stderr and "
    "the exit code in your report. Otherwise report the archive path, size, "
    "and per-section counts (dashboards exported, dashboards provisioned, "
    "hermes zip bytes, inventory + KB DB bytes) from the script's stdout."
)
new_skills = ["aiamsbs-backup"]

existing = next((j for j in data.get("jobs", []) if j.get("name") == JOB_NAME), None)
if existing is not None:
    # Update in place. Preserve schedule state. Bump id if the existing
    # job still carries the old "aiamsbs-backup-it_admin" id (legacy).
    old_id = existing.get("id", JOB_ID)
    if old_id != JOB_ID:
        print(f"[update] cron job {JOB_NAME!r} (old id={old_id}) — rewriting to id={JOB_ID}")
        print(f"         (the old id is referenced in executions.db and output dir; "
              "they will become orphaned but the new id picks up future runs cleanly)")
    else:
        print(f"[update] cron job {JOB_NAME!r} (id={old_id}) — refreshing prompt/skills/profile")
    existing["id"] = JOB_ID
    existing["skills"] = new_skills
    existing["skill"] = None
    existing["prompt"] = new_prompt
    existing["profile"] = PROFILE
    jobs_file.write_text(json.dumps(data, indent=2, sort_keys=False))
    jobs_file.chmod(0o600)
else:
    # Build the new job. The shape mirrors the existing jobs in jobs.json
    # (see ~/.hermes/cron/jobs.json for reference). The prompt is a thin
    # wrapper around the existing aiamsbs-backup.sh — the script is
    # the workhorse, the agent is a thin wrapper that provides logging.
    new_job = {
        "id": JOB_ID,
        "name": JOB_NAME,
        "prompt": new_prompt,
        "skills": new_skills,
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
