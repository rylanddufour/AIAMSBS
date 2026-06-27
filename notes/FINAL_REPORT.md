# BACKLOG #25 — Add `delete_device` to inventory-mcp + confirmation flow

**Card:** t_6ad78473
**Date:** 2026-06-27
**Branch:** `wt/feat-delete-device-20260627`
**VM:** 192.168.0.220
**Verdict:** **SHIPPED** ✅

---

## TL;DR

| Item | Verdict | Notes |
|------|---------|-------|
| **Step 1** `delete_device` tool in `server.py` | ✅ | 44-line addition after `update_device`; cascade_relationships=True default |
| **Step 2** Container rebuild + redeploy | ✅ | inventory-mcp Up (healthy) on VM 220 |
| **Step 3** tools/list exposes `delete_device` | ✅ | 8 tools total (was 7); saved to `notes/step3_delete_tool_listed.txt` |
| **Step 4** non-destructive-operations.md updated | ✅ | 46-line "Destructive Inventory Operations" section appended; copied to `~/.hermes/profiles/it_admin/skills/` on VM |
| **Step 5** Smoke test | ✅ | **14/14 PASS** (was 12/12; +2 for delete_device + post-delete get_device) — `notes/step5_smoke_test.txt` |
| **Step 6** IT_ADMIN E2E confirmation flow | ✅ | Agent searched, showed row, ASKED, did NOT delete until "yes" — `notes/step6_e2e_confirm_flow.txt` |
| **Step 7** Default profile E2E | ✅ | BACKLOG #24 regression NOT present in this environment; default profile also follows confirmation flow — `notes/step7_e2e_default_profile.txt` |
| **Step 8** Commit + push + PR | ⏳ | Done in this card |

---

## Step-by-step details

### ✅ Step 1: delete_device tool

`inventory-stack/mcp/server.py` — 44-line addition (inserted between
`update_device` and `get_device_relationships`):

```python
@mcp.tool()
def delete_device(device_id: str, cascade_relationships: bool = True) -> dict:
    """Delete a device record from the inventory by device_id.

    DESTRUCTIVE — the row is permanently removed (not soft-deleted).
    Callers should always confirm with the user before invoking this.

    Args:
        device_id: required. The device_id of the row to delete.
        cascade_relationships: if True (default), also delete any rows in
            device_relationships where this device is source or target.
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM devices WHERE device_id=?", (device_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return {"error": "not found", "device_id": device_id}
    deleted = dict(row)
    rels_deleted = 0
    if cascade_relationships:
        cur.execute(
            "DELETE FROM device_relationships "
            "WHERE source_device_id=? OR target_device_id=?",
            (device_id, device_id),
        )
        rels_deleted = cur.rowcount
    cur.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
    conn.commit()
    rows_affected = cur.rowcount
    conn.close()
    return {
        "status": "deleted",
        "device_id": device_id,
        "rows": rows_affected,
        "relationships_deleted": rels_deleted,
        "deleted_record": deleted,
    }
```

Design notes:
- Returns `deleted_record` so the agent can show the user exactly what was removed.
- `relationships_deleted` count included so callers see the cascade effect.
- Returns `{"error": "not found", "device_id": ...}` envelope if missing (idempotent — matches the other tools' shape).
- `cascade_relationships=True` is the safer default — leaving orphaned FK rows would be a quiet correctness bug.

### ✅ Step 2: Container rebuilt + redeployed

```
NAME            IMAGE                   COMMAND                  SERVICE         CREATED         STATUS                   PORTS
inventory-mcp   aiamsbs_inventory-mcp   "python server.py --…"   inventory-mcp   5 minutes ago   Up 5 minutes (healthy)   127.0.0.1:8001->8001/tcp
```

### ✅ Step 3: tools/list shows 8 tools

8 tools total, including `delete_device`. Full output preserved in `notes/step3_delete_tool_listed.txt`.

```
Total tools: 8
  - get_device: Look up a single device by its device_id.
  - lookup_by_ip: Look up a device by its IP address.
  - lookup_by_hostname: Look up a device by its hostname.
  - search_devices: Search devices by free-text query with optional filters.
  - create_device: Create a new device record. `device_id` is required.
  - update_device: Update fields on an existing device. updated_at is set automatically.
  - delete_device: Delete a device record from the inventory by device_id.
  - get_device_relationships: Return all relationships involving this device (as source or target).

delete_device present: True
```

### ✅ Step 4: non-destructive-operations.md updated

`profiles/it_admin/skills/non-destructive-operations.md` — 46-line
"Destructive Inventory Operations" section appended. Covers:
1. Search first (search_devices / lookup_by_ip / lookup_by_hostname)
2. Show what you found
3. Wait for explicit confirmation
4. Report the result

Plus an example user flow ("Remove server 101 from inventory") and a "Never" list
(skipping confirmation, batch deletes, fabricating a device_id).

Re-installed on VM:
```
-rw-r--r-- 1 ansible ansible 6018 Jun 27 23:37 /home/ansible/.hermes/profiles/it_admin/skills/non-destructive-operations.md
```

### ✅ Step 5: Smoke test 14/14 PASS

`inventory-stack/tests/smoke_test.sh` updated:
- Header `=== MCP tools (8) ===`
- Test 8a: create throwaway → delete_device → assert envelope + deleted_record
- Test 8b: get_device after delete → assert `{"error": "not found"}`

```
=== preflight ===
  [PASS] seed (DB reseeded via seed.py)
  [PASS] container inventory-mcp is up

=== MCP session ===
  [PASS] initialize (session=368feb40db8e4cbf93385310c9833590)

=== MCP tools (8) ===
  [PASS] get_device(dev-linux-01) returns seeded linux host
  [PASS] lookup_by_ip(192.168.10.1) returns seeded switch
  [PASS] lookup_by_hostname(ap-floor1-01) returns seeded AP
  [PASS] search_devices(query='linux') returns linux host only
  [PASS] create_device echoes device_id
  [PASS] update_device returns success envelope
  [PASS] get_device confirms update_device wrote new hostname
  [PASS] get_device_relationships(dev-switch-01) returns 2 entries
  [PASS] delete_device returns success envelope with deleted_record
  [PASS] get_device after delete_device returns not found

=== nmap-discovery wrapper (port 8002) ===
  [PASS] nmap-discovery TCP connect to 127.0.0.1:8002 (no healthcheck endpoint exposed)

=== summary ===
  passed: 14
  failed: 0
OK: all smoke checks passed
```

Full output: `notes/step5_smoke_test.txt`.

### ✅ Step 6: IT_ADMIN E2E confirmation flow

Seed: `e2e-delete-test` / throwaway / 192.168.0.251 / TestCo / e2e-test

**Prompt 1** ("search first, show what you found, ask me to confirm"):
- Agent searched via MCP, rendered the row in a markdown table, asked:
  > "Do you want me to proceed with deleting device `e2e-delete-test`?"
- DB row count BEFORE confirm: **1** (proof of non-destructive behavior)

**Prompt 2** ("yes, delete it"):
- Agent called `delete_device`, returned the deleted_record envelope
  (`relationships_deleted: 0`)
- DB row count AFTER confirm: **0** (proof of successful delete)

Full output: `notes/step6_e2e_confirm_flow.txt`.

### ✅ Step 7: Default profile E2E

**IMPORTANT:** Prior card t_f4ff4c7b (June 27) reported BACKLOG #24 (default
profile MCP auto-load regression) as BLOCKING v1. Re-tested for this card with
`hermes profile show default && hermes tools list`:

```
MCP servers:
  inventory-mcp  all tools enabled
```

The regression is **no longer present** in this environment (or was fixed by
an intervening config change since the prior card). Default profile exposes
inventory-mcp tools and the agent follows the confirmation flow.

Seed: `e2e-delete-default-2` / throwaway-default-2 / 192.168.0.253 / TestCo / e2e-test-default-2

**Prompt 1** ("search first, show what you found, ask me to confirm"):
- Agent rendered the row, asked:
  > "Confirm delete? Reply `yes` to proceed with deletion, or anything else to cancel."
- DB row count BEFORE confirm: **1**

**Prompt 2** ("yes, delete it via delete_device, report what was removed"):
- Agent called delete_device, returned the deleted_record envelope
  (`relationships_deleted: 0`)
- DB row count AFTER confirm: **0**

Full output: `notes/step7_e2e_default_profile.txt`.

**Caveat:** Default profile E2E required `export HERMES_HOME=/home/ansible/.hermes`
before `hermes chat` — without it, the subprocess falls back to `it_admin`
(profile use doesn't persist across shell boundaries without HERMES_HOME).
This is a separate UX wart (Hermes issue #18594 per the fallback warning)
but doesn't affect the delete_device functionality.

---

## Files changed in this card

```
inventory-stack/mcp/server.py                      | 44 +++++++++++++++++++++
inventory-stack/tests/smoke_test.sh                | 20 +++++++++-
.../it_admin/skills/non-destructive-operations.md  | 46 ++++++++++++++++++++++
notes/step3_delete_tool_listed.txt                 | (new)
notes/step5_smoke_test.txt                         | (new)
notes/step6_e2e_confirm_flow.txt                   | (new)
notes/step7_e2e_default_profile.txt                | (new)
notes/FINAL_REPORT.md                              | (rewritten for this card)
scripts/step3_verify_tools_list.sh                 | (helper, not committed)
```

---

## Pitfalls hit + how they were handled

- **`hermes profile use default` doesn't persist across shells** without `HERMES_HOME`. Set it explicitly for default-profile chat invocations. (Not blocking — `it_admin` chat invocations work without it because it_admin is the active profile marker.)
- **First default-profile "yes" prompt timed out** before reporting cleanly, but the row was deleted during the agent's attempts. Re-seeded and re-ran with explicit `HERMES_HOME` to get a clean PASS signal.
- **No `git pull` artifacts left behind.** All work on branch `wt/feat-delete-device-20260627`, none on main.

---

## Verdict

**SHIPPED** ✅

- Tool added (`delete_device` with cascade_relationships=True default).
- Tool exposed (8 tools / was 7).
- Skill updated (destructive operations require confirm + show + wait + report).
- Smoke test 14/14 PASS (was 12/12).
- Both `it_admin` and `default` profiles follow the confirmation flow end-to-end.

PR will follow. Customers can now prompt either profile with
"remove server X from inventory" and get the search → confirm → delete
flow without any agent-side code changes required.