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
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

NMAP_URL = "http://localhost:8002/scan"
INVENTORY_URL = "http://localhost:8001/mcp"
DEFAULT_CIDR = "192.168.0.0/24"


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


def insert_device(payload: dict, dry_run: bool = False) -> tuple[bool, str]:
    """Call inventory-mcp's create_device. Returns (inserted, reason)."""
    if dry_run:
        return True, "dry-run"
    try:
        client = _get_mcp()
        resp = client.call_tool("create_device", payload)
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        return False, f"inventory-mcp unreachable: {exc}"
    except json.JSONDecodeError as exc:
        return False, f"inventory-mcp returned non-JSON: {exc}"

    if "error" in resp:
        err = resp["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        # PRIMARY KEY collisions on device_id are normal (re-scans).
        if "UNIQUE" in msg or "PRIMARY KEY" in msg or "duplicate" in msg.lower():
            return False, "duplicate"
        return False, f"error: {msg[:200]}"
    return True, "ok"


def main() -> int:
    desc = "Inventory discovery: scan a CIDR via nmap, insert hosts into inventory DB"
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument("target", nargs="?", default=DEFAULT_CIDR,
                        help=f"target CIDR (default: {DEFAULT_CIDR})")
    parser.add_argument("--dry-run", action="store_true",
                        help="scan + parse but don't insert into inventory DB")
    parser.add_argument("--timeout", type=int, default=300,
                        help="nmap scan timeout in seconds (default: 300)")
    args = parser.parse_args()

    print(f"Inventory discovery: scanning {args.target}...")

    xml_text = run_nmap(args.target, timeout=args.timeout)
    hosts = parse_hosts(xml_text)
    total = len(hosts)

    if total == 0:
        print("")
        print("Inventory discovery complete:")
        print(f"  Target:   {args.target}")
        print(f"  Found:    0 device(s)")
        print(f"  Inserted: 0 new device(s)")
        print(f"  Skipped:  0 duplicate(s)")
        return 0

    inserted = 0
    skipped = 0
    failures = []
    for host in hosts:
        payload = device_payload(host)
        ok, reason = insert_device(payload, dry_run=args.dry_run)
        if ok:
            inserted += 1
        elif reason == "duplicate":
            skipped += 1
        else:
            failures.append((host["ip"], reason))

    print("")
    print("Inventory discovery complete:")
    print(f"  Target:   {args.target}")
    print(f"  Found:    {total} device(s)")
    print(f"  Inserted: {inserted} new device(s)")
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