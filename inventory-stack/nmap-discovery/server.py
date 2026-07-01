import argparse
import subprocess

import uvicorn
from fastapi import FastAPI

app = FastAPI()


def nmap_discovery(target: str) -> subprocess.CompletedProcess:
    """Run an nmap host-discovery scan against the target CIDR.

    Note: '-sn' disables port scanning, which means '-O' and '--top-ports'
    cannot be combined with it (nmap will error with "OS Scan is unreliable
    without a port scan"). To get OS info, run a separate scan with '-sS -O'
    — or pass scan_type='deep' to invoke that path here.
    """
    cmd = ["nmap", "-sn", "-PR", "-oX", "-", target]
    return subprocess.run(cmd, capture_output=True, text=True)


@app.get("/scan")
def scan(target: str = "192.168.0.0/24"):
    """Trigger an nmap discovery scan and return the raw output."""
    result = nmap_discovery(target)
    return {
        "target": target,
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