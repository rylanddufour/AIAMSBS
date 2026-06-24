#!/usr/bin/env python3
"""Seed the AIAMSBS inventory DB for smoke tests.

Runs seed.sql idempotently against /data/inventory.db. Because the DB lives
inside the running `inventory-mcp` container (mounted at /data from the
`inventory-data` named volume), the script invokes `docker exec` to apply the
SQL using Python's sqlite3 module — the container ships with Python 3.12 but
no `sqlite3` CLI binary.

Idempotent: seed.sql begins with DELETE FROM both tables, so calling this
script multiple times always converges on the same fixture state.

Usage:
    python3 seed.py            # seeds the running inventory-mcp container
    python3 seed.py --db PATH  # seeds an arbitrary sqlite file (testing)

Exit codes:
    0  on success
    1  on any failure (container not running, SQL error, etc.)
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SEED_SQL = HERE / "seed.sql"

DEFAULT_CONTAINER = "inventory-mcp"
DEFAULT_CONTAINER_DB = "/data/inventory.db"


def _docker_prefix() -> list[str]:
    """Return `["sudo", "-n", "docker"]` if plain docker needs elevation.

    Some dev sandboxes have `docker` installed but the daemon socket is
    root-owned; in that case `sudo -n docker` works without prompting. We
    probe by attempting a no-op `docker info` first.
    """
    probe = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if probe.returncode == 0:
        return ["docker"]
    # Try sudo -n (non-interactive) — if that works, use it.
    sudo_probe = subprocess.run(
        ["sudo", "-n", "docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if sudo_probe.returncode == 0:
        return ["sudo", "-n", "docker"]
    # Neither worked; let the subsequent call produce the visible error.
    return ["docker"]


def seed_via_docker(container: str, db_path: str, sql: str) -> None:
    """Apply SQL to the container's DB by piping it into `docker exec python`."""
    # `docker exec -i` keeps stdin attached so we can pipe the SQL script.
    prefix = _docker_prefix()
    cmd = prefix + [
        "exec",
        "-i",
        container,
        "python3",
        "-c",
        (
            "import sqlite3, sys\n"
            "sql = sys.stdin.read()\n"
            "conn = sqlite3.connect(%r)\n"
            "conn.executescript(sql)\n"
            "conn.commit()\n"
            "conn.close()\n"
        )
        % db_path,
    ]
    proc = subprocess.run(cmd, input=sql, text=True, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(
            f"docker exec failed (rc={proc.returncode}): {proc.stderr.strip()}\n"
        )
        sys.exit(1)


def seed_local(db_path: str, sql: str) -> None:
    """Apply SQL directly to a local sqlite file (testing / dry-run)."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.executescript(sql)
    conn.commit()
    conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        help="Seed a local sqlite file instead of the container DB.",
    )
    parser.add_argument(
        "--container",
        default=DEFAULT_CONTAINER,
        help=f"Docker container to exec into (default: {DEFAULT_CONTAINER})",
    )
    parser.add_argument(
        "--container-db",
        default=DEFAULT_CONTAINER_DB,
        help=f"Path to inventory.db inside the container (default: {DEFAULT_CONTAINER_DB})",
    )
    args = parser.parse_args()

    if not SEED_SQL.exists():
        sys.stderr.write(f"missing seed SQL: {SEED_SQL}\n")
        return 1
    sql = SEED_SQL.read_text()

    if args.db:
        seed_local(args.db, sql)
        print(f"[seed.py] seeded local DB: {args.db}")
        return 0

    if shutil.which("docker") is None:
        sys.stderr.write("docker not on PATH; pass --db to seed locally\n")
        return 1

    seed_via_docker(args.container, args.container_db, sql)
    print(f"[seed.py] seeded {args.container}:{args.container_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())