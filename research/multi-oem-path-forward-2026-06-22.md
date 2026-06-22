# AIAMSBS Multi-OEM Path Forward

**Date:** 2026-06-22
**Status:** Strategic recommendation — synthesized from research (see companion doc)
**Companion:** [`multi-oem-skill-research-2026-06-22.md`](./multi-oem-skill-research-2026-06-22.md)
**Tracks:** `BACKLOG.md` item #12, Kanban task `t_48b5cc06`

---

## TL;DR

We don't need to build 6 exporters from scratch. **5 of 6 OEMs in scope have mature Prometheus exporters we can wrap.** The platform investment is in the **per-OEM integration template**: exporter deployment + syslog-to-Loki + Grafana dashboard + Hermes skill wrapping the management APIs + alert rules.

### Recommended sequence

| Phase | OEM(s) | Rationale |
|---|---|---|
| **v1.0 — ship** | Windows Server | Biggest gap in current stack; mature exporter (windows_exporter, 44 collectors); core SMB workload |
| **v1.0 — ship** | Ubiquiti UniFi | Easy win via `unpoller/unpoller` (2,650★, very active); covers AP/switch/gateway/cameras; ships its own Grafana dashboards |
| **v1.1** | Cisco Catalyst (IOS + CatOS) | Largest installed base for managed switches; `snmp_exporter` (official, 2,100★) handles it |
| **v1.1** | Linux (expanded scope) | Mostly there via host node_exporter; v1.1 fills in *management* layer (systemd, packages, config drift) |
| **v1.x — conditional** | VMware vSphere | Only if 2+ customers in pipeline use it; exporter exists but maintainer stepping down |
| **Defer** | Aruba Networks | Community exporter nascent (12★, last commit 2023); revisit when mature or customer-driven |

---

## Strategic frame: wrap, don't build

The research confirms every OEM in scope has at least one Prometheus exporter already. The exporter code is not the work — the work is the **management layer above it**: discovery, configuration, backup, health checks, and a Hermes skill wrapping the management APIs. AIAMSBS's role is OEM **integrator**, not exporter **author**.

### Why this matters

- **Time-to-market:** a wrap-only OEM ships in days, not months
- **Maintenance:** third-party exporters maintain their own MIB / API coverage; AIAMSBS inherits that
- **Quality:** 2,650★ unpoller is better-tested than anything we'd write in v1.0
- **Security:** vendors update their exporters faster than we'd update our own

### Where we DO build

- The per-OEM Hermes skill (management API wrapper)
- Grafana dashboards tailored to AIAMSBS's alert conventions
- Alert rules tied to the existing alertmanager
- The integration template itself (so adding an OEM #7 is mechanical)

---

## The "OEM integration" template

Every new OEM follows the same shape. AIAMSBS should ship this template as a **`oem-integration-template/`** skill that new OEM skills fork.

### Per-OEM deliverable list

| Layer | What it looks like in AIAMSBS |
|---|---|
| **Exporter service** | New entry in `docker-compose.yml` running the OEM's exporter (windows_exporter, unpoller, snmp_exporter, etc.) |
| **Scrape config** | New job in Prometheus's scrape config pointing at the exporter |
| **Syslog forwarding** | OEM device config → Promtail at port 1514 (already in AIAMSBS) |
| **Grafana dashboard** | A provisioned dashboard JSON for this OEM |
| **Alert rules** | OEM-specific alert rules loaded into the existing alertmanager |
| **Hermes skill** | A skill wrapping the OEM's management API |
| **Connection profile** | Stored in `~/.hermes/secrets/oem/<vendor>/` — credentials, SNMP community strings, controller URLs |

### Per-OEM skill shape

```
oem/<vendor>/
  ├── SKILL.md                # what the skill does, how to invoke
  ├── manage_<vendor>.py      # core: API wrappers
  ├── deploy_exporter.py      # one-time exporter deployment
  ├── backup_config.py        # config backup (where applicable)
  ├── discover.py             # enumerate devices/instances
  ├── health_check.py         # pre-flight checks
  └── alerts.md               # human-readable alert runbook
```

### Common Python libs across skills

- `requests` (REST APIs everywhere)
- `paramiko` / `netmiko` (SSH where no REST)
- `pysnmp` (SNMP-based)
- `pywinrm` (Windows)
- `pyvmomi` / `govc` (VMware)

AIAMSBS should ship a shared `oem_common/` library that all OEM skills import — handles connection pooling, credential loading, retry/backoff, structured logging.

---

## Priority reasoning

### Phase 1 (v1.0 — ship): Windows + UniFi

These two together cover the largest gap in the current stack and the easiest win:

- **Windows Server:** AIAMSBS is currently Linux-only at the agent level. Windows is the dominant SMB workload for our target market. `windows_exporter` is mature (44 collectors including IIS, AD, SQL, file shares). The skill is the bigger lift (WinRM config + PSRemoting + AD integration), but it's bounded.
- **UniFi:** UnPoller is a perfect fit — 2,650★, very active, covers APs/switches/gateways/cameras, includes Grafana dashboards and Prometheus alerts in the repo. The skill is mostly REST API calls to the controller. **Lowest-effort, highest-visibility win.**

### Phase 2 (v1.1 — ship): Cisco + Linux expansion

- **Cisco Catalyst:** Largest installed base of managed switches. `snmp_exporter` (official Prometheus, 2,100★) handles it. The skill is mostly netmiko for config + SNMP config management. CatOS EOL-but-still-deployed means we need both SNMPv1 and SNMPv2c handling paths.
- **Linux:** Mostly covered today via the host node_exporter. The v1.1 expansion is the *management* layer: systemd service orchestration, package management, config drift detection. This becomes "Linux admin assistant" more than "Linux monitoring."

### Phase 3 (v1.x — conditional): VMware

- Only pursue if 2+ customers in the pipeline actually use vSphere.
- `pryorda/vmware_exporter` is active but maintainer stepping down. Watch for a community fork before committing.
- The skill is substantial: pyvmomi is the right tool, but ESXi/vCenter has the deepest API surface of any OEM in scope. **Estimate: 2–3x the effort of a UniFi skill.**

### Phase 4 (defer): Aruba

- The community exporter (`slashdoom/aruba_exporter`) is at 12 stars, last commit 2023, in early development.
- Building our own exporter is a multi-month investment with unclear ROI.
- Better path: ship a thin SNMP-based monitoring skill (using `snmp_exporter` + Aruba MIBs) and skip the management API until community tooling matures or a customer specifically needs it.
- Revisit in 6–12 months.

---

## Risks + open questions

1. **Windows WinRM/PSRemoting friction.** Customers need WinRM enabled on their Windows hosts. This is a config change requiring admin on each Windows box. AIAMSBS's bootstrap can't reach into customer Windows machines without explicit permission. → *Mitigation:* ship a PowerShell script the customer runs once per host to enable WinRM and create a service account.

2. **vmware_exporter single-maintainer risk.** If the project goes unmaintained, we'd be forking. → *Mitigation:* monitor for community fork; if none by v1.x planning time, build our own using `govc`.

3. **Aruba fragmentation.** Aruba has 4 product lines (CX, Switch, Instant, Central) with 4 different APIs. → *Mitigation:* phase it — start with SNMP + RESTCONF for CX, defer Central and Instant.

4. **Per-customer OEM mix is heterogeneous.** Not every customer has all 6 OEMs. The AIAMSBS compose stack should support optional services (the current pattern handles this — services are gated by env vars).

5. **CatOS SNMPv1.** Legacy CatOS only supports SNMPv1 with weak community strings. Modern SNMPv3 isn't available. → *Mitigation:* ship a separate `snmp_v1` scrape config for legacy devices; document the security tradeoff.

6. **Syslog forwarding at customer sites.** Most of these OEMs need syslog forwarding configured on each device. AIAMSBS doesn't auto-reach into customer devices. → *Mitigation:* each OEM skill includes a setup script the customer runs once per device to configure syslog forwarding + exporter-side scraping.

---

## Concrete next steps

1. **Move research + path-forward into the repo.** *(Done — both in `research/`.)*
2. **Update `BACKLOG.md` item #12** with the priority sequence above so the backlog stays a living artifact.
3. **Build the `oem-integration-template/` skill** — the shared scaffolding every OEM skill forks from. This is Phase 0 and unblocks every Phase 1+ OEM.
4. **Phase 1a: Windows Server skill** — biggest gap, most-requested for SMB.
5. **Phase 1b: UniFi skill** — easy win, demonstrates the template working.
6. **Re-evaluate after Phase 1 ships** — adjust based on customer feedback + which OEMs are actually being requested.

---

## What this looks like in 6 months

If we ship the template + Windows + UniFi in v1.0 and Cisco + Linux expansion in v1.1:

- 4 of 6 OEMs in scope are AIAMSBS-native
- The remaining 2 (VMware, Aruba) are explicitly conditional
- Adding a new OEM in v2.0 is a fork-the-template exercise, not a research project
- The AIAMSBS platform becomes genuinely "AI-managed" rather than "AI-observed" — the skill layer is what makes it different from a stock Prometheus + Grafana install

That's the differentiation. Anyone can install Prometheus + Grafana. Almost nobody can ship a coherent *management layer* across six heterogeneous OEMs through a single AI interface. That's what AIAMSBS is for.
