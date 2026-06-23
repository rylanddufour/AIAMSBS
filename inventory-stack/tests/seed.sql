-- Smoke-test seed for AIAMSBS inventory MCP.
-- Idempotent: clears both tables before inserting fixtures.
-- Designed to match the schema declared in inventory-stack/mcp/init_db.sql.

-- Wipe and re-insert so the test is repeatable. Order matters:
-- relationships first (FK-less here but defensively cleanest), then devices.
DELETE FROM device_relationships;
DELETE FROM devices;

-- Three representative devices: a Linux host, a managed switch, and a wireless AP.
-- device_id is TEXT PRIMARY KEY (per init_db.sql).
INSERT INTO devices (
    device_id, hostname, ip_address, mac_address, device_type,
    vendor, model, management_endpoint, credential_ref, site,
    role, tags, description, source, last_seen
) VALUES
    (
        'dev-linux-01', 'linux-host-01', '192.168.10.10', 'aa:bb:cc:00:00:01',
        'linux_host', 'Dell', 'PowerEdge R740',
        'https://linux-host-01.example.com:8443', NULL, 'lab',
        'compute', 'linux,prod,smoke-test',
        'Smoke-test Linux host fixture', 'seed', CURRENT_TIMESTAMP
    ),
    (
        'dev-switch-01', 'core-switch-01', '192.168.10.1', 'aa:bb:cc:00:00:02',
        'switch', 'Cisco', 'Catalyst 9300',
        'https://core-switch-01.example.com', 'vault:switch-01', 'lab',
        'core', 'switch,prod,smoke-test',
        'Smoke-test managed switch fixture', 'seed', CURRENT_TIMESTAMP
    ),
    (
        'dev-ap-01', 'ap-floor1-01', '192.168.10.50', 'aa:bb:cc:00:00:03',
        'ap', 'Ubiquiti', 'U7 Pro',
        'https://ap-floor1-01.example.com:8443', 'vault:ap-01', 'lab',
        'access', 'ap,wifi,smoke-test',
        'Smoke-test wireless AP fixture', 'seed', CURRENT_TIMESTAMP
    );

-- Two device_relationships connecting the three fixtures. Composite PK is
-- (source_device_id, target_device_id, relationship_type), so duplicate
-- relationships with a different type are allowed.
INSERT INTO device_relationships (source_device_id, target_device_id, relationship_type) VALUES
    ('dev-linux-01', 'dev-switch-01', 'connects_to'),
    ('dev-switch-01', 'dev-ap-01', 'connects_to');