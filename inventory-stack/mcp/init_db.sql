PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname TEXT,
    ip_address TEXT NOT NULL UNIQUE,
    mac_address TEXT,
    device_type TEXT,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    credential_ref TEXT
);

CREATE TABLE IF NOT EXISTS device_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    related_device_id INTEGER,
    related_ip TEXT,
    related_hostname TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (related_device_id) REFERENCES devices(id)
);

CREATE INDEX IF NOT EXISTS idx_ip_address ON devices(ip_address);
CREATE INDEX IF NOT EXISTS idx_hostname ON devices(hostname);
CREATE INDEX IF NOT EXISTS idx_device_type ON devices(device_type);