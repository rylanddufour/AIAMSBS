#!/usr/bin/env python3
"""systemd-journal-search — structured journalctl queries on a Linux Managed device.

Wraps `journalctl` with safe flags so the Agent doesn't have to remember them.
Returns filtered journal entries as structured JSON.

Usage: systemd-journal-search.py [--since STR] [--until STR] [--unit NAME]
                                 [--priority LEVEL] [--boot] [--pid N]
                                 [--uid N] [--regex PATTERN] [--limit N]
                                 [--target HOST]

v1: only `localhost` honored; SSH for remote Managed devices is future.
Exits 0 on success, 1 on infrastructure failure.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys


def _run_journalctl(args, timeout=30):
    bin_ = shutil.which("journalctl")
    if not bin_:
        return None, "<journalctl not found>"
    try:
        r = subprocess.run(
            [bin_] + args + ["--no-pager", "-o", "json"],
            capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None, "<journalctl timed out>"
    except OSError as e:
        return None, f"<journalctl failed: {e}>"
    if r.returncode != 0 and not r.stdout:
        return None, f"<journalctl exit {r.returncode}: {(r.stderr or '').strip()}>"
    entries = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries, ""


def _parse_entry(e):
    # journalctl -o json fields: __REALTIME_TIMESTAMP (us), PRIORITY, _PID,
    # _UID, _SYSTEMD_UNIT, MESSAGE, SYSLOG_IDENTIFIER, etc.
    ts_us = int(e.get("__REALTIME_TIMESTAMP", 0))
    if ts_us:
        # microseconds -> ISO timestamp
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(ts_us / 1e6, tz=timezone.utc).isoformat()
    else:
        ts = ""
    prio_map = {0: "emerg", 1: "alert", 2: "crit", 3: "err",
                4: "warning", 5: "notice", 6: "info", 7: "debug"}
    prio = prio_map.get(int(e.get("PRIORITY", 6)), "info")
    return {
        "timestamp": ts,
        "priority": prio,
        "unit": e.get("_SYSTEMD_UNIT", "") or "",
        "pid": int(e.get("_PID", 0)),
        "uid": int(e.get("_UID", 0)),
        "syslog_identifier": e.get("SYSLOG_IDENTIFIER", "") or "",
        "message": e.get("MESSAGE", "") or "",
    }


def _build_args(a):
    args = []
    if a.since:
        args += ["--since", a.since]
    if a.until:
        args += ["--until", a.until]
    if a.unit:
        args += ["--unit", a.unit]
    if a.priority:
        args += ["--priority", a.priority]
    if a.boot:
        args.append("--boot")
    if a.pid:
        args += ["_PID=" + str(a.pid)]
    if a.uid:
        args += ["_UID=" + str(a.uid)]
    if a.regex:
        args += ["--grep", a.regex]
    return args


def _summary(entries):
    if not entries:
        return {"total": 0}
    prios = {}
    units = {}
    for e in entries:
        prios[e["priority"]] = prios.get(e["priority"], 0) + 1
        if e["unit"]:
            units[e["unit"]] = units.get(e["unit"], 0) + 1
    return {
        "total": len(entries),
        "first_timestamp": entries[-1]["timestamp"],
        "last_timestamp": entries[0]["timestamp"],
        "priority_breakdown": prios,
        "top_units": dict(sorted(units.items(), key=lambda kv: -kv[1])[:5]),
    }


def main():
    ap = argparse.ArgumentParser(
        description="Structured journalctl queries on a Linux Managed device.")
    ap.add_argument("--since", help="e.g. '1 hour ago', '2026-06-25'")
    ap.add_argument("--until", help="e.g. '30 min ago', '2026-06-26'")
    ap.add_argument("--unit", help="systemd unit name (e.g. hermes-dashboard)")
    ap.add_argument("--priority",
                    choices=["emerg", "alert", "crit", "err", "warning",
                             "notice", "info", "debug"],
                    help="min priority (journalctl -p)")
    ap.add_argument("--boot", action="store_true",
                    help="only this boot (-b)")
    ap.add_argument("--pid", type=int, help="filter by _PID")
    ap.add_argument("--uid", type=int, help="filter by _UID")
    ap.add_argument("--regex", help="grep-style message filter")
    ap.add_argument("--limit", type=int, default=100, help="cap entries (default 100)")
    ap.add_argument("--target", default="localhost",
                    help="Managed device (v1: localhost only)")
    ap.add_argument("--json-only", action="store_true",
                    help="suppress human summary on stderr")
    a = ap.parse_args()
    if a.target != "localhost":
        print(json.dumps({"target": a.target,
                          "error": "remote targets not supported in v1",
                          "entries": []}, indent=2))
        return 1
    args = _build_args(a)
    raw, note = _run_journalctl(args)
    if raw is None:
        print(json.dumps({"target": "localhost", "error": note,
                          "entries": []}, indent=2))
        return 1
    entries = [_parse_entry(e) for e in raw]
    entries.sort(key=lambda e: e["timestamp"], reverse=True)
    if a.limit and a.limit > 0:
        entries = entries[:a.limit]
    print(json.dumps({"target": "localhost", "query_args": args,
                      "entry_count": len(entries),
                      "summary": _summary(entries), "entries": entries},
                     indent=2))
    if not a.json_only and entries:
        print(f"\n[systemd-journal-search] {len(entries)} entry/entries "
              f"on localhost", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)