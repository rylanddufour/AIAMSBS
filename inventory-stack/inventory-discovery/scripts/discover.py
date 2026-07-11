#!/usr/bin/env python3
"""Inventory discovery workflow.

Runs an nmap scan against a target CIDR via the nmap-discovery service, parses
the XML output, and inserts every discovered host into the inventory database
via the inventory-mcp MCP server's `create_device` tool.

Usage:
    discover.py [--dry-run] [--timeout SECONDS] <target_cidr>

Example:
    discover.py 192.168.0.0/24
    discover.py --dry-run 10.0.1.0/24

Exits 0 on success (even if 0 devices were found), 1 on infrastructure failure
(nmap-discovery or inventory-mcp unreachable, or the scan itself failed).
"""

import argparse
import json
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

NMAP_URL = "http://localhost:8003/scan"
INVENTORY_URL = "http://localhost:8001/mcp"
DEFAULT_CIDR = "192.168.0.0/24"


def auto_detect_subnet() -> tuple[str, Optional[str]]:
    """Figure out the primary interface's CIDR + default gateway.

    Returns (cidr, gateway) where:
      - cidr is e.g. "192.168.0.220/24" (the primary interface's IPv4 CIDR)
      - gateway is e.g. "192.168.0.1" (the default route's next-hop) or None
        if there's no upstream gateway (e.g. IPv6-only host)

    Raises SystemExit with a clear message if auto-detect can't determine
    the network (no default route, no IPv4 address on the route's interface,
    `ip` not installed, etc.).
    """
    # Step 1: find the default route's interface
    try:
        route_proc = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"auto-detect-subnet: 'ip route show default' failed: {exc}")
    if not route_proc.stdout.strip():
        raise SystemExit("auto-detect-subnet: no default route found")
    # Parse: "default via 192.168.0.1 dev eth0" (or with proto/static/etc).
    # Be robust to "default dev <iface>" (no via) and trailing fields.
    parts = route_proc.stdout.split()
    if "dev" not in parts:
        raise SystemExit(f"auto-detect-subnet: no 'dev' in default route: {route_proc.stdout!r}")
    iface = parts[parts.index("dev") + 1]
    gateway = parts[parts.index("via") + 1] if "via" in parts else None
    # Step 2: get the CIDR for that interface
    try:
        addr_proc = subprocess.run(
            ["ip", "-j", "-4", "addr", "show", iface],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"auto-detect-subnet: 'ip -j -4 addr show {iface}' failed: {exc}")
    try:
        addrs = json.loads(addr_proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"auto-detect-subnet: 'ip -j' returned non-JSON: {exc}")
    if not addrs or not addrs[0].get("addr_info"):
        raise SystemExit(f"auto-detect-subnet: no IPv4 address on interface {iface!r}")
    primary = addrs[0]["addr_info"][0]
    cidr = f"{primary['local']}/{primary['prefixlen']}"
    return cidr, gateway


def http_get_json(url: str, timeout: float = 10.0) -> dict:
    """GET a URL and parse JSON response. Raises on HTTP / parse failure."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# MCPClient — minimal streamable-http JSON-RPC 2.0 client that handles the
# initialize → notifications/initialized → tools/call handshake the spec
# requires. Without the session-id header on subsequent calls, the server
# rejects tool calls with HTTP 400 "Missing session ID".
class MCPClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url
        self.timeout = timeout
        self.session_id: Optional[str] = None

    def _post(self, body: dict, *, expect_response: bool = True) -> Optional[dict]:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.base_url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            sid = resp.headers.get("mcp-session-id")
            if sid and not self.session_id:
                self.session_id = sid
            raw = resp.read().decode("utf-8")
        if not expect_response:
            return None
        return _parse_sse_response(raw)

    def initialize(self) -> dict:
        """Send initialize + notifications/initialized. Captures session id."""
        init = self._post({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "aiamsbs-discover", "version": "1.0.0"},
            },
        })
        # notifications/initialized has no response body per the spec
        self._post({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }, expect_response=False)
        return init or {}

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self._post({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }) or {}


def _parse_sse_response(raw: str) -> dict:
    """Strip SSE `event:message\\ndata:` prefix and return the parsed JSON body."""
    if raw.startswith("event:"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                raw = line[len("data:"):].strip()
                break
    return json.loads(raw)


def run_nmap(target: str, timeout: int = 300) -> str:
    """Call nmap-discovery /scan and return the XML stdout. Raises on failure."""
    url = f"{NMAP_URL}?target={urllib.parse.quote(target)}"
    try:
        result = http_get_json(url, timeout=timeout)
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        raise SystemExit(
            f"nmap-discovery unreachable at {NMAP_URL}: {exc}\n"
            f"Is the nmap-discovery container running? Start it with:\n"
            f"  cd /home/ansible/AIAMSBS/inventory-stack && \\\n"
            f"  sg docker -c 'docker compose --profile discovery up -d nmap-discovery'"
        )

    code = result.get("code", 1)
    output = result.get("output", "")
    if code != 0 or not output:
        raise SystemExit(
            f"nmap scan failed (returncode={code}): "
            f"{result.get('error', '<no stderr captured>')[:500]}"
        )
    return output


def reverse_dns_lookup(ip: str) -> Optional[str]:
    """Reverse-resolve an IP to its hostname via the host's configured DNS
    resolvers. Returns the FQDN (or short hostname) from the PTR record,
    or None on any failure (timeout, NXDOMAIN, no resolver, network
    unreachable, invalid input).

    Uses socket.gethostbyaddr which reads /etc/resolv.conf (and the glibc
    resolver) automatically — no extra deps. Default timeout is the system
    resolver's default (typically 5s). If a particular lookup hangs it'll
    block the script for that long; if that's a problem in production we
    can add a signal.alarm-based timeout in a follow-up.
    """
    if not ip:
        return None
    try:
        hostname, _aliases, _addrs = socket.gethostbyaddr(ip)
        return hostname or None
    except (socket.herror, socket.gaierror, socket.timeout, OSError):
        return None


def parse_hosts(xml_text: str) -> list[dict]:
    """Parse nmap XML and return one dict per host with extracted fields."""
    hosts = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SystemExit(f"nmap XML parse error: {exc}")

    for host in root.findall("host"):
        ip = mac = hostname = os_name = vendor = ""
        for addr in host.findall("address"):
            addrtype = addr.get("addrtype")
            if addrtype == "ipv4":
                ip = addr.get("addr", "")
            elif addrtype == "mac":
                mac = addr.get("addr", "")
                vendor = addr.get("vendor", "")
        h = host.find("hostname")
        if h is not None:
            n = h.find("name")
            if n is not None:
                hostname = n.get("name", "")
        # nmap's -sn -PR ping scan does NOT perform reverse DNS by default
        # (it only does ARP-ping to enumerate live hosts), so the
        # <hostname> element is usually empty. Fall back to the system
        # resolver's PTR lookup; on failure (NXDOMAIN, timeout, etc.)
        # reverse_dns_lookup returns None and we leave hostname as "" —
        # inventory-mcp's create_device/update_device handle the empty
        # string fine, and the device still gets a record (with ip_address
        # as the only identity).
        if not hostname and ip:
            hostname = reverse_dns_lookup(ip) or ""
        o = host.find("os/osmatch")
        if o is not None:
            os_name = o.get("name", "")
        if ip:
            hosts.append({
                "ip": ip,
                "mac": mac,
                "hostname": hostname,
                "os_name": os_name,
                "vendor": vendor,
            })
    return hosts


def device_payload(host: dict) -> dict:
    """Build the create_device argument dict for inventory-mcp."""
    device_type = host["os_name"].split()[0] if host["os_name"] else ""
    return {
        "device_id": host["ip"],
        "ip_address": host["ip"],
        "mac_address": host["mac"],
        "hostname": host["hostname"],
        "device_type": device_type[:50],
        "vendor": host["vendor"],
        "source": "nmap-discovery",
    }


# Module-level MCP client (lazily initialized; one session per script run)
_mcp_client: Optional[MCPClient] = None


def _get_mcp() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient(INVENTORY_URL, timeout=10.0)
        _mcp_client.initialize()
    return _mcp_client


def _now_iso() -> str:
    """Return current UTC time as an ISO 8601 string (with timezone offset).

    Used as the value for `last_seen` on update_device so daily re-scans
    refresh the staleness signal. inventory-mcp's `last_seen` column is a
    SQLite TIMESTAMP, which is type-flexible and accepts ISO 8601 text.
    """
    return datetime.now(timezone.utc).isoformat()


def _update_fields_from_payload(payload: dict) -> dict:
    """Build the PATCH fields dict for inventory-mcp's update_device.

    update_device(device_id, fields) has PATCH semantics — only the fields
    passed in `fields` are written. `device_id` is the update key (NOT a
    column) and must not appear in `fields` (it would be silently dropped
    by the server's VALID_DEVICE_FIELDS filter anyway, but be explicit).

    The set of fields is the device_payload() keys minus device_id, plus
    last_seen = "now" so each re-scan bumps the staleness timer.
    """
    return {
        "ip_address": payload.get("ip_address", ""),
        "mac_address": payload.get("mac_address", ""),
        "hostname": payload.get("hostname", ""),
        "device_type": payload.get("device_type", ""),
        "vendor": payload.get("vendor", ""),
        "source": payload.get("source", ""),
        "last_seen": _now_iso(),
    }


def get_existing_device(device_id: str) -> tuple[Optional[dict], str]:
    """Call inventory-mcp's get_device. Returns (device, error_reason).

    - (device_dict, "") — device found; `device_dict` is the row.
    - (None, "")        — device not found (the tool's normal "not found"
                          response, NOT an error).
    - (None, reason)    — infra / protocol / tool error; caller should
                          surface this as a per-host failure rather than
                          guess at the device's existence.

    inventory-mcp's get_device returns the row as a dict serialized into
    `result.content[0].text` as JSON. The "not found" path returns
    `{"error": "not found", "device_id": ...}` with isError=false — we
    parse the text body to distinguish that from a real row.
    """
    try:
        client = _get_mcp()
        resp = client.call_tool("get_device", {"device_id": device_id})
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        return None, f"inventory-mcp unreachable: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"inventory-mcp returned non-JSON: {exc}"

    # Protocol-level error (JSON-RPC error envelope)
    if "error" in resp:
        err = resp["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return None, f"protocol error: {msg[:200]}"

    result = resp.get("result", {})
    if result.get("isError"):
        content = result.get("content", [])
        msg = content[0].get("text", "") if content else "<no content>"
        return None, f"tool error: {msg[:200]}"

    # Success — get_device returns a dict wrapped in content[0].text as JSON
    content = result.get("content", [])
    if not content:
        return None, ""  # Empty result — treat as not found
    try:
        body = json.loads(content[0].get("text", ""))
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"non-JSON content: {exc}"
    if isinstance(body, dict) and body.get("error") == "not found":
        return None, ""  # Normal "not found" response from the tool
    if not body:
        return None, ""
    return body, ""


def insert_device(payload: dict, dry_run: bool = False) -> tuple[bool, str]:
    """Call inventory-mcp's create_device. Returns (inserted, reason).

    The MCP tool signature is `create_device(device: dict)` — FastMCP wraps
    the dict under a `device` key in the wire schema. Must wrap here.

    Tool-level errors live at result.isError + result.content[0].text (not at
    the JSON-RPC top-level `error` field, which is reserved for protocol
    errors). Read both to classify the failure.
    """
    if dry_run:
        return True, "dry-run"
    try:
        client = _get_mcp()
        # Wrap the dict under "device" — the tool signature is `device: dict`
        resp = client.call_tool("create_device", {"device": payload})
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        return False, f"inventory-mcp unreachable: {exc}"
    except json.JSONDecodeError as exc:
        return False, f"inventory-mcp returned non-JSON: {exc}"

    # Protocol-level error (JSON-RPC error envelope)
    if "error" in resp:
        err = resp["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return False, f"protocol error: {msg[:200]}"

    # Tool-level error (FastMCP returns isError=true with text content)
    result = resp.get("result", {})
    if result.get("isError"):
        content = result.get("content", [])
        msg = content[0].get("text", "") if content else "<no content>"
        # PRIMARY KEY collisions on device_id are unreachable in normal flow:
        # main() now calls get_device first and routes existing rows through
        # update_device_fields. Kept as defense-in-depth in case of a race
        # with another writer between our get_device and create_device.
        lower = msg.lower()
        if "unique" in lower or "primary key" in lower or "duplicate" in lower:
            return False, "duplicate"
        return False, f"tool error: {msg[:200]}"

    return True, "ok"


def update_device_fields(payload: dict, dry_run: bool = False) -> tuple[bool, str]:
    """Call inventory-mcp's update_device. Returns (updated, reason).

    PATCH semantics: only the fields passed in `fields` are written. Pass
    `device_id` as the update key (NOT as a field) — the server's
    VALID_DEVICE_FIELDS filter would drop it anyway. `last_seen` is
    refreshed to "now" so daily re-scans keep the staleness signal fresh.
    """
    if dry_run:
        return True, "dry-run"
    device_id = payload.get("device_id", "")
    if not device_id:
        return False, "missing device_id"
    fields = _update_fields_from_payload(payload)
    try:
        client = _get_mcp()
        # update_device signature is `update_device(device_id, fields)` — no
        # wrapping under "device" (that's only create_device's wire contract).
        resp = client.call_tool(
            "update_device",
            {"device_id": device_id, "fields": fields},
        )
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        return False, f"inventory-mcp unreachable: {exc}"
    except json.JSONDecodeError as exc:
        return False, f"inventory-mcp returned non-JSON: {exc}"

    # Protocol-level error (JSON-RPC error envelope)
    if "error" in resp:
        err = resp["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return False, f"protocol error: {msg[:200]}"

    # Tool-level error (FastMCP returns isError=true with text content)
    result = resp.get("result", {})
    if result.get("isError"):
        content = result.get("content", [])
        msg = content[0].get("text", "") if content else "<no content>"
        return False, f"tool error: {msg[:200]}"

    return True, "ok"


def main() -> int:
    desc = "Inventory discovery: scan a CIDR via nmap, upsert hosts into inventory DB"
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument("target", nargs="?", default=DEFAULT_CIDR,
                        help=f"target CIDR (default: {DEFAULT_CIDR})")
    parser.add_argument("--auto-detect-subnet", action="store_true",
                        help="auto-detect the primary interface's subnet + default "
                             "gateway; for cron mode. Mutually exclusive with the "
                             "positional <target>.")
    parser.add_argument("--dry-run", action="store_true",
                        help="scan + parse but don't touch inventory DB")
    parser.add_argument("--timeout", type=int, default=300,
                        help="nmap scan timeout in seconds (default: 300)")
    args = parser.parse_args()

    if args.auto_detect_subnet:
        cidr, gateway = auto_detect_subnet()
        # Use just the CIDR as the nmap target. v1 doesn't force-include the
        # gateway because the inventory-stack/nmap-discovery container passes
        # the target as a SINGLE argv element to nmap (`subprocess.run(["nmap",
        # "-sn", "-PR", "-oX", "-", target])`), and nmap can't parse a
        # space-separated list when it arrives as one string. The gateway
        # is force-included implicitly: for the .220 (and ~99% of small-shop
        # deployments) the gateway is in the same /24 as the host, so the
        # ARP-ping sweep (`-PR`) finds it naturally. Multi-target nmap
        # (when the gateway is on a different subnet) is a follow-up BACKLOG
        # item — see #40.
        target = cidr
        print(f"Auto-detected subnet: {cidr}, gateway: {gateway or '(none)'}")
    else:
        target = args.target

    print(f"Inventory discovery: scanning {target}...")

    xml_text = run_nmap(target, timeout=args.timeout)
    hosts = parse_hosts(xml_text)
    total = len(hosts)

    if total == 0:
        print("")
        print("Inventory discovery complete:")
        print(f"  Target:   {target}")
        print(f"  Found:    0 device(s)")
        print(f"  Inserted: 0 new device(s)")
        print(f"  Updated:  0 existing device(s)")
        print(f"  Skipped:  0 duplicate(s)")
        return 0

    inserted = 0
    updated = 0
    skipped = 0
    failures = []
    for host in hosts:
        payload = device_payload(host)
        device_id = payload["device_id"]
        # Check existence first so existing rows are refreshed (PATCH) instead
        # of failing the create with a UNIQUE constraint. This is the upsert
        # fix that lets a daily cron keep `last_seen` fresh on re-scans.
        existing, get_err = get_existing_device(device_id)
        if get_err:
            failures.append((device_id, get_err))
            continue
        if existing is not None:
            ok, reason = update_device_fields(payload, dry_run=args.dry_run)
            if ok:
                updated += 1
            elif reason == "duplicate":
                # Unreachable in normal flow — update_device doesn't have a
                # UNIQUE constraint to collide with. Kept for symmetry with
                # the insert path's race-condition defense.
                skipped += 1
            else:
                failures.append((device_id, reason))
        else:
            ok, reason = insert_device(payload, dry_run=args.dry_run)
            if ok:
                inserted += 1
            elif reason == "duplicate":
                # Defense-in-depth: only reachable if another writer inserts
                # this device_id between our get_device and create_device.
                skipped += 1
            else:
                failures.append((device_id, reason))

    print("")
    print("Inventory discovery complete:")
    print(f"  Target:   {target}")
    print(f"  Found:    {total} device(s)")
    print(f"  Inserted: {inserted} new device(s)")
    print(f"  Updated:  {updated} existing device(s)")
    print(f"  Skipped:  {skipped} duplicate(s)")
    if failures:
        print(f"  Failed:   {len(failures)} (showing first 3)")
        for ip, reason in failures[:3]:
            print(f"    {ip}: {reason}")

    # Infrastructure errors should propagate up
    infra_errors = [r for _, r in failures if r.startswith("inventory-mcp")]
    if infra_errors:
        print("")
        print("Hint: inventory-mcp may not be reachable. Check:")
        print("  sg docker -c 'docker ps | grep inventory-mcp'")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)