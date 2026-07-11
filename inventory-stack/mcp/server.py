import argparse
import os
import sqlite3

from mcp.server.fastmcp import FastMCP

DB_PATH = os.environ.get("INVENTORY_DB_PATH", "/data/inventory.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "init_db.sql")

VALID_DEVICE_FIELDS = [
    "hostname",
    "ip_address",
    "mac_address",
    "device_type",
    "vendor",
    "model",
    "management_endpoint",
    "credential_ref",
    "site",
    "role",
    "tags",
    "description",
    "source",
    "last_seen",
]

mcp = FastMCP("inventory")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Load schema from init_db.sql and apply it to the database."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with open(SCHEMA_PATH, "r") as f:
        schema_sql = f.read()
    conn = _connect()
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()


@mcp.tool()
def get_device(device_id: str) -> dict:
    """Look up a single device by its device_id."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices WHERE device_id=?", (device_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"error": "not found", "device_id": device_id}
    return dict(row)


@mcp.tool()
def lookup_by_ip(ip: str) -> dict:
    """Look up a device by its IP address."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices WHERE ip_address=?", (ip,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"error": "not found", "ip": ip}
    return dict(row)


@mcp.tool()
def lookup_by_hostname(hostname: str) -> dict:
    """Look up a device by its hostname."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices WHERE hostname=?", (hostname,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"error": "not found", "hostname": hostname}
    return dict(row)


@mcp.tool()
def search_devices(query: str, device_type: str = "", tag: str = "", limit: int = 20) -> list:
    """Search devices by free-text query with optional filters.

    Args:
        query: substring matched against device_id, hostname, ip_address,
               vendor, description, and tags.
        device_type: if non-empty, restrict to this exact device_type.
        tag: if non-empty, restrict to devices whose tags column contains it.
        limit: maximum number of rows to return.
    """
    conn = _connect()
    cur = conn.cursor()
    sql = (
        "SELECT * FROM devices WHERE ("
        "device_id LIKE ? OR hostname LIKE ? OR ip_address LIKE ? "
        "OR vendor LIKE ? OR description LIKE ? OR tags LIKE ?"
        ")"
    )
    like = f"%{query}%"
    params: list = [like, like, like, like, like, like]
    if device_type:
        sql += " AND device_type = ?"
        params.append(device_type)
    if tag:
        sql += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    sql += " LIMIT ?"
    params.append(limit)
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


@mcp.tool()
def list_devices(device_type: str = "", limit: int = 500) -> list:
    """Enumerate all devices, optionally filtered by exact device_type.

    Use this for bulk operations (e.g. generating Prometheus target files)
    where you need the full inventory, not a substring search. For free-text
    lookup, use search_devices instead.

    Args:
        device_type: if non-empty, restrict to this exact device_type.
        limit: maximum number of rows to return (default 500).
    """
    conn = _connect()
    cur = conn.cursor()
    if device_type:
        cur.execute("SELECT * FROM devices WHERE device_type = ? LIMIT ?", (device_type, limit))
    else:
        cur.execute("SELECT * FROM devices LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


@mcp.tool()
def create_device(device: dict) -> dict:
    """Create a new device record. `device_id` is required."""
    device_id = device.get("device_id")
    if not device_id:
        return {"error": "device_id is required"}
    fields = ["device_id"]
    values = [device_id]
    for f in VALID_DEVICE_FIELDS:
        if f in device and device[f] is not None:
            fields.append(f)
            values.append(device[f])
    placeholders = ",".join(["?"] * len(values))
    sql = f"INSERT INTO devices ({','.join(fields)}) VALUES ({placeholders})"
    conn = _connect()
    cur = conn.cursor()
    cur.execute(sql, values)
    conn.commit()
    conn.close()
    return {"status": "created", "device_id": device_id}


@mcp.tool()
def update_device(device_id: str, fields: dict) -> dict:
    """Update fields on an existing device. updated_at is set automatically."""
    updates = {k: v for k, v in fields.items() if k in VALID_DEVICE_FIELDS}
    if not updates:
        return {"error": "no valid fields to update"}
    updates["updated_at"] = "CURRENT_TIMESTAMP"
    set_clause = ", ".join(f"{k}=?" for k in updates.keys())
    values = list(updates.values()) + [device_id]
    sql = f"UPDATE devices SET {set_clause} WHERE device_id=?"
    conn = _connect()
    cur = conn.cursor()
    cur.execute(sql, values)
    conn.commit()
    rows_affected = cur.rowcount
    conn.close()
    return {"status": "updated", "rows": rows_affected, "device_id": device_id}


@mcp.tool()
def delete_device(device_id: str, cascade_relationships: bool = True) -> dict:
    """Delete a device record from the inventory by device_id.

    DESTRUCTIVE — the row is permanently removed (not soft-deleted).
    Callers should always confirm with the user before invoking this.

    Args:
        device_id: required. The device_id of the row to delete.
        cascade_relationships: if True (default), also delete any rows in
            device_relationships where this device is source or target.

    Returns the deleted row contents plus a status envelope so callers
    can show the user exactly what was removed.
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices WHERE device_id=?", (device_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return {"error": "not found", "device_id": device_id}
    deleted = dict(row)
    rels_deleted = 0
    if cascade_relationships:
        cur.execute(
            "DELETE FROM device_relationships "
            "WHERE source_device_id=? OR target_device_id=?",
            (device_id, device_id),
        )
        rels_deleted = cur.rowcount
    cur.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
    conn.commit()
    rows_affected = cur.rowcount
    conn.close()
    return {
        "status": "deleted",
        "device_id": device_id,
        "rows": rows_affected,
        "relationships_deleted": rels_deleted,
        "deleted_record": deleted,
    }


@mcp.tool()
def get_device_relationships(device_id: str) -> list:
    """Return all relationships involving this device (as source or target)."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM device_relationships "
        "WHERE source_device_id=? OR target_device_id=?",
        (device_id, device_id),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def main():
    parser = argparse.ArgumentParser(description="AIAMSBS inventory MCP server")
    parser.add_argument("--host", default="0.0.0.0", help="bind host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8001, help="bind port (default 8001)")
    args = parser.parse_args()

    init_db()

    # FastMCP.run() does not accept host/port kwargs in this version — set via
    # the settings object (host/port are top-level Settings fields).
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()