#!/usr/bin/env python3
"""service-troubleshooter — diagnose a failed systemd service.

Runs a fixed diagnostic Workflow:
  1. systemctl is-active / status
  2. systemctl list-dependencies
  3. journalctl -u <svc> -p err -n 200
  4. systemctl cat <svc> (unit file)
  5. Check ExecStart binary paths exist
  6. Check socket/timer preconditions
  7. ss -tlnp for the listening port

Returns {status, hypothesis, evidence_quotes, suggested_fix, verification_step}.

Usage: service-troubleshooter.py SERVICE [--target HOST]

v1: only `localhost` honored; SSH for remote Managed devices is future.
Exits 0 on success, 1 on infrastructure failure.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run(cmd, timeout=15):
    bin_ = shutil.which(cmd[0])
    if not bin_:
        return None, f"<{cmd[0]} not found>"
    try:
        r = subprocess.run([bin_] + cmd[1:], capture_output=True, text=True,
                           timeout=timeout, check=False)
        return (r.returncode, (r.stdout or "") + (r.stderr or "")), ""
    except subprocess.TimeoutExpired:
        return None, f"<{cmd[0]} timed out>"
    except OSError as e:
        return None, f"<{cmd[0]} failed: {e}>"


def _check_step(label, cmd):
    result, note = _run(cmd)
    if result is None:
        return {"step": label, "command": " ".join(cmd), "ok": False,
                "output": note, "evidence": ""}
    rc, out = result
    snippet = out.strip().splitlines()[:30]
    return {"step": label, "command": " ".join(cmd), "ok": rc == 0,
            "exit_code": rc, "output_lines": len(out.splitlines()),
            "evidence": "\n".join(snippet)}


def _extract_execstart(unit_file_text):
    # Find ExecStart= line, strip env-var prefix, return path
    for line in unit_file_text.splitlines():
        line = line.strip()
        if line.startswith("ExecStart="):
            cmd = line[len("ExecStart="):].strip()
            # strip leading env vars like "FOO=bar BAZ=qux"
            while "=" in cmd.split()[0] if cmd.split() else False:
                cmd = " ".join(cmd.split()[1:])
            return cmd.split()[0] if cmd.split() else ""
    return ""


def _main_logic(service, target):
    if target != "localhost":
        return {"target": target, "service": service,
                "error": "remote targets not supported in v1"}, 1
    steps = []
    # 1. status
    steps.append(_check_step("status",
                            ["systemctl", "status", service, "--no-pager", "-n", "5"]))
    active_rc = steps[0]["exit_code"] if "exit_code" in steps[0] else -1
    # 2. dependencies
    steps.append(_check_step("dependencies",
                            ["systemctl", "list-dependencies", service, "--no-pager", "-n", "20"]))
    # 3. errors
    steps.append(_check_step("journal_errors",
                            ["journalctl", "-u", service, "-p", "err", "-n", "50",
                             "--no-pager"]))
    # 4. unit file
    cat = _check_step("unit_file",
                      ["systemctl", "cat", service, "--no-pager"])
    steps.append(cat)
    execstart = ""
    if cat["ok"] and cat.get("evidence"):
        execstart = _extract_execstart(cat["evidence"])
    # 5. execstart path exists?
    if execstart:
        exists = Path(execstart).exists()
        steps.append({"step": "execstart_exists", "path": execstart,
                      "ok": exists,
                      "evidence": f"{execstart}: {'exists' if exists else 'MISSING'}"})
    # 6. timer/socket preconditions
    for kind in ["socket", "timer"]:
        dep_rc, dep_out = (_run(["systemctl", "list-dependencies",
                                 f"{service}.{kind}", "--no-pager"])[0] or
                            (-1, ""))
        if dep_rc == 0 and dep_out.strip():
            steps.append({"step": f"{kind}_dependency",
                          "output_lines": len(dep_out.splitlines()),
                          "ok": True, "evidence": dep_out.strip()[:500]})
    # 7. listening ports for service
    listening = _check_step("listening_ports",
                            ["ss", "-tlnp", f"sport = :0"])
    if listening["ok"]:
        steps.append(listening)
    # synthesize hypothesis
    errs = [s for s in steps if s["step"] == "journal_errors"]
    hypothesis = "Unknown"
    if not steps[0].get("ok", False):
        hypothesis = f"Service is not active (systemctl status exit={active_rc})"
    elif execstart and not Path(execstart).exists():
        hypothesis = f"ExecStart binary missing: {execstart}"
    elif errs and errs[0]["ok"] and errs[0]["evidence"].strip():
        first_err = errs[0]["evidence"].splitlines()[0][:200]
        hypothesis = f"Recent error in journal: {first_err}"
    else:
        hypothesis = "No clear failure signal in status/journal/unit file"
    # suggested fix
    if "not active" in hypothesis:
        suggested_fix = f"Run: sudo systemctl start {service}"
        verification_step = f"systemctl is-active {service}  # expect: active"
    elif "missing" in hypothesis.lower():
        suggested_fix = f"Reinstall the package that provides {execstart}"
        verification_step = f"ls -la {execstart}  # expect: file exists"
    elif "error in journal" in hypothesis:
        suggested_fix = f"Inspect full journal: journalctl -u {service} -p err -n 200"
        verification_step = f"systemctl status {service} --no-pager  # no new errors"
    else:
        suggested_fix = f"Inspect: journalctl -u {service} --no-pager"
        verification_step = f"systemctl status {service} --no-pager"
    return {
        "target": "localhost", "service": service,
        "status": "inactive" if not steps[0].get("ok", False) else "unknown",
        "hypothesis": hypothesis,
        "suggested_fix": suggested_fix,
        "verification_step": verification_step,
        "steps": steps,
    }, 0


def main():
    ap = argparse.ArgumentParser(
        description="Diagnose a failed systemd service on a Linux Managed device.")
    ap.add_argument("service", help="systemd unit name (no .service suffix required)")
    ap.add_argument("--target", default="localhost",
                    help="Managed device (v1: localhost only)")
    ap.add_argument("--json-only", action="store_true",
                    help="suppress human summary on stderr")
    a = ap.parse_args()
    svc = a.service if a.service.endswith(".service") else a.service + ".service"
    out, rc = _main_logic(svc, a.target)
    print(json.dumps(out, indent=2, default=str))
    if not a.json_only:
        h = out.get("hypothesis", "")
        f = out.get("suggested_fix", "")
        v = out.get("verification_step", "")
        print(f"\n[service-troubleshooter] {svc}", file=sys.stderr)
        if h:
            print(f"  hypothesis: {h}", file=sys.stderr)
        if f:
            print(f"  fix:        {f}", file=sys.stderr)
        if v:
            print(f"  verify:     {v}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)