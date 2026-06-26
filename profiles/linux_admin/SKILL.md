# linux_admin Skill Routing Map

This Profile bundles three Linux-specific **Skills**. They live under
`profiles/linux_admin/skills/<name>/` and ship in a later milestone
(this file is the **design**, not the implementation — see `~/AIAMSBS/BACKLOG.md`
#16).

All three Skills are read-only by default. They never mutate a Managed
device on their own; they return evidence for the Agent to act on.

## Skills

### `apt-history-analyzer`

- **Lives at:** `profiles/linux_admin/skills/apt-history-analyzer/`
- **What it does:** Parses `/var/log/apt/history.log` and
  `/var/log/dpkg.log` on a Debian/Ubuntu Managed device. Returns a
  human-readable timeline of installs, upgrades, removals, and the
  apt command that triggered them. Equivalent tool: `yum history` /
  `dnf history list` on RHEL-family — the skill detects the distro
  and adapts.
- **When the Customer asks:**
  - "What got installed on `<host>` yesterday?"
  - "Did anyone run `apt upgrade` last night?"
  - "When did package X get installed?"
  - "Why did the apt mirror change?"
- **Returns:** ordered list `{timestamp, command, package, version,
  requested_by}` per event. No side effects.

### `systemd-journal-search`

- **Lives at:** `profiles/linux_admin/skills/systemd-journal-search/`
- **What it does:** Runs structured `journalctl` queries against a
  Managed device via SSH. Supports `--since`, `--until`, `-u <unit>`,
  `-p <priority>`, `-b` (boot), `_PID=`, `_UID=`, message regex.
  Wraps raw `journalctl` so the Agent doesn't have to remember the
  flags.
- **When the Customer asks:**
  - "What does this journal error mean?"
  - "Show me the last 100 lines of `<svc>` from 2 a.m. last night."
  - "Filter `<host>` logs for `OOM` since the boot."
  - "Did service X crash? When?"
- **Returns:** filtered journal lines + a one-line summary (count,
  first/last timestamp, top recurring message). Read-only.

### `service-troubleshooter`

- **Lives at:** `profiles/linux_admin/skills/service-troubleshooter/`
- **What it does:** Runs a fixed diagnostic **Workflow** against a
  Managed device: `systemctl status` → `systemctl list-dependencies`
  → `journalctl -u <svc> -p err -n 200` → `systemctl cat <svc>` for
  unit file → check ExecStart paths exist → check socket / timer
  preconditions → `ss -tlnp` for the listening port. Bundles the
  results into a structured diagnosis report.
- **When the Customer asks:**
  - "Why did this service crash?"
  - "`<svc>` is down — figure out why."
  - "`<svc>` failed to start — walk me through what to check."
  - "Is the failure in the unit file, the binary, or upstream?"
- **Returns:** `{status, hypothesis, evidence_quotes, suggested_fix,
  verification_step}`. Always ends with a named verification step —
  the Agent does not declare "fixed" until the Customer confirms the
  verification passes.

## Routing rules (summary)

| Customer question                                            | Skill                        |
|--------------------------------------------------------------|------------------------------|
| "What was installed yesterday?"                             | `apt-history-analyzer`       |
| "What does this journal error mean?" / "Show me logs for…"   | `systemd-journal-search`     |
| "Why did this service crash?" / "`<svc>` is down"            | `service-troubleshooter`     |
| "Is disk full on `<host>`?"                                  | none (use raw `df`/`du`)     |
| "What's listening on `<host>`?"                              | none (use raw `ss`)          |

If the Skill doesn't exist yet, fall back to the raw command — the
Agent knows the syntax. Skills add structure; they don't add
authority.

## Forward-compatibility

When `~/AIAMSBS/ansible/` (BACKLOG #15) ships, this Profile can also
invoke ansible playbooks against Managed devices. The Skills above
will become ansible modules where it makes sense (e.g.
`apt-history-analyzer` can call `ansible.builtin.package` facts). No
changes to the Customer-facing routing — the question stays the same,
the tool underneath becomes faster.

## Version

- **v1.0** — 2026-06-25 (design only; Skills not yet implemented)
- See `~/AIAMSBS/BACKLOG.md` #16