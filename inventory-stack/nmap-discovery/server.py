import argparse
import subprocess

import uvicorn
from fastapi import FastAPI

app = FastAPI()


def nmap_discovery(target: str, scan_type: str = "ping") -> subprocess.CompletedProcess:
    """Run an nmap scan against the target.

    scan_type="ping" (default): host-discovery only (`-sn -PR`), no port scan.
        Fast, no root required inside the container, ~25s per /24. The
        `--max-rate 10` cap prevents parallel-ARP congestion from dropping
        slow-responding hosts (WiFi clients, sleepy NICs, busy switches)
        on a full /24 sweep — see the 2026-07-20 fix.

    scan_type="deep": TCP SYN scan on common management ports + OS fingerprint.
        Slower, requires NET_RAW (which the container has via --cap-add).

    Raises ValueError on unknown scan_type so the caller sees the failure
    cleanly instead of a silent default.
    """
    if scan_type == "ping":
        cmd = ["nmap", "-sn", "-PR", "--max-rate", "10", "-oX", "-", target]
    elif scan_type == "deep":
        cmd = [
            "nmap",
            "-sS",                              # TCP SYN scan
            "-p", "22,23,80,135,139,443,445,3389,8080,8443",  # ssh, telnet, http, https, RDP-adjacent
            "-O",                                # OS detection
            "--osscan-limit",                    # only OS-scan promising hosts (faster)
            "-oX", "-",
            target,
        ]
    else:
        raise ValueError(f"unknown scan_type: {scan_type!r} (expected 'ping' or 'deep')")
    return subprocess.run(cmd, capture_output=True, text=True)


@app.get("/scan")
def scan(target: str = "192.168.0.0/24", scan_type: str = "ping"):
    """Trigger an nmap scan and return the raw output.

    scan_type: "ping" (host discovery only, fast) or "deep"
        (TCP SYN + OS fingerprint, slower, requires NET_RAW).
    """
    try:
        result = nmap_discovery(target, scan_type=scan_type)
    except ValueError as exc:
        return {
            "target": target,
            "scan_type": scan_type,
            "error": str(exc),
            "code": 2,  # 2 = usage/config error (nmap convention)
            "output": "",
        }
    return {
        "target": target,
        "scan_type": scan_type,
        "output": result.stdout,
        "error": result.stderr,
        "code": result.returncode,
    }


def main():
    parser = argparse.ArgumentParser(description="AIAMSBS nmap discovery service")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8003, help="bind port (default 8003)")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()