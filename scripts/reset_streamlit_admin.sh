#!/usr/bin/env bash
# scripts/reset_streamlit_admin.sh — host-side recovery for the Streamlit admin account.
#
# BACKLOG #79: companion to the BACKLOG #77 Settings-page form. The form is for
# routine password rotation via the UI; this script is the recovery path when
# the operator is locked out and can't reach the form.
#
# Behavior:
#   - Opens $HOME/AIAMSBS/streamlit-ui-stack/data/streamlit-ui.db on the host
#     (bind-mount source for the streamlit-ui container's /data volume) via
#     Python stdlib sqlite3 + bcrypt.
#   - Computes a fresh bcrypt hash of "admin".
#   - Upserts STREAMLIT_ADMIN_PASSWORD_HASH to that hash.
#   - Deletes the STREAMLIT_ADMIN_PASSWORD plaintext row (so it can't
#     accidentally override the new hash on the next login).
#   - Prints the old + new hash + a confirmation.
#
# Usage:
#   bash scripts/reset_streamlit_admin.sh           # actually reset
#   bash scripts/reset_streamlit_admin.sh --dry-run # show what would happen
#
# Exit codes:
#   0 = success (or dry-run completed)
#   1 = sqlite database file not found at the expected mount path
#   2 = bcrypt Python module not installed on the host
#   3 = sqlite error during read/write
#
# After running, the operator can log in at http://<host>/ with admin / admin.
# No `docker compose restart` needed — auth re-reads on every login.

set -euo pipefail

DB_PATH="${HOME}/AIAMSBS/streamlit-ui-stack/data/streamlit-ui.db"
DRY_RUN=0

# ---- argparse (manual; bash getopts is fine for two flags) ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --db-path)
            DB_PATH="$2"
            shift 2
            ;;
        --help|-h)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *)
            echo "ERROR: unknown flag: $1" >&2
            echo "Run with --help for usage." >&2
            exit 1
            ;;
    esac
done

# ---- pre-flight: DB file exists ----
if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: sqlite database not found at: $DB_PATH" >&2
    echo "" >&2
    echo "Expected path (host-side bind-mount source for the streamlit-ui" >&2
    echo "container's /data volume — the path resolves to the repo's" >&2
    echo "streamlit-ui-stack/data/ subdir relative to \$HOME)." >&2
    echo "" >&2
    echo "If your AIAMSBS checkout lives elsewhere, pass --db-path /your/path/streamlit-ui.db" >&2
    echo "(defaults to \${HOME}/AIAMSBS/streamlit-ui-stack/data/streamlit-ui.db)" >&2
    exit 1
fi

# ---- pre-flight: DB file writable (the bind-mount creates the file as root,
# so the host user usually needs sudo to write — verify, fall back to sudo).
# Use `test -w` (the canonical POSIX write check) rather than actually appending
# to the file — sqlite uses fixed-size pages and a stray NUL byte would corrupt
# the header. ----
SUDO=""
if ! test -w "$DB_PATH"; then
    if sudo -n true 2>/dev/null; then
        SUDO="sudo -n"
        echo "(DB file is not writable by current user; re-running Python under sudo)"
        echo ""
    else
        echo "ERROR: cannot write to $DB_PATH and passwordless sudo is unavailable." >&2
        echo "Re-run as root, or chmod the file to be group-writable for the" >&2
        echo "current user's group, or configure passwordless sudo." >&2
        exit 1
    fi
fi

# ---- pre-flight: bcrypt importable on the host ----
if ! python3 -c 'import bcrypt' 2>/dev/null; then
    echo "ERROR: bcrypt Python module not installed on this host." >&2
    echo "" >&2
    echo "Install with one of:" >&2
    echo "  pip3 install bcrypt" >&2
    echo "  sudo apt-get install python3-bcrypt    # Debian/Ubuntu" >&2
    exit 2
fi

# ---- the actual reset (one Python invocation; no shell-escaping of bcrypt/sql).
# Pass values as CLI args (not env vars) so sudo -n doesn't strip them — sudo
# by default scrubs the environment except for a small allowlist. ----
$SUDO python3 - "$DB_PATH" "$DRY_RUN" <<'PY'
import os
import sqlite3
import sys
import bcrypt

# Args from the bash wrapper (passed positionally to survive `sudo` env-scrubbing).
db_path = sys.argv[1]
dry_run = sys.argv[2] == "1"

def _read_old_hash(conn):
    """Return the current STREAMLIT_ADMIN_PASSWORD_HASH row, or None if absent."""
    row = conn.execute(
        "SELECT value FROM ui_settings WHERE key='STREAMLIT_ADMIN_PASSWORD_HASH'"
    ).fetchone()
    return row[0] if row else None

try:
    conn = sqlite3.connect(db_path)
    old_hash = _read_old_hash(conn)
except sqlite3.Error as e:
    print(f"ERROR: sqlite read failed: {e}", file=sys.stderr)
    sys.exit(3)

new_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode("utf-8")

print(f"Database: {db_path}")
print(f"Old hash: {old_hash if old_hash else '(none — first row)'}")
print(f"New hash: {new_hash}")
print(f"New hash cost factor: {new_hash.split('$')[2]}  (default 12)")
print()

# SQL we'll run (printed whether dry-run or live so the operator sees it).
upsert_sql = (
    "INSERT INTO ui_settings (key, value, updated_at) "
    "VALUES ('STREAMLIT_ADMIN_PASSWORD_HASH', ?, CURRENT_TIMESTAMP) "
    "ON CONFLICT(key) DO UPDATE SET "
    "value = excluded.value, updated_at = CURRENT_TIMESTAMP"
)
delete_plain_sql = "DELETE FROM ui_settings WHERE key='STREAMLIT_ADMIN_PASSWORD'"
print("SQL to run:")
print(f"  {upsert_sql}")
print(f"  -- params: ('{new_hash}',)")
print(f"  {delete_plain_sql}")
print()

if dry_run:
    print("DRY RUN — no changes written. Re-run without --dry-run to apply.")
    sys.exit(0)

try:
    cur = conn.cursor()
    cur.execute(upsert_sql, (new_hash,))
    cur.execute(delete_plain_sql)
    conn.commit()
except sqlite3.Error as e:
    print(f"ERROR: sqlite write failed: {e}", file=sys.stderr)
    conn.rollback()
    sys.exit(3)
finally:
    conn.close()

# Verify by re-reading
conn = sqlite3.connect(db_path)
verified = _read_old_hash(conn)
conn.close()
if verified != new_hash:
    print(f"ERROR: post-write verification failed. expected={new_hash!r} got={verified!r}",
          file=sys.stderr)
    sys.exit(3)

print("SUCCESS — admin / admin is now active.")
print()
print("Next steps:")
print("  1. Open http://<host>/ in a browser")
print("  2. Log in with username 'admin', password 'admin'")
print("  3. (Recommended) Go to Settings -> Admin Account and rotate the")
print("     password to something stronger — this script is for recovery,")
print("     not routine rotation. Use the UI form for that.")
print("  4. No 'docker compose restart' needed — auth re-reads on every login.")
PY