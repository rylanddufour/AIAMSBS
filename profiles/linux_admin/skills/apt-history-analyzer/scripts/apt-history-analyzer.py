#!/usr/bin/env python3
"""apt-history-analyzer — parse apt/dpkg history on a Linux Managed device.

Debian/Ubuntu: parses /var/log/apt/history.log + /var/log/dpkg.log (+ .gz).
RHEL-family: runs `dnf history list` or `yum history`. Returns a structured
install/upgrade/remove/purge timeline.

Usage: apt-history-analyzer.py [--since DAYS] [--limit N]
       [--source auto|apt|dpkg|rhel] [--target HOST]

v1: only `localhost` honored; SSH for remote Managed devices is future.
Exits 0 on success, 1 on infrastructure failure.
"""
import argparse, gzip, json, re, shutil, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

APT_DIRS = [Path("/var/log/apt")]
DPKG_LOGS = [Path("/var/log/dpkg.log")]
MAX_ROT = 5


def _open(p):
    if str(p).endswith(".gz"):
        return gzip.open(p, "rt", encoding="utf-8", errors="replace")
    return open(p, "r", encoding="utf-8", errors="replace")


def _rotated(dir_, prefix):
    if not dir_.exists():
        return []
    fs = [p for p in dir_.iterdir()
          if p.name.startswith(prefix) and p.name != prefix]
    fs.sort(key=lambda p: p.name, reverse=True)
    return fs[:MAX_ROT]


def _ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc).isoformat()
    except ValueError:
        return s


def _parse_apt(text):
    out, cur = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Start-Date:"):
            cur = {"timestamp": _ts(s[11:].strip()),
                   "command": "", "requested_by": "", "packages": []}
        elif cur is None:
            continue
        elif s.startswith("Commandline:"):
            cur["command"] = s[11:].strip()
        elif s.startswith("Requested-By:"):
            cur["requested_by"] = s[13:].strip()
        elif s.startswith(("Install:", "Upgrade:", "Remove:", "Purge:",
                           "Downgrade:", "Reinstall:")):
            op = s.split(":", 1)[0].lower()
            for e in s.split(":", 1)[1].strip().split(","):
                e = e.strip()
                if not e:
                    continue
                m = re.match(r"^([^:]+):(\S+)\s+\((.*)\)\s*$", e)
                if m:
                    n, a, r = m.groups()
                    vs = [v.strip() for v in r.split(",")
                          if v.strip() and v.strip() != "automatic"]
                    cur["packages"].append({"op": op, "name": n, "arch": a,
                                            "versions": vs,
                                            "automatic": "automatic" in r})
        elif s.startswith("End-Date:"):
            if cur and cur["packages"]:
                out.append(cur)
            cur = None
    return out


def _parse_dpkg(text):
    # dpkg.log: TS verb pkg:arch oldver newver
    out, pat = [], (r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
                    r"(install|upgrade|remove|purge|configure)\s+"
                    r"([^:]+):(\S+)\s+(\S+)\s+(\S+)\s*$")
    for line in text.splitlines():
        m = re.match(pat, line)
        if not m:
            continue
        ts, op, n, a, ov, nv = m.groups()
        out.append({"timestamp": ts, "command": f"dpkg {op}",
                    "requested_by": "", "source": "dpkg",
                    "packages": [{"op": op, "name": n, "arch": a,
                                  "versions": [v for v in (ov, nv)
                                               if v and v != "<none>"],
                                  "automatic": False}]})
    return out


def _read_apt():
    files, evs = [], []
    for base in APT_DIRS:
        main = base / "history.log"
        if main.exists():
            with _open(main) as f:
                evs.extend(_parse_apt(f.read()))
            files.append(main)
        for rot in _rotated(base, "history.log"):
            with _open(rot) as f:
                evs.extend(_parse_apt(f.read()))
            files.append(rot)
    return evs, files


def _read_dpkg():
    files, evs = [], []
    for main in DPKG_LOGS:
        if not main.exists():
            continue
        rot = [p for p in main.parent.iterdir()
               if p.name.startswith("dpkg.log") and p.name != main.name]
        rot.sort(key=lambda p: p.name, reverse=True)
        for path in [main] + rot[:MAX_ROT]:
            with _open(path) as f:
                evs.extend(_parse_dpkg(f.read()))
            files.append(path)
    return evs, files


def _read_rhel():
    bin_ = shutil.which("dnf") or shutil.which("yum")
    if not bin_:
        return [], "<not-found>", ""
    try:
        r = subprocess.run([bin_, "history", "list"], capture_output=True,
                           text=True, timeout=30, check=False)
    except (subprocess.TimeoutExpired, OSError) as e:
        return [], bin_, f"<{bin_} failed: {e}>"
    raw = (r.stdout or "") + (r.stderr or "")
    evs = _parse_rhel(raw)
    return evs, bin_, (f"{bin_} returned no parseable rows"
                       if not evs and raw else "")


def _parse_rhel(raw):
    # ID | Command line | Date(/Time) | Action(s) | Altered
    out, pat = [], (r"^\s*(\d+)\s+\|\s+([^|]+?)\s+\|\s+([^|]+?)\s+\|"
                    r"\s+([^|]+?)\s+\|\s+(\d+)")
    for line in raw.splitlines():
        if not line or line.lstrip().startswith(("ID ", "---")):
            continue
        m = re.match(pat, line)
        if not m:
            continue
        id_, cmd, when, act, alt = (g.strip() for g in m.groups())
        out.append({"timestamp": when, "command": cmd, "requested_by": "",
                    "source": "rhel", "history_id": id_,
                    "packages": [{"op": act, "name": f"<{alt} pkgs>",
                                  "arch": "", "versions": [],
                                  "automatic": False}]})
    return out


def _filter(events, since_days, limit):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)
              if since_days else None)
    out = []
    for ev in events:
        if cutoff is not None:
            try:
                dt = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
            except (ValueError, KeyError):
                dt = None
            if dt is not None and dt < cutoff:
                continue
        out.append(ev)
    out.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return out[:limit] if limit and limit > 0 else out


def _summary(events):
    if not events:
        return {"total": 0}
    ops, pkgs = {}, {}
    for ev in events:
        for p in ev.get("packages", []):
            ops[p["op"]] = ops.get(p["op"], 0) + 1
            pkgs[p["name"]] = pkgs.get(p["name"], 0) + 1
    return {"total_events": len(events),
            "first_timestamp": events[-1].get("timestamp", ""),
            "last_timestamp": events[0].get("timestamp", ""),
            "ops_breakdown": ops,
            "top_packages": dict(sorted(pkgs.items(),
                                        key=lambda kv: -kv[1])[:10])}


def main():
    ap = argparse.ArgumentParser(
        description="Parse apt/dpkg/yum/dnf history on a Linux Managed device.")
    ap.add_argument("--since", type=float, default=None,
                    help="only events from last N days")
    ap.add_argument("--limit", type=int, default=None, help="cap event count")
    ap.add_argument("--source", default="auto",
                    choices=["auto", "apt", "dpkg", "rhel"],
                    help="which log source to read (default: auto-detect)")
    ap.add_argument("--target", default="localhost",
                    help="Managed device (v1: localhost only)")
    ap.add_argument("--json-only", action="store_true",
                    help="suppress human summary on stderr")
    a = ap.parse_args()
    if a.target != "localhost":
        print(json.dumps({"target": a.target,
                          "error": "remote targets not supported in v1",
                          "events": []}, indent=2))
        return 1
    sources, files, evs, notes = [], [], [], []
    order = ["apt", "dpkg", "rhel"] if a.source == "auto" else [a.source]
    for src in order:
        if src == "apt":
            e, f = _read_apt()
            if e or f:
                sources.append("apt")
                files.extend(str(x) for x in f)
                for x in e:
                    x.setdefault("source", "apt")
                evs.extend(e)
        elif src == "dpkg":
            e, f = _read_dpkg()
            if e or f:
                sources.append("dpkg")
                files.extend(str(x) for x in f)
                evs.extend(e)
        elif src == "rhel":
            e, b, note = _read_rhel()
            if b != "<not-found>":
                sources.append(f"rhel:{b}")
                if note:
                    notes.append(note)
                evs.extend(e)
    events = _filter(evs, a.since, a.limit)
    print(json.dumps({"target": "localhost", "sources": sources,
                      "files_read": sorted(set(files)),
                      "since_days": a.since, "limit": a.limit,
                      "event_count": len(events),
                      "summary": _summary(events), "events": events,
                      "notes": notes}, indent=2, default=str))
    if not a.json_only and events:
        print(f"\n[apt-history-analyzer] {len(events)} event(s) from "
              f"{', '.join(sources) or 'no source'} on localhost",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)