#!/usr/bin/env python3
"""Install the 'AIAMSBS Inventory Discovery' Hermes cron job.

Idempotent: skips if a job with the same name already exists.
No legacy system cron to clean up (this cron was added in
BACKLOG #39.6 — there was no pre-existing /etc/cron.d entry to migrate).

Usage: install_inventory_discovery_hermes_cron.py <hermes_home> <profile>
  hermes_home: e.g. /home/ansible/.hermes
  profile:     e.g. it_admin

The cron fires daily at 02:00 local and runs the inventory discovery
end-to-end:
  1. discover.py --auto-detect-subnet   (scan the customer's local subnet)
  2. regenerate_blackbox.py             (rewrite blackbox exporter targets)
  3. curl POST /-/reload                 (Prom picks up new blackbox targets)

The discover.py step handles subnet auto-detection internally (it
figures out the primary interface's CIDR + default gateway), so the
agent prompt does not need to pre-detect the subnet.
"""
import json
import sys
from pathlib import Path

HERMES_HOME = Path(sys.argv[1])
PROFILE = sys.argv[2]
JOB_NAME = "AIAMSBS Inventory Discovery"
SCHEDULE_EXPR = "0 2 * * *"  # daily at 02:00 local, after the 01:00 backup
JOB_ID = f"inventory-discovery-{PROFILE}"  # stable, deterministic for idempotency re-runs

jobs_file = HERMES_HOME / "cron" / "jobs.json"

# Load existing jobs (or empty list if file missing/malformed)
try:
    data = json.loads(jobs_file.read_text())
except (FileNotFoundError, json.JSONDecodeError):
    data = {"jobs": []}

# Idempotency: skip if a job with the same id already exists.
# We match on the deterministic id (not the human name) so a re-run with
# a different PROFILE is treated as a separate job, but a re-run with the
# same PROFILE on the same HERMES_HOME is a no-op.
existing = next((j for j in data.get("jobs", []) if j.get("id") == JOB_ID), None)
if existing is not None:
    print(f"[skip] cron job {JOB_NAME!r} already exists (id={existing.get('id')})")
    print(f"       state={existing.get('state')!r} schedule={existing.get('schedule_display')!r}")
else:
    # Build the new job. Shape mirrors the existing AIAMSBS Backup job
    # in jobs.json. The prompt is self-contained — the cron fires at
    # 02:00 with no prior context, so the prompt must spell out the
    # three steps and the expected exit semantics. discover.py's
    # --auto-detect-subnet handles subnet discovery internally; the
    # prompt does NOT pre-detect the subnet.
    new_job = {
        "id": JOB_ID,
        "name": JOB_NAME,
        "prompt": (
            "You are running the AIAMSBS inventory discovery cron job.\n\n"
            "Execute these steps and report the result. The discover.py step\n"
            "handles subnet auto-detection internally — you don't need to\n"
            "figure out the subnet yourself.\n\n"
            "  1. Run the discovery:\n"
            f"       {HERMES_HOME}/skills/inventory-discovery/scripts/discover.py \\\n"
            "         --auto-detect-subnet --timeout 600\n\n"
            "  2. Regenerate the blackbox inventory targets file:\n"
            f"       {HERMES_HOME}/profiles/{PROFILE}/scripts/regenerate_blackbox.py\n\n"
            "  3. Trigger Prometheus reload:\n"
            "       curl -sf -XPOST http://localhost:9090/-/reload || true\n\n"
            "Report: devices found, inserted vs updated, blackbox targets\n"
            "written, Prom reload status. Exit 0 if all three steps\n"
            "completed, 1 otherwise."
        ),
        "skills": [f"{PROFILE}/inventory-discovery"],
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
        "deliver": None,
        "origin": None,
        "enabled_toolsets": None,
        "workdir": str(HERMES_HOME.parent),  # the user's HOME, e.g. /home/ryland
        "profile": PROFILE,
    }
    data.setdefault("jobs", []).append(new_job)
    jobs_file.write_text(json.dumps(data, indent=2, sort_keys=False))
    jobs_file.chmod(0o600)
    print(f"[ok] installed cron job {JOB_NAME!r} (id={new_job['id']}, profile={PROFILE}, schedule={SCHEDULE_EXPR})")
