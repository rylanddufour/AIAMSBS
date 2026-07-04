# skills/dashboard-backup.md — Grafana dashboard backup

## Purpose

Documents the daily Grafana dashboard backup workflow so the IT_ADMIN agent can run, verify, and troubleshoot it.

## When to use

- When the user asks "are the dashboards being backed up?" / "is the backup running?" / "show me the last backup"
- When a dashboard was modified and the user wants to verify it's in the latest archive
- When the cron job reports a failure and the agent needs to diagnose
- When the user wants to restore a dashboard from a backup (read-only first — restoration still needs explicit human approval per the non-destructive policy)

## The script

`~/.hermes/scripts/backup-dashboards.sh` (installed by `bootstrap.sh install_backup_scripts`, present on every AIAMSBS install).

What it does, in order:
1. Loads the Grafana service account token from `~/.hermes/secrets/grafana-mcp.env` (the same token file the `default` and `it_admin` profiles already read).
2. Calls `GET /api/search?type=dash-db` to enumerate every dashboard.
3. For each dashboard UID, calls `GET /api/dashboards/uid/{uid}` and writes a sanitized JSON copy to a per-uid file.
4. Tarballs everything (dashboards + `MANIFEST.json`) into `~/backups/dashboard-backup-YYYYMMDD-HHMMSS.tar.gz`.
5. Rotates: deletes any `dashboard-backup-*.tar.gz` beyond the most recent 14.

**Exit code:**
- `0` — success (zero or more dashboards exported; manifest written; archive created; rotation applied)
- `1` — token file missing, token is a placeholder, or API call failed catastrophically

**Environment overrides (all optional):**
- `GRAFANA_URL` — default `http://localhost:3000`
- `GRAFANA_TOKEN_FILE` — default `~/.hermes/secrets/grafana-mcp.env`
- `BACKUP_DIR` — default `~/backups`

## How the agent runs it (the cron flow)

The Hermes cron job `AIAMSBS Dashboard Backup` (registered by `bootstrap.sh install_dashboard_backup_hermes_cron`) fires daily at 01:00. Its prompt is a thin wrapper:

> Run `~/.hermes/scripts/backup-dashboards.sh` and report any errors.

The agent:
1. Invokes the script via the terminal tool.
2. Inspects the exit code and the last 10-20 lines of stdout/stderr.
3. If exit code 0, returns a 1-line success summary (archive path + size + dashboard count).
4. If non-zero, returns the error message and the last failing step.

The agent does NOT rewrite the script or implement backup logic in-line. The script is the source of truth; the agent is a thin wrapper that provides logging + delivery.

## The gateway is what ticks the cron

Per `hermes_agent/cron/__init__.py`: *"Cron jobs are executed automatically by the gateway daemon"*. This means the `AIAMSBS Dashboard Backup` entry in `~/.hermes/cron/jobs.json` is **inert until the `hermes-gateway` daemon is running** — registration alone is not enough.

`bootstrap.sh` installs the gateway as a **system-level systemd service** (`sudo hermes gateway install --system --run-as-user <user>`) so it:
- Lives in `/etc/systemd/system/hermes-gateway.service`
- Starts automatically at `multi-user.target` (server boot, independent of any user login)
- Is supervised by systemd (Restart=always; auto-recovers from crashes)

This is the right scope for a headless server. The per-user variant (`hermes gateway install`, no `--system`) only starts on user login and would not survive a reboot of a headless Proxmox VM/CT.

To verify on a live install: `sudo systemctl status hermes-gateway.service` — should show `Active: active (running)`.

## Reading a backup

```bash
# List recent archives
ls -lht ~/backups/dashboard-backup-*.tar.gz | head -5

# Extract one
mkdir /tmp/dash-restore && tar -xzf ~/backups/dashboard-backup-<TS>.tar.gz -C /tmp/dash-restore
ls /tmp/dash-restore/dashboards/   # one .json per dashboard
cat /tmp/dash-restore/MANIFEST.json
```

## Troubleshooting checklist

| Symptom | Likely cause |
|---|---|
| `ERROR: token file not readable: ~/.hermes/secrets/grafana-mcp.env` | Token file missing. Was `create_grafana_mcp_service_account()` ever run? Check `ls -la ~/.hermes/secrets/`. |
| `ERROR: GRAFANA_SERVICE_ACCOUNT_TOKEN missing or placeholder` | Token file exists but is empty or contains a placeholder. Re-run `create_grafana_mcp_service_account()`. |
| `WARN: failed to fetch <uid>, skipping` | One dashboard's JSON is malformed or the API call was rate-limited. The export continues with the other dashboards. Investigate the specific UID separately. |
| No `dashboard-backup-*.tar.gz` files in `~/backups/` | Cron never ran. Check the Hermes cron state: `hermes cron list`, look for `AIAMSBS Dashboard Backup`, check `last_status`. |
| Cron registered in jobs.json with `state: scheduled` and `enabled: true` but never fires | The **hermes-gateway daemon is not running** — it is the daemon that ticks scheduled jobs. Check `sudo systemctl status hermes-gateway.service`; on a fresh install it should be `active (running)`. If `inactive` or `failed`, start it with `sudo systemctl start hermes-gateway.service` and inspect `journalctl -u hermes-gateway.service -n 50` for the cause. |
| `last_status: error` on the cron | Read `last_error` from `~/.hermes/cron/jobs.json` or `hermes cron status <id>`. |
| Archive size much smaller than usual | A dashboard was deleted (or the manifest changed). Compare against the manifest from a prior archive. |

## Non-destructive policy

- Running the backup script is non-destructive (it only writes to `~/backups/` and rotates old archives).
- **Restoring** a dashboard from a backup IS destructive (it overwrites the live dashboard) and requires explicit human approval per the global non-destructive policy in `SOUL.md`.

## Related

- Script: `scripts/backup-dashboards.sh` (the workhorse)
- Service account: `create_grafana_mcp_service_account()` in `bootstrap.sh`
- Cron registration: `install_dashboard_backup_hermes_cron()` in `bootstrap.sh` (replaces the legacy `/etc/cron.d/aiamsbs-dashboard-backup` system cron)
- Gateway (cron scheduler daemon): `install_hermes_gateway_service()` in `bootstrap.sh` — installs the system-level systemd service that ticks the cron
- Legacy system cron: `/etc/cron.d/aiamsbs-dashboard-backup` — removed by the new install on re-bootstrap
