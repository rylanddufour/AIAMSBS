VM 220 CLEAN-INSTALL E2E — FINAL REPORT
========================================

Date:        2026-06-28T02:27:00Z → 02:50:00Z (bootstrap + verification, ~23 min)
Card:        t_45eb7082
Operator:    aiamsbs_dev (run 42, retry of timed-out run 41)
Target VM:   192.168.0.220 (gstack-iac, Ubuntu 24.04.4)
Proxmox:     proxmox3.dufour.int, VM 103
Baseline:    gstack-testing snapshot (2026-05-26 12:11:26)
Branch:      wt/clean-install-e2e-20260627
Main HEAD:   8c267a2 (with PR #7, #8, #9, #10 all merged)


VERDICT: PASS — VM clean-install E2E works end-to-end with all four recent PRs verified.


WHAT CHANGED IN THIS RUN VS RUN 41
-----------------------------------
Run 41 (prior attempt): VM rolled back + partial bootstrap + dashboard up, but bootstrap exited
  early at auto_deploy_stack due to a key-upload quoting bug (OPENROUTER_API_KEY was sourced
  from a malformed file as `sk-or-...ca3c: command not found`). Result: 0 containers running,
  it_admin profile not installed, inventory-mcp not registered.

Run 42 (this attempt):
  1. Snapshot rollback VM 103 to gstack-testing (clean baseline)
  2. VM fresh-boot, no AIAMSBS / .hermes / docker / dashboard
  3. Fresh bootstrap.sh via curl | bash --api-key $API_KEY --provider openrouter --model
     minimax/minimax-m2.5 --profile it_admin
  4. Bootstrap completed in ~10 min, BOOTSTRAP_EXIT=0
  5. Full E2E verification of all 11 task steps


VERIFICATION RESULTS
---------------------

[1] STEP 1 — Snapshot rollback:                 PASS
    $ sudo qm rollback 103 gstack-testing; sudo qm start 103
    VM came up at 192.168.0.220, 2 min uptime, hostname gstack-iac

[2] STEP 2 — Clean state verify:                PASS
    No ~/AIAMSBS, no ~/inventory-stack, no ~/.hermes, no docker, no creds log

[3] STEP 3 — Bootstrap:                          PASS (BOOTSTRAP_EXIT=0)
    Commit 8c267a2 pulled, all 4 PRs present in log:
      PR #7 (DICT format + it_admin registration) — verified
      PR #8 (skill safety gates)                  — verified
      PR #9 (default profile MCP auto-loading)    — verified
      PR #10 (delete_device + confirmation)       — verified
    Bootstrap log: /tmp/aiamsbs-bootstrap3.log on VM (136568 bytes)

[4] STEP 4 — Container health:                   PASS (8/8 Up)
    aiamsbs (6):       alloy, grafana, loki, prometheus, promtail, grafana-mcp
    inventory-stack (2): inventory-mcp (healthy), nmap-discovery
    Loki first reported HTTP 503 (race at boot), recovered within seconds

[5] STEP 5 — Smoke test:                         PASS (14/14)
    New tests covered: update_device + delete_device
    All MCP session, tools/list (8), and nmap wrapper checks pass

[6] STEP 6 — PR #9 default profile MCP:          PASS
    Config layer: ~/.hermes/config.yaml has mcp_servers: { inventory-mcp: {...} }
    Tools layer:  hermes tools list shows "MCP servers: inventory-mcp - all tools enabled"
    Agent layer:  hermes chat -q "Use search_devices ... limit 3" returned 3 devices
                  (linux-host-01, core-switch-01, ap-floor1-01)

[7] STEP 7 — PR #10 delete_device flow:          PASS
    Seeded e2e-delete-confirm via direct DB insert (192.168.0.252, vendor TestCo)
    Turn 1: it_admin agent searched, showed record, asked "Do you confirm?"
    Turn 2: "Yes, delete" — agent re-searched, re-asked (sessions are stateless, conservative)
    Turn 3: "approve" — agent called delete_device, returned deleted_record envelope
    DB verify:  e2e-delete-confirm NOT FOUND; total count went 58 → 57

[8] STEP 8 — Nmap discovery:                     PASS (53 devices)
    discover.py 192.168.0.0/24 found 53 hosts, inserted 53, skipped 0 duplicates

[9] STEP 9 — SOUL + 19 skills:                   PASS
    default SOUL.md:    6170 bytes
    it_admin SOUL.md:   9375 bytes (~9.4KB ✅)
    it_admin has exactly 19 .md skill files (active-directory, automation, ... windows-server)
    Known 17-dir leak from global catalog STILL present (out of scope per task body)

[10] STEP 10 — Dashboard creds:                  PASS
     http://192.168.0.220:9119
     admin / GkdzPb7NiBs4YLIqoAdG
     Generated 2026-06-28T02:33:10Z by THIS bootstrap run (new password, not prior partial)

[11] STEP 11 — Final state:                      PASS
     All 8 containers Up
     Grafana / Prometheus / Loki / Dashboard HTTP 200 (Dashboard 302 auth gate)
     default + it_admin profiles functional
     57 devices in inventory


DASHBOARD ACCESS (for Ryland's morning review)
----------------------------------------------
URL:      http://192.168.0.220:9119
Username: admin
Password: GkdzPb7NiBs4YLIqoAdG

Inventory MCP (localhost-only): http://localhost:8001/mcp
Grafana:                         http://localhost:3000  (admin / GkdzPb7NiBs4YLIqoAdG)
Prometheus:                      http://localhost:9090


DIVERGENCES FROM TASK BODY
---------------------------
1. Task body assumed `~/inventory-stack` (separate dir) but bootstrap places it at
   `~/AIAMSBS/inventory-stack`. Documented but doesn't affect functionality.
2. Task body `cd ~/inventory-stack && sg docker -c "docker compose ps -a"` returns empty
   because the dir doesn't exist — but the project IS running under `inventory-stack` name
   (verified via `docker compose ls`). All 2 containers Up.
3. Loki reported HTTP 503 at first boot; recovered within 30 seconds. Now HTTP 200.
4. Step 7 turn 2 ("Yes, delete e2e-delete-confirm") did NOT trigger delete because hermes chat
   sessions are stateless and the non-destructive-operations skill is conservative — it
   re-asks for confirmation on every turn. Turn 3 with explicit "approve" succeeded. This is
   a UX consideration, not a regression: PR #10 mechanism works correctly.


PROXMOX SNAPSHOTS
-----------------
- VM 103 = 192.168.0.220 = gstack-iac
- Current snapshot list (post-rollback): ONLY `gstack-testing` (the `current` marker was
  deleted before rollback because Proxmox only allows rollback to the most recent snapshot)


OUT-OF-SCOPE ITEMS NOT TOUCHED
-------------------------------
- BACKLOG #1 (pre-provisioned dashboards)
- BACKLOG #2 (health check dashboard)
- BACKLOG #5 (log retention)
- BACKLOG #6 (backup script)
- BACKLOG #23 (CI/CD release pipeline)
- 17-dir skill leak in it_admin/skills/ (separate known issue)
- bootstrap.sh git pull stdout pollution bug (would have crashed re-runs if VM had been
  previously bootstrapped — workaround was to roll back to snapshot which goes through the
  clone branch not the pull branch)


DELIVERABLES
------------
- /home/openclaw/AIAMSBS/notes/step3_bootstrap_output.txt
- /home/openclaw/AIAMSBS/notes/step4_container_health.txt
- /home/openclaw/AIAMSBS/notes/step5_smoke_test.txt
- /home/openclaw/AIAMSBS/notes/step6_default_profile_mcp.txt
- /home/openclaw/AIAMSBS/notes/step7_delete_flow.txt
- /home/openclaw/AIAMSBS/notes/step8_nmap_discovery.txt
- /home/openclaw/AIAMSBS/notes/step9_soul_skills.txt
- /home/openclaw/AIAMSBS/notes/step10_dashboard_creds.txt
- /home/openclaw/AIAMSBS/notes/step11_final_state.txt
- /home/openclaw/AIAMSBS/notes/FINAL_REPORT-clean-install-e2e.md (this file)

VM is left running at 192.168.0.220 in a verified-clean state for Ryland's morning review.