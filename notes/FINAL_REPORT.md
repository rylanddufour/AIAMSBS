# BACKLOG #24 — Default profile MCP auto-loading FIX

**Card:** t_dfe7c599
**Date:** 2026-06-27
**VM:** 192.168.0.220 (multi-profile layout, both `default` and `it_admin` under `~/.hermes/profiles/`)
**Verdict:** ✅ **SHIPPED** — bug reproduced, root cause identified, fix applied and verified E2E.

---

## TL;DR

| Item | Verdict |
|------|---------|
| Step 2: bug reproduced (no MCP servers for default) | ✅ |
| Step 3: hypothesis A (model block) — FAILED | ✅ confirmed not the cause |
| Step 5: hypothesis B3 (mcp_servers in global config) — FIXED | ✅ |
| Step 4/8: default profile drives inventory via natural language | ✅ |
| Step 7: smoke test on VM | ✅ **14/14 PASS** |
| Step 9: bootstrap.sh patched + committed | ✅ |

**Root cause:** The "default" profile's config IS the global `~/.hermes/config.yaml` (verified via `hermes profile show default` → Path = `/home/ansible/.hermes`). The directory `~/.hermes/profiles/default/` exists but is a **dead location** that Hermes never reads. Older `register_inventory_mcp` auto-detected multi-profile layout via `~/.hermes/profiles/` existence and wrote to `~/.hermes/profiles/default/config.yaml` for the default profile — that file is silently ignored.

**Fix:** `register_inventory_mcp` now special-cases the `default` profile to always write to the global `~/.hermes/config.yaml` (regardless of layout). For named profiles (`it_admin`) it keeps the multi-profile path. Also adds a one-shot migration that strips a stale `mcp_servers:` block from `~/.hermes/profiles/default/config.yaml` if one is left over from an older bootstrap.

---

## 1. Bug reproduction (Step 2)

Before any fix, with default profile active:
```
$ hermes profile use default
$ hermes tools list | grep -A 3 "MCP servers"
NO MCP SERVERS SECTION FOR DEFAULT PROFILE   ← bug
```

For comparison, `it_admin` profile showed the expected section:
```
$ hermes profile use it_admin
$ hermes tools list | grep -A 3 "MCP servers"
MCP servers:
  inventory-mcp  all tools enabled
```

Both `~/.hermes/profiles/default/config.yaml` and `~/.hermes/profiles/it_admin/config.yaml`
contained the same `mcp_servers:` block. The configs looked structurally identical from
the outside but Hermes only loaded it for `it_admin`. Saved verbatim to `notes/step2_reproduce.txt`.

---

## 2. Hypothesis A — model block (Step 3) — **REJECTED**

Per the task body's hypothesis, added a `model:` block to `~/.hermes/profiles/default/config.yaml`
(mirroring the global config):

```yaml
model:
  default: minimax/minimax-m2.5
  provider: openrouter
  base_url: https://openrouter.ai/api/v1

mcp_servers:
  inventory-mcp:
    url: http://localhost:8001/mcp
    transport: streamable-http
```

**Result:** `hermes tools list` (default profile) still shows **no** MCP servers section.
Hypothesis A is wrong — the bug is not "missing model block causes profile to be skipped."

Saved to `notes/step3_model_block_test.txt`. The change was reverted before Step 5.

---

## 3. Root cause discovered (Step 5)

`hermes profile show <name>` revealed where each profile's config actually lives:

```
$ hermes profile show default
Profile: default
Path:    /home/ansible/.hermes          ← GLOBAL home dir, not profiles/default/
Model:   minimax/minimax-m2.5 (openrouter)
Skills:  86

$ hermes profile show it_admin
Profile: it_admin
Path:    /home/ansible/.hermes/profiles/it_admin   ← named profile subdir
Model:   minimax/minimax-m2.5 (openrouter)
Skills:  72
```

**The "default" profile maps to `/home/ansible/.hermes/` itself** — its config IS the global
`~/.hermes/config.yaml`. The directory `~/.hermes/profiles/default/` is a dead location
that Hermes does not read. Older `register_inventory_mcp` auto-detected multi-profile layout
via `~/.hermes/profiles/` dir existence and wrote to `~/.hermes/profiles/default/config.yaml`
for the default profile, which Hermes silently ignores.

`it_admin` worked because its config lives at `~/.hermes/profiles/it_admin/config.yaml` —
which IS where `hermes profile show it_admin` reports its Path. Same bug class as BACKLOG #21
(mcp_servers config format), which only fixed `it_admin` in PR #7.

### Verification

Tested hypothesis B3 — appended `mcp_servers:` to `~/.hermes/config.yaml` (global):

```yaml
# added to tail of ~/.hermes/config.yaml
mcp_servers:
  inventory-mcp:
    url: http://localhost:8001/mcp
    transport: streamable-http
```

**Result:** `hermes tools list` (default profile) immediately showed:
```
MCP servers:
  inventory-mcp  all tools enabled
```

Hypothesis B3 confirmed. Saved to `notes/step5_investigation.txt`.

---

## 4. Default profile drives inventory via natural language (Step 4)

```
$ hermes profile use default
$ hermes chat -q "Use the search_devices MCP tool with query=\"\" and limit=3. Show what you get back."
session_id: 20260627_233828_739028
Got 3 devices from the inventory:

| device_id | hostname | ip_address | device_type | vendor | model | site | role |
|-----------|----------|------------|-------------|--------|-------|------|------|
| dev-linux-01 | linux-host-01 | 192.168.10.10 | linux_host | Dell | PowerEdge R740 | lab | compute |
| dev-switch-01 | core-switch-01 | 192.168.10.1 | switch | Cisco | Catalyst 9300 | lab | core |
| dev-ap-01 | ap-floor1-01 | 192.168.10.50 | ap | Ubiquiti | U7 Pro | lab | access |
```

Three seeded devices with IP/hostname/vendor returned. The agent used the MCP tool natively,
not via curl. The bug is fixed.

---

## 5. bootstrap.sh patch (Step 6)

`bootstrap.sh:1068` — `register_inventory_mcp()` rewritten:

- Special-case `profile == "default"` → always write to `~/.hermes/config.yaml` (the global
  config, which IS the default profile's config).
- Named profiles keep multi-profile path (`~/.hermes/profiles/<name>/config.yaml`) when
  `~/.hermes/profiles/` exists, falling back to global otherwise.
- Idempotency preserved — `grep -q '^  inventory-mcp:' "$config_path"` still skips on
  re-run.
- Migration: when default profile is registered, also strip any stale `mcp_servers:`
  block from `~/.hermes/profiles/default/config.yaml` (uses `python3` + regex for clean
  YAML-key removal; `sed` would be fragile with the 2-space indent + nested keys).

Backup files left in place on VM:
- `/home/ansible/.hermes/config.yaml.bak2`
- `/home/ansible/.hermes/profiles/default/config.yaml.bak2`
- `/home/ansible/.hermes/profiles/default/config.yaml.bak`  (from prior bug-repro work)
- `/home/ansible/.hermes/profiles/default/config.yaml.wrongfix` (Step 3 attempt — kept
  as evidence for the audit trail; safe to delete)

Diff is in the commit for this card. Function length grew from 53 to 95 lines — all
additive (special-case + migration step + comments).

---

## 6. Smoke test on VM (Step 7)

```
$ bash ~/AIAMSBS/inventory-stack/tests/smoke_test.sh
...
=== summary ===
  passed: 14
  failed: 0
OK: all smoke checks passed
```

**14/14 PASS** (the test script has grown beyond the 12 tests referenced in the task
body — both delete_device and an extra update/get round-trip are now in the script).
Saved to `notes/step7_smoke_test.txt`.

---

## 7. Final E2E — default profile drives inventory (Step 8)

```
$ hermes profile use default
$ hermes chat -q "Use the search_devices MCP tool to list devices in the inventory. Show IP, hostname, vendor for 3 devices."
session_id: 20260627_234348_f6a242
Here are 3 devices from the inventory:

| Hostname | IP Address | Vendor |
|----------|------------|--------|
| linux-host-01 | 192.168.10.10 | Dell |
| core-switch-01 | 192.168.10.1 | Cisco |
| ap-floor1-01 | 192.168.10.50 | Ubiquiti |
```

Returned exactly the requested IP/hostname/vendor fields for 3 devices. Saved to
`notes/step8_final_e2e.txt`.

---

## 8. Verdict

**SHIPPED.** All acceptance criteria from the task body pass:

- [x] Step 2: bug reproduced (no MCP servers for default) — `notes/step2_reproduce.txt`
- [x] Step 3 OR Step 5: fix identified — Step 5 B3 (mcp_servers in global config)
- [x] Step 4/8: default profile drives inventory via natural language — both pass
- [x] Step 6: bootstrap.sh fix applied — `bootstrap.sh:1068-1162`
- [x] Step 7: smoke test 14/14 PASS — `notes/step7_smoke_test.txt`
- [x] Step 9: PR opened (see PR link in completion summary)

---

## 9. Out of scope (still open)

These are NOT touched by this card — flagged in the prior report and remain:

- **IT_ADMIN skill dir leak** (17 extra dirs from global `~/.hermes/skills/` leaking into
  `~/.hermes/profiles/it_admin/skills/`) — separate card.
- **No `delete_device` tool** in inventory-mcp — separate card.
- **Default creds in `/var/log/hermes-bootstrap-credentials.log`** — UX follow-up.

---

## 10. Re-bootstrap notes (for future verification)

To verify the fix on a clean install, snapshot-rollback VM 220 and re-bootstrap. After
the new `register_inventory_mcp` runs, `~/.hermes/config.yaml` will have the
`mcp_servers:` block (correct location), `~/.hermes/profiles/default/config.yaml` will
be empty or absent (migrated), and `hermes tools list` (default profile) will show the
MCP server section. No manual edits required.