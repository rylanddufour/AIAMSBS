PRAGMA journal_mode=WAL;

CREATE TABLE devices (
    device_id TEXT PRIMARY KEY,
    hostname TEXT,
    ip_address TEXT,
    mac_address TEXT,
    device_type TEXT,
    vendor TEXT,
    model TEXT,
    management_endpoint TEXT,
    credential_ref TEXT,
    site TEXT,
    role TEXT,
    tags TEXT,
    description TEXT,
    source TEXT,
    last_seen TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_devices_ip ON devices(ip_address);
CREATE INDEX idx_devices_type ON devices(device_type);

CREATE TABLE device_relationships (
    source_device_id TEXT,
    target_device_id TEXT,
    relationship_type TEXT,
    PRIMARY KEY (source_device_id, target_device_id, relationship_type)
);