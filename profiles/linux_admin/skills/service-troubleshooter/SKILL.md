---
name: service-troubleshooter
title: Systemd Service Troubleshooter
description: Run a structured diagnostic Workflow against a failed systemd service on a Linux Managed device. Triggered when the user asks why a service crashed or won't start.
trigger: When the user asks "why did this service crash?", "<svc> is down — figure out why", "<svc> failed to start — walk me through what to check", or wants root-cause diagnosis of a service failure.
---

# Service Troubleshooter

Run a fixed diagnostic Workflow against a failed systemd service on a
Managed device. Returns a structured diagnosis with hypothesis + suggested
fix + verification step so the Agent (and Customer) can act on it.

## When to use this skill

Trigger this skill when the user says any of:

- "Why did this service crash?"
- "`<svc>` is down — figure out why."
- "`<svc>` failed to start — walk me through what to check."
- "Is the failure in the unit file, the binary, or upstream?"
- "Diagnose `<svc>` and propose a fix."

## How to use it

1. **Extract the service name** from the prompt. Strip `.service` suffix if
   the user included it.

2. **Run the troubleshooter script**:
   ```bash
   $TROUBLESHOOTER_DIR/scripts/service-troubleshooter.py hermes-dashboard
   ```
   `$TROUBLESHOOTER_DIR` is the directory this SKILL.md lives in.

3. **Report the diagnosis** (status, hypothesis, suggested fix, verification
   step) back to the user. Always cite the verification step — never declare
   "fixed" without it.

## What the script does

`scripts/service-troubleshooter.py`:

1. **`systemctl status <svc>`** — checks if active + last 5 lines of status.
2. **`systemctl list-dependencies <svc>`** — surfaces unmet deps.
3. **`journalctl -u <svc> -p err -n 50`** — pulls recent errors.
4. **`systemctl cat <svc>`** — full unit file. Extracts `ExecStart=` path.
5. **Check ExecStart path exists** on disk (catches broken package installs).
6. **List socket/timer preconditions** if any (e.g. `<svc>.socket`).
7. **`ss -tlnp sport = :0`** — listening sockets (general signal).
8. **Synthesizes a hypothesis**:
   - Service not active → status failure hypothesis
   - ExecStart missing → binary reinstall hypothesis
   - Recent errors → first error line as hypothesis
   - Otherwise → "no clear signal; inspect journal"
9. **Returns** `{status, hypothesis, suggested_fix, verification_step,
   steps: [...]}` so the Agent can quote specific evidence.

## Defaults

| Knob | Default | Override |
|---|---|---|
| Target host | `localhost` | `--target HOST` (v1: only `localhost` accepted; exit 1 otherwise) |
| Journal depth | 50 entries | (hardcoded for v1; future: --journal-lines) |

## Output shape

```json
{
  "target": "localhost",
  "service": "hermes-dashboard.service",
  "status": "inactive",
  "hypothesis": "Service is not active (systemctl status exit=3)",
  "suggested_fix": "Run: sudo systemctl start hermes-dashboard",
  "verification_step": "systemctl is-active hermes-dashboard  # expect: active",
  "steps": [
    {"step": "status", "ok": false, "exit_code": 3, "evidence": "..."},
    {"step": "dependencies", "ok": true, "evidence": "..."},
    {"step": "journal_errors", "ok": true, "evidence": "..."},
    {"step": "unit_file", "ok": true, "evidence": "..."},
    {"step": "execstart_exists", "path": "...", "ok": true, "evidence": "..."}
  ]
}
```

## Out of scope (v1)

- **SSH to managed devices** — script exits 1 if `--target` is not
  `localhost`. SSH support is future work.
- **Auto-remediation** — script NEVER starts/stops services. It diagnoses;
  the Agent proposes; the Customer approves.
- **Non-systemd init systems** — OpenRC, SysV init, runit not supported
  (AIAMSBS hosts are Ubuntu + systemd).
- **Performance profiling** — strace, perf, eBPF not in scope. Use dedicated
  profiling tools (future).

## Forward compatibility

When BACKLOG #15 (ansible container) ships, this skill becomes a thin
ansible wrapper — `ansible.builtin.systemd` facts + `ansible.builtin.service`
state checks + `ansible.builtin.shell` for journalctl. The Customer-facing
interface (this skill) stays unchanged.

## Version

- Added: 2026-06-26 (Task: implement linux_admin Skills)
- Status: v1, localhost-only
- Depends on: `linux_admin` profile, systemd + journalctl + ss on target host