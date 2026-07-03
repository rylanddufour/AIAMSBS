---
name: kb-mcp
title: AIAMSBS Knowledge Base MCP
description: Search, add, update, list, and delete entries in the AIAMSBS knowledge base (SQLite + FTS5, served by kb-mcp on :8002). Runbooks, facts, and gotchas captured from agent and customer sources.
trigger: When the user asks something that might be answered by a previously-captured runbook, fact, or gotcha. Also when the agent learns something worth remembering (a fix, a quirk, a customer-specific detail) and should record it for later.
---

# AIAMSBS Knowledge Base MCP

SQLite + FTS5 knowledge base exposed via FastMCP. Registers as `kb-mcp` in `default` and `it_admin` profiles. Server runs on `http://localhost:8002/mcp` after `bootstrap.sh` deploys the kb stack.

**When to use this skill:** any question that might be answered by past experience (runbooks, gotchas, customer-specific facts). Also any time the agent learns something it should remember — capture it as a `runbook`/`fact`/`gotcha` entry before the context rolls.

**Don't use this for:** live system state (use inventory-mcp or platform observability). KB is captured knowledge, not real-time telemetry.

## Tools

| Tool | Signature | Use for |
|---|---|---|
| `kb_search` | `(query, limit=10, source_types=None) -> list` | FTS5 BM25-ranked search. Use free-text; quote phrases for exact match. |
| `kb_add` | `(content, entry_type, tags=None, source_id=None, created_by='agent') -> dict` | Add a new entry. Agent entries start `status=pending`; customer entries start `approved`. |
| `kb_update` | `(entry_id, content=None, tags=None, status=None) -> dict` | Patch fields on an existing entry. |
| `kb_list` | `(source_type=None, status=None, limit=50, offset=0) -> list` | List entries with optional filters. Newest first. |
| `kb_delete` | `(entry_id) -> dict` | **DESTRUCTIVE** — hard delete. Always confirm with the user first. |
| `kb_add_source` | `(name, source_type, file_path_or_url=None) -> dict` | Register a new source (where knowledge chunks came from). |
| `kb_list_sources` | `() -> list` | List all known sources, newest first. |

## Valid enum values

- **`entry_type`:** `runbook` (how to do X), `fact` (something true about this environment), `gotcha` (a pitfall / "watch out")
- **`status`:** `pending` (agent wrote, awaiting review), `approved` (customer or operator accepted), `rejected` (will be ignored)
- **`created_by`:** `agent` (default) or `customer` (auto-approved, trust level 3)
- **`source_type`:** `skill` (came from a skill file), `customer_doc` (customer uploaded), `runtime` (captured at runtime)

## Trust model

The KB has a trust ladder:
- **0 = agent-written pending** (default for new agent entries; not surfaced until approved)
- **3 = customer-written** (auto-approved at creation; the customer wrote it, they own it)

When searching, customer-written entries are preferred over pending agent entries. The customer can promote pending → approved or pending → rejected.

## Examples

**Search for a known issue:**
```
> user: "the OPNsense box keeps dropping the VPN"
> agent: kb_search("OPNsense VPN drops") → [{entry_id: 42, snippet: "...", status: "approved", trust_level_at_creation: 3, ...}, ...]
```

**Capture something learned:**
```
> agent: kb_add(
    content="Always `qm rollback <vmid> gstack-testing` before E2E — fresh state avoids left-over containers from prior runs.",
    entry_type="gotcha",
    tags=["e2e", "proxmox"],
    created_by="agent"   # starts as pending; customer approves later
)
```

**Customer corrects an agent entry:**
```
> user: "actually it's `qm snapshot` first, not `qm rollback` — fix entry 7"
> agent: kb_update(7, content="Use `qm snapshot` first, then `qm rollback <vmid> gstack-testing` to restore.")
```

**List everything pending review:**
```
> kb_list(status="pending") → [ {entry_id: 12, ...}, ... ]
```

## Pitfalls

- **FTS5 tokenizes, so multi-word queries match entries with ANY term** (OR semantics by default). For phrase matching, quote: `kb_search('"VPN drops"')`.
- **Agent entries start `pending`.** They'll be invisible to default searches in some flows. The customer/operator must approve them. Don't add entries the user hasn't asked to capture — pending entries pile up.
- **`kb_delete` is hard delete.** No soft-delete. Same pattern as inventory: `search → show → confirm → delete`. The FTS index is updated via the `kb_ad` trigger, so search results are immediately consistent.
- **Tags are stored as a JSON array string in SQLite but surfaced as a list.** If you see tags as a string in a return value, the JSON was malformed on insert.
- **`source_id` is a foreign key to `kb_sources.id`.** Use `kb_add_source` first if you want to attribute the entry to a named source (e.g., a customer doc). Pass `None` to skip attribution.
- **`kb_search` with `source_types` excludes sourceless entries** (uses INNER JOIN). Without `source_types`, sourceless entries are included (LEFT JOIN). Same for `kb_list`.
- **The MCP is local-only (`localhost:8002`).** Don't try to hit it from a remote profile.
