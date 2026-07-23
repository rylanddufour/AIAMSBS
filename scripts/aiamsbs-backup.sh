#!/usr/bin/env bash
# aiamsbs-backup.sh
# Comprehensive AIAMSBS stack backup for disaster recovery.
#
# Captures, in one tarball:
#   1. Grafana dashboards — via the Grafana API (catches UI edits)
#   2. Grafana dashboards — provisioning source files from
#      ~/AIAMSBS/config/grafana/provisioning/dashboards/ (catches provisioning
#      source-of-truth, including metadata like uid, datasource refs)
#   3. Hermes state — single zip via `hermes backup` (covers ~/.hermes minus
#      the agent codebase: profiles, sessions, kanban, cron jobs, .env, etc.)
#   4. Inventory MCP SQLite database (via sqlite3 .backup + docker cp)
#   5. KB MCP SQLite database (same pattern)
#   5b. Vaultwarden SQLite database (BACKLOG #48, sqlite3 .backup + docker cp)
#   6. Grafana-stack yml configs (alloy, blackbox, loki, prometheus, promtail,
#      datasources, dashboards.yml provisioning config)
#
# Excluded intentionally:
#   - Loki chunks + Prometheus TSDB — backed up by their own retention
#     mechanisms (BACKLOG #5 covers Loki; Prometheus snapshot API for metrics)
#   - hermes-agent code — installable from PyPI; not customer state
#   - Docker volumes for grafana-data / loki / prometheus — service-level
#
# Output: ~/backups/aiamsbs-backup-YYYYMMDD-HHMMSS.tar.gz
# Retention: last 14 daily backups (rotated)
#
# Cron: 0 1 * * *   (daily at 01:00, fired by the AIAMSBS Backup Hermes cron job)
# Run as: the AIAMSBS install user (e.g. ansible). hermes and docker must be on PATH.

set -euo pipefail

# Ensure the user-local bin (where `hermes` and `pip --user` installs land) is
# on PATH. System crons and the hermes-gateway systemd unit don't always
# source the user's profile, so the cron job's script needs to do it.
export PATH="$HOME/.local/bin:$PATH"

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
TOKEN_FILE="${GRAFANA_TOKEN_FILE:-$HOME/.hermes/secrets/grafana-mcp.env}"
AIAMSBS_DIR="${AIAMSBS_DIR:-$HOME/AIAMSBS}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP="${KEEP:-14}"
TS="$(date -u +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
ARCHIVE="$BACKUP_DIR/aiamsbs-backup-${TS}.tar.gz"

mkdir -p "$BACKUP_DIR" \
         "$WORK/dashboards" \
         "$WORK/dashboards-provisioned" \
         "$WORK/config" \
         "$WORK/db" \
         "$WORK/hermes"
trap 'rm -rf "$WORK"' EXIT

log() { echo "[$(date -Is)] $*"; }
fail() { log "ERROR: $*"; exit 1; }

# ===== Load Grafana service account token (shared with the agent profiles) =====
[ -r "$TOKEN_FILE" ] || fail "token file not readable: $TOKEN_FILE (create_grafana_mcp_service_account creates it)"
# shellcheck disable=SC1090
. "$TOKEN_FILE"
GRAFANA_TOKEN="${GRAFANA_SERVICE_ACCOUNT_TOKEN:-}"
[ -n "$GRAFANA_TOKEN" ] && [[ "$GRAFANA_TOKEN" != *...* ]] \
    || fail "GRAFANA_SERVICE_ACCOUNT_TOKEN missing or placeholder in $TOKEN_FILE"

api() { curl -fsS -H "Authorization: Bearer $GRAFANA_TOKEN" -H 'Accept: application/json' "$@"; }

# ===== 1. Grafana dashboards — API export (captures customer UI edits) =====
log "Exporting dashboards from $GRAFANA_URL (API)"
SEARCH_JSON="$(api "${GRAFANA_URL}/api/search?type=dash-db&limit=5000")"
API_COUNT=$(printf '%s' "$SEARCH_JSON" | grep -o '"uid":"' | wc -l)
log "  found $API_COUNT dashboard(s) via API"
EXPORTED=0
for uid in $(printf '%s' "$SEARCH_JSON" | grep -o '"uid":"[^"]*"' | sed 's/"uid":"//;s/"//g'); do
    RAW="$(api "${GRAFANA_URL}/api/dashboards/uid/${uid}" 2>/dev/null)" || {
        log "  WARN: failed to fetch $uid via API, skipping"
        continue
    }
    SLUG=$(printf '%s' "$RAW" | python3 -c "
import sys, json
d = json.load(sys.stdin)['dashboard']
print(d.get('slug') or d.get('uid') or 'unknown')
" 2>/dev/null || echo "$uid")
    SLUG="$(printf '%s' "$SLUG" | tr -c '[:alnum:]._-' '-' | head -c 64)"
    OUT="$WORK/dashboards/${SLUG}__${uid}.json"
    printf '%s' "$RAW" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(json.dumps(d.get('dashboard', d), indent=2, sort_keys=True))
" > "$OUT" 2>/dev/null \
        || { log "  WARN: failed to write $uid, skipping"; continue; }
    EXPORTED=$((EXPORTED + 1))
done
log "  exported $EXPORTED dashboard(s) via API"

# ===== 2. Grafana dashboards — provisioning source files =====
if [ -d "$AIAMSBS_DIR/config/grafana/provisioning/dashboards" ]; then
    cp "$AIAMSBS_DIR/config/grafana/provisioning/dashboards"/*.json \
       "$WORK/dashboards-provisioned/" 2>/dev/null || true
    PROV_COUNT=$(ls -1 "$WORK/dashboards-provisioned"/*.json 2>/dev/null | wc -l)
    log "Copied $PROV_COUNT provisioning dashboard(s) from filesystem"
else
    PROV_COUNT=0
    log "WARN: $AIAMSBS_DIR/config/grafana/provisioning/dashboards not found"
fi

# ===== 3. Hermes state =====
if command -v hermes >/dev/null 2>&1; then
    log "Running hermes backup (covers ~/.hermes)"
    if hermes backup --output "$WORK/hermes/backup.zip" 2>>"$WORK/hermes.err"; then
        HERMES_SIZE=$(stat -c%s "$WORK/hermes/backup.zip" 2>/dev/null || echo 0)
        log "  hermes backup: $HERMES_SIZE bytes"
    else
        log "  WARN: hermes backup failed (see $WORK/hermes.err); continuing"
        HERMES_SIZE=0
    fi
else
    log "WARN: hermes not on PATH; skipping hermes backup"
    HERMES_SIZE=0
fi

# ===== 4. Inventory DB =====
# Use python3's sqlite3 module (always present in the Python-based container)
# rather than the sqlite3 CLI (not in these images).
INVENTORY_SIZE=0
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'inventory-mcp'; then
    log "Backing up inventory DB"
    if docker exec inventory-mcp python3 -c '
import sqlite3, shutil
src = sqlite3.connect("/data/inventory.db")
dst = sqlite3.connect("/data/inventory.db.bak")
with dst:
    src.backup(dst)
src.close(); dst.close()
' 2>>"$WORK/db.err"; then
        if docker cp inventory-mcp:/data/inventory.db.bak "$WORK/db/inventory.db" 2>>"$WORK/db.err"; then
            INVENTORY_SIZE=$(stat -c%s "$WORK/db/inventory.db" 2>/dev/null || echo 0)
            log "  inventory DB: $INVENTORY_SIZE bytes"
        else
            log "  WARN: docker cp of inventory failed"
        fi
        docker exec inventory-mcp rm -f /data/inventory.db.bak 2>/dev/null || true
    else
        log "  WARN: python sqlite3 backup of inventory failed"
    fi
else
    log "WARN: inventory-mcp container not running; skipping inventory DB"
fi

# ===== 5. KB DB =====
# Same pattern as inventory.
KB_SIZE=0
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'kb-mcp'; then
    log "Backing up KB DB"
    if docker exec kb-mcp python3 -c '
import sqlite3
src = sqlite3.connect("/data/kb.db")
dst = sqlite3.connect("/data/kb.db.bak")
with dst:
    src.backup(dst)
src.close(); dst.close()
' 2>>"$WORK/db.err"; then
        if docker cp kb-mcp:/data/kb.db.bak "$WORK/db/kb.db" 2>>"$WORK/db.err"; then
            KB_SIZE=$(stat -c%s "$WORK/db/kb.db" 2>/dev/null || echo 0)
            log "  KB DB: $KB_SIZE bytes"
        else
            log "  WARN: docker cp of KB failed"
        fi
        docker exec kb-mcp rm -f /data/kb.db.bak 2>/dev/null || true
    else
        log "  WARN: python sqlite3 backup of KB failed"
    fi
else
    log "WARN: kb-mcp container not running; skipping KB DB"
fi


# ===== 5b. Vaultwarden DB =====
# BACKLOG #48. vaultwarden uses SQLite at /data/db.sqlite3. Use the .backup
# command for an online backup (no locking) since vaultwarden is a live
# service; docker cp the .bak out and clean up. The image ships sqlite3 CLI.
VAULTWARDEN_SIZE=0
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'vaultwarden'; then
    log "Backing up vaultwarden DB"
    if docker exec vaultwarden sh -c "sqlite3 /data/db.sqlite3 ".backup '/data/db.sqlite3.bak'"" 2>>"$WORK/db.err"; then
        if docker cp vaultwarden:/data/db.sqlite3.bak "$WORK/db/vaultwarden.db" 2>>"$WORK/db.err"; then
            VAULTWARDEN_SIZE=$(stat -c%s "$WORK/db/vaultwarden.db" 2>/dev/null || echo 0)
            log "  vaultwarden DB: $VAULTWARDEN_SIZE bytes"
        else
            log "  WARN: docker cp of vaultwarden failed"
        fi
        docker exec vaultwarden rm -f /data/db.sqlite3.bak 2>/dev/null || true
    else
        log "  WARN: sqlite3 backup of vaultwarden failed (image may lack sqlite3 CLI)"
    fi
else
    log "WARN: vaultwarden container not running; skipping vaultwarden DB"
fi

# ===== 6. Config yml files =====
log "Copying yml config files"
for f in alloy.yml blackbox.yml loki.yml prometheus.yml promtail.yml; do
    if [ -f "$AIAMSBS_DIR/config/$f" ]; then
        cp "$AIAMSBS_DIR/config/$f" "$WORK/config/"
    else
        log "  WARN: missing $AIAMSBS_DIR/config/$f"
    fi
done
for f in grafana/provisioning/datasources/datasources.yml \
         grafana/provisioning/dashboards/dashboards.yml; do
    if [ -f "$AIAMSBS_DIR/config/$f" ]; then
        cp "$AIAMSBS_DIR/config/$f" "$WORK/config/$(basename "$f")"
    else
        log "  WARN: missing $AIAMSBS_DIR/config/$f"
    fi
done

# ===== 7. Manifest =====
EXPORTED="$EXPORTED" \
PROV_COUNT="$PROV_COUNT" \
HERMES_SIZE="$HERMES_SIZE" \
INVENTORY_SIZE="$INVENTORY_SIZE" \
KB_SIZE="$KB_SIZE" \
VAULTWARDEN_SIZE="$VAULTWARDEN_SIZE" \
AIAMSBS_DIR="$AIAMSBS_DIR" \
GRAFANA_URL="$GRAFANA_URL" \
python3 - <<'PY' > "$WORK/MANIFEST.json"
import datetime, json, os
print(json.dumps({
    "schema_version": 2,
    "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "aiamsbs_dir": os.environ.get("AIAMSBS_DIR", "unknown"),
    "grafana_url": os.environ.get("GRAFANA_URL", "unknown"),
    "dashboards_api_exported": int(os.environ.get("EXPORTED", "0")),
    "dashboards_provisioned_files": int(os.environ.get("PROV_COUNT", "0")),
    "hermes_zip_size_bytes": int(os.environ.get("HERMES_SIZE", "0")),
    "inventory_db_size_bytes": int(os.environ.get("INVENTORY_SIZE", "0")),
    "kb_db_size_bytes": int(os.environ.get("KB_SIZE", "0")),
    "vaultwarden_db_size_bytes": int(os.environ.get("VAULTWARDEN_SIZE", "0")),
}, indent=2))
PY

# ===== 8. Tar =====
tar -czf "$ARCHIVE" -C "$WORK" .
log "Wrote $ARCHIVE ($(du -h "$ARCHIVE" | awk '{print $1}'))"

# ===== 9. Rotate =====
ROTATED=$(ls -1t "$BACKUP_DIR"/aiamsbs-backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | wc -l)
ls -1t "$BACKUP_DIR"/aiamsbs-backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f --
log "Retention: kept last $KEEP backups (rotated $ROTATED old)"
