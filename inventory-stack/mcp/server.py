from fastmcp.mcp import initialize_mcp, tool, McpServer
import sqlite3
import os

DB_PATH = "./inventory.db"

# SQLite schema functions
create_tables_sql = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    hostname TEXT,
    device_type TEXT NOT NULL,
    mac TEXT,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS device_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_device_id INTEGER,
    to_device_id INTEGER,
    relationship_type TEXT NOT NULL,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_device_id) REFERENCES devices(id),
    FOREIGN KEY (to_device_id) REFERENCES devices(id)
);
"""

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(create_tables_sql)
    conn.commit()

def get_device(ip: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices WHERE ip=?", (ip,))
    return dict(zip([d[0] for d in cur.description], cur.fetchone())) if cur.fetchone() else None

def lookup_by_ip(ip: str):
    cur = sqlite3.connect(DB_PATH).cursor()
    cur.execute("SELECT * FROM devices WHERE ip=?", (ip,))
    return dict(zip([d[0] for d in cur.description], cur.fetchone())) if cur.fetchone() else None

def lookup_by_hostname(hostname: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices WHERE hostname=?", (hostname,))
    return dict(zip([d[0] for d in cur.description], cur.fetchone())) if cur.fetchone() else None

def search_devices(query: str):
    cur = sqlite3.connect(DB_PATH).cursor()
    cur.execute("SELECT * FROM devices WHERE ip LIKE ? OR hostname LIKE ?", (f"%{query}%", f"%{query}%"))
    rows = cur.fetchall()
    return [dict(zip([d[0] for d in cur.description], row)) for row in rows]

def create_device(ip: str, hostname: str = None, device_type: str = "unknown", mac: str = None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO devices (ip, hostname, device_type, mac) VALUES (?, ?, ?, ?)", (ip, hostname, device_type, mac))
    conn.commit()
    return {"id": cur.lastrowid, "ip": ip, "hostname": hostname, "device_type": device_type, "mac": mac}

def update_device(ip: str, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    updates = {key: value for key, value in kwargs.items() if key in ['hostname', 'device_type', 'mac']}
    if not updates:
        return {"error": "No valid fields to update"}
    
    set_clause = ", ".join([f"{key}=?" for key in updates.keys()])
    cur.execute(f"UPDATE devices SET {set_clause} WHERE ip= ?", (*updates.values(), ip))
    conn.commit()
    return {"status": "success"}

def get_device_relationships(device_id: int):
    cur = sqlite3.connect(DB_PTR).cursor()
    cur.execute("SELECT * FROM device_relationships WHERE from_device_id=?", (device_id,))
    rows = cur.fetchall()
    return [dict(zip([d[0] for d in cur.description], row)) for row in rows]

# Initialize database
if not os.path.exists(DB_PATH):
    init_db()

app = McpServer(
    name='inventory-mcp',
    description='AIAMSBS Device Inventory Service',
    version='1.0.0',
    tools=[
        tool(get_device),
        tool(lookup_by_ip),
        tool(lookup_by_hostname),
        tool(search_devices),
        tool(create_device),
        tool(update_device),
        tool(get_device_relationships)
    ]
)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)