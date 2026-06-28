#!/usr/bin/env bash
# backup-dashboards.sh
# Export every Grafana dashboard (file-provisioned AND customer-created)
# as JSON, then tar them into ~/backups/dashboard-backup-YYYYMMDD-HHMMSS.tar.gz.
#
# Auth: Grafana service account token (Bearer), created by bootstrap.sh's
# create_grafana_mcp_service_account(). Token file is the SAME file the
# default and it_admin profiles already read at ~/.hermes/secrets/grafana-mcp.env.
# Override path with GRAFANA_TOKEN_FILE env var if needed.
#
# Cron: 0 1 * * *   (daily at 01:00, before backup-aiamsbs.sh)
# Retains the last 14 daily backups.

set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
TOKEN_FILE="${GRAFANA_TOKEN_FILE:-$HOME/.hermes/secrets/grafana-mcp.env}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP=14
TS="$(date -u +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
ARCHIVE="$BACKUP_DIR/dashboard-backup-${TS}.tar.gz"

mkdir -p "$BACKUP_DIR" "$WORK/dashboards"
trap 'rm -rf "$WORK"' EXIT

# ---- Load SA token ----
if [ ! -r "$TOKEN_FILE" ]; then
    echo "[$(date -Is)] ERROR: token file not readable: $TOKEN_FILE" >&2
    echo "[$(date -Is)] (bootstrap.sh creates it via create_grafana_mcp_service_account)" >&2
    exit 1
fi
# shellcheck disable=SC1090
. "$TOKEN_FILE"
GRAFANA_TOKEN="${GRAFANA_SERVICE_ACCOUNT_TOKEN:-}"
if [ -z "$GRAFANA_TOKEN" ] || [[ "$GRAFANA_TOKEN" == *...* ]]; then
    echo "[$(date -Is)] ERROR: GRAFANA_SERVICE_ACCOUNT_TOKEN missing or placeholder in $TOKEN_FILE" >&2
    exit 1
fi

# ---- API helper (Bearer auth) ----
api() {
    curl -fsS -H "Authorization: Bearer ${GRAFANA_TOKEN}" \
        -H 'Accept: application/json' \
        "$@"
}

# ---- Enumerate dashboards ----
echo "[$(date -Is)] enumerating dashboards from $GRAFANA_URL (token from $TOKEN_FILE)"
SEARCH_JSON="$(api "${GRAFANA_URL}/api/search?type=dash-db&limit=5000")"
COUNT=$(printf '%s' "$SEARCH_JSON" | grep -o '"uid":"' | wc -l)
echo "[$(date -Is)] found $COUNT dashboard(s)"

if [ "$COUNT" -eq 0 ]; then
    echo "[$(date -Is)] no dashboards to back up, exiting"
    exit 0
fi

# ---- Export each dashboard ----
EXPORTED=0
for uid in $(printf '%s' "$SEARCH_JSON" | grep -o '"uid":"[^"]*"' | sed 's/"uid":"//;s/"//g'); do
    RAW="$(api "${GRAFANA_URL}/api/dashboards/uid/${uid}" 2>/dev/null)" || {
        echo "[$(date -Is)] WARN: failed to fetch $uid, skipping"
        continue
    }

    SLUG=$(printf '%s' "$RAW" | python3 -c "import sys,json; d=json.load(sys.stdin)['dashboard']; print(d.get('slug') or d.get('uid') or 'unknown')" 2>/dev/null || echo "$uid")
    # Sanitize slug: keep alphanumerics, dots, underscores, hyphens. Everything else -> '-'.
    SLUG="$(printf '%s' "$SLUG" | tr -c '[:alnum:]._-' '-' | head -c 64)"

    OUT="$WORK/dashboards/${SLUG}__${uid}.json"
    printf '%s' "$RAW" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('dashboard', d), indent=2, sort_keys=True))" \
        > "$OUT" 2>/dev/null \
        || { echo "[$(date -Is)] WARN: failed to write $uid, skipping"; continue; }
    EXPORTED=$((EXPORTED + 1))
done

echo "[$(date -Is)] exported $EXPORTED dashboard(s)"

# ---- Manifest ----
EXPORTED="$EXPORTED" GRAFANA_URL="$GRAFANA_URL" python3 - <<'PY' > "$WORK/MANIFEST.json"
import datetime, json, os
print(json.dumps({
    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    "source": os.environ.get("GRAFANA_URL", "unknown"),
    "count": int(os.environ.get("EXPORTED", "0")),
    "schema_version": 1,
}, indent=2))
PY

# ---- Tar ----
tar -czf "$ARCHIVE" -C "$WORK" MANIFEST.json dashboards
echo "[$(date -Is)] wrote $ARCHIVE ($(du -h "$ARCHIVE" | awk '{print $1}'))"

# ---- Rotate ----
ls -1t "$BACKUP_DIR"/dashboard-backup-*.tar.gz 2>/dev/null \
    | tail -n +$((KEEP + 1)) \
    | xargs -r rm -f --
echo "[$(date -Is)] retention: kept last $KEEP dashboard backups"
