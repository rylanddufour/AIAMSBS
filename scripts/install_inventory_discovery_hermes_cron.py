#!/usr/bin/env python3
"""Install the 'AIAMSBS Inventory Discovery' Hermes cron job.

Idempotent: matches existing jobs by ``name`` (not ``id``) so that
upgrades from the older ``inventory-discovery-it_admin`` id layout (when
crons were mistakenly tagged with the it_admin profile name in their
metadata) get rewritten in place rather than creating duplicates.

No legacy system cron to clean up (this cron was added in
BACKLOG #39.6 — there was no pre-existing /etc/cron.d entry to migrate).

Usage: install_inventory_discovery_hermes_cron.py <hermes_home> [<profile>]
  hermes_home: e.g. /home/ansible/.hermes
  profile:     legacy arg, ignored. The cron always runs under the
               default profile because Hermes cron scheduler is the
               default-profile process (HERMES_HOME=~/.hermes). The
               ``profile`` field stored on the job is metadata only.

The cron fires daily at 02:00 local and runs the inventory discovery
end-to-end:
  1. discover.py --auto-detect-subnet   (scan the customer's local subnet)
  2. python3 regenerate_blackbox.py     (rewrite blackbox exporter targets)
  3. curl POST /-/reload                 (Prom picks up new blackbox targets)

The discover.py step handles subnet auto-detection internally (it
figures out the primary interface's CIDR + default gateway), so the
agent prompt does not need to pre-detect the subnet.

Step 2 invokes the script via ``python3`` explicitly so the script does
not need to be marked executable. The repo file lives at
``~/AIAMSBS/profiles/it_admin/scripts/regenerate_blackbox.py`` (mode
``-rw-rw-r--`` — no execute bit). Running it via the interpreter avoids
the Permission denied exit code 126 that bash returns when trying to
exec a non-executable file.
"""
import json
import sys
from pathlib import Path

HERMES_HOME = Path(sys.argv[1])
# Second positional arg is legacy (used to be the profile name). Ignored.
# We hardcode "default" because that's where the cron actually runs.
JOB_NAME = "AIAMSBS Inventory Discovery"
JOB_ID = "inventory-discovery"  # stable, deterministic for idempotency re-runs
PROFILE = "default"  # metadata only; cron scheduler runs under default profile
SCHEDULE_EXPR = "0 2 * * *"  # daily at 02:00 local, after the 01:00 backup

jobs_file = HERMES_HOME / "cron" / "jobs.json"

# Load existing jobs (or empty list if file missing/malformed)
try:
    data = json.loads(jobs_file.read_text())
except (FileNotFoundError, json.JSONDecodeError):
    data = {"jobs": []}

# Idempotency: match by ``name``. If an existing job has the same name
# (regardless of id), update it in place so we don't end up with two
# inventory-discovery crons after a re-bootstrap. Preserve schedule
# state (state, next_run_at, last_run_at, last_status, executions.db
# linkage) by updating the existing record in place.
new_prompt = (
    "You are running the AIAMSBS inventory discovery cron job.\n\n"
    "Execute these steps and report the result. The discover.py step\n"
    "handles subnet auto-detection internally — you don't need to\n"
    "figure out the subnet yourself.\n\n"
    "  1. Run the discovery:\n"
    f"       {HERMES_HOME}/skills/inventory-discovery/scripts/discover.py \\\n"
    "         --auto-detect-subnet --timeout 600\n\n"
    "  2. Regenerate the blackbox inventory targets file:\n"
    "       python3 $HOME/AIAMSBS/profiles/it_admin/scripts/regenerate_blackbox.py\n\n"
    "  3. Trigger Prometheus reload:\n"
    "       curl -sf -XPOST http://localhost:9090/-/reload || true\n\n"
    "Report: devices found, inserted vs updated, blackbox targets\n"
    "written, Prom reload status. Exit 0 if all three steps\n"
    "completed, 1 otherwise."
)
new_skills = ["inventory-discovery"]

existing = next((j for j in data.get("jobs", []) if j.get("name") == JOB_NAME), None)
if existing is not None:
    # Update in place. Preserve schedule state. Bump id if the existing
    # job still carries the old "inventory-discovery-it_admin" id (legacy).
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
    # Build the new job. Shape mirrors the existing AIAMSBS Backup job
    # in jobs.json. The prompt is self-contained — the cron fires at
    # 02:00 with no prior context, so the prompt must spell out the
    # three steps and the expected exit semantics. discover.py's
    # --auto-detect-subnet handles subnet discovery internally; the
    # prompt does NOT pre-detect the subnet.
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
