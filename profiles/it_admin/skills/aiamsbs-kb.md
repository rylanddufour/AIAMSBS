# skills/aiamsbs-kb.md — AIAMSBS knowledge base authoring

## Purpose

How an agent should write to the AIAMSBS knowledge base via the `kb-mcp` MCP tools (`kb_add`, `kb_update`, `kb_search`, `kb_list`, `kb_get`, `kb_delete`). The skill exists so that every entry — written by any agent, any subagent, any future model — is **discoverable, scannable, and trustworthy** six months from now.

The number one failure mode of a knowledge base is entries that no one can find later. This skill prevents that.

## When to use

- Before calling `kb_add`, `kb_update`, `kb_search`, `kb_list`, `kb_get`, or `kb_delete` via the kb-mcp MCP tools.
- When reasoning about whether to write a KB entry from a troubleshooting session, runbook, alert, or incident.
- When reviewing the KB (any agent-fetched list of entries) and deciding what to refine.
- When drafting a runbook, fact, or gotcha that will be stored in the KB.

If you skip this skill and call `kb_add` without reading it, the tool will reject you with `title is required`. Don't fight it — read the section below, write a real title, submit.

## The hard rule: TITLE IS REQUIRED

Every entry must have a non-empty title. There is no exception.

The rule is enforced at three layers (tool validation, schema CHECK constraint, UI form validation). Even if you bypass one layer, the next will reject you. Don't try.

### What makes a good title

A good title is the **one thing a human searches for six months from now**. It answers: **what is this entry about, in one line?**

Good titles are specific, scannable, searchable:

- `Win11 link_down: WinRM service stopped after reboot` — OS + symptom + root cause in one line
- `Prometheus WMI exporter: port 9182 firewall rule` — component + port + the specific step
- `Snmp v2c community string mismatch gives no-such-name` — protocol + cause + the error phrase you'll grep for
- `Grafana CSV export: timezone is UTC, not local` — tool + behavior + the surprise
- `Loki retention not deleting: compactor never ran` — symptom + hidden cause

Bad titles are too generic and defeat the purpose:

- `Windows issue` — what about Windows?
- `Network problem` — what kind, where?
- `Server fix` — what server, what fix?
- `Notes` — notes on WHAT?
- (empty string) — rejected by schema
- The first sentence of content pasted back as a title — first sentence is usually framing, not the searchable nugget

**Rule of thumb:** If you can't imagine a customer typing the title (or part of it) into a search box and finding this entry, rewrite it.

### Titles are searchable

The FTS5 index covers `title + content + tags`. A title-only word (e.g., the word `WinRM` in the title above) is a strong search hit. Use this to your advantage: include the **specific error phrase**, **port number**, **device class**, or **protocol name** somewhere in the title.

## The five MCP tools

### `kb_search(query, limit=10, source_types=None)` — start here

Before you write anything, search for an existing entry. Do not duplicate. The default schema is `kb_fts` (BM25 ranking), so the highest-ranked result is the closest match.

```python
hits = kb_search("Snmp v2c community string")
# Returns entries with titles and content matching the query, ranked by relevance.
# Each row has a 'snippet' field with highlighted matches.
```

**FTS5 query syntax notes** (the MCP tool does some pre-processing for you):

- **Prefix matching is automatic for the last token.** Plain queries like `win` are silently rewritten to `win*` so they find `Win11`, `Windows`, `winrm`, etc. You do NOT need to type the `*` yourself. Earlier tokens are matched exactly, so `snmp community` finds entries containing the word `snmp` AND something starting with `community`.
- **Advanced syntax passes through unchanged.** If your query contains any FTS5 operator (`"`, `*`, `(`, `)`, `:`, `^`), the tool passes it through verbatim. Use `"phrase"` for exact phrases, `tok*` for explicit prefix, `tok1 OR tok2` for OR, and `title:Win11` to restrict to the title column.
- **Hyphens are NOT word separators** and the tool won't fix this for you (auto-prefixing would be ambiguous here). `kb_search("Win11-link_down")` returns `{"error": "no such column: link_down"}`. Use a space (`kb_search("Win11 link_down")`) or quote the phrase (`kb_search('"Win11-link_down"')`).
- Don't pass SQL special characters (`(`, `)`, `:`) unless you mean them. If a query errors, fall back to simpler words.

If you find a stale or incomplete entry, prefer `kb_update` over `kb_add`.

### `kb_add(title, content, entry_type, tags=None, source_id=None, created_by="agent")` — the primary write tool

```python
result = kb_add(
    title="Snmp v2c community string mismatch gives no-such-name",
    content="When polling a device with the wrong community string, the snmp_exporter returns "
            "no-such-name instead of a connection error. Check the community string in the "
            "device's snmp config and match it exactly in the prometheus.yml `snmp` block. "
            "Whitespace matters: 'public ' (with trailing space) won't match 'public'.",
    entry_type="gotcha",
    tags=["snmp", "prometheus", "gotcha"],
    created_by="agent",
)
# Returns: {"id": <new_id>, "status": "pending", ...}
```

Result notes:

- `created_by="agent"` (default) → entry is created with `status="pending"` and `trust_level=0`. A human reviews it; the customer can flip it to `approved` via `kb_update` or the UI.
- `created_by="customer"` → entry is auto-approved at `trust_level=3`.
- If the tool returns `{"error": "title is required and must be a non-empty string"}`, you forgot the title. Fix it.
- `kb_search` returns entries regardless of status (no status filter applied), so the entry you just wrote will be findable by anyone immediately. The `status` field is a review-queue marker, not a visibility gate.

### `kb_update(entry_id, title=None, content=None, tags=None, status=None)` — for edits

```python
kb_update(entry_id=42, title="Snmp v2c: trailing space in community string breaks poll")
```

To keep a field unchanged, **omit it** (or pass `None`). Passing `title=""` to "clear" it will be rejected — there's no way to remove a title; that's intentional.

### `kb_list(source_type=None, status=None, limit=50, offset=0)` — for review queues

Useful for the customer to see all pending entries awaiting approval. Filter by `status="pending"` to enumerate the review queue.

### `kb_delete(entry_id)` — for hard removal

Use sparingly. The customer can remove anything they've approved; agents should generally update or re-tag rather than delete (audit trail).

## Choosing `entry_type`

The schema enforces three values: `runbook`, `fact`, `gotcha`.

| Type | When to use | Example |
|---|---|---|
| `runbook` | Step-by-step procedure to accomplish a task. Loading order matters. Failure modes are documented. | "How to onboard a new SNMP device" — with exact clicks and CLI snippets |
| `fact` | A stable, verifiable piece of information. It doesn't change between runs. | "The default snmp_exporter port is 9116" |
| `gotcha` | A surprise, gotcha, or non-obvious failure mode. The thing that bit you and would bite someone else. | "Trailing whitespace in community string silently breaks polling" |

If you find yourself writing **"if X, then Y"** with a surprise ending, it's a `gotcha`. If you're writing **"to accomplish X, do steps 1, 2, 3"**, it's a `runbook`. If you're writing **"X is Y"** with no procedure and no surprise, it's a `fact`.

## When to write a KB entry

Write a KB entry when **an answer to a question has been found and that answer is non-obvious or will be needed again**.

Triggers:

- You diagnosed a non-obvious issue (snmp community string mismatch, firewall rule, version drift). The fix is now a `gotcha`.
- You produced a runbook from a complex task (onboarding a device, configuring a new integration). Save it as a `runbook`.
- You discovered a stable fact about the customer's environment (a hostname convention, a vendor quirk, a config location). Save it as a `fact`.
- The customer corrected or clarified something. Save it as a `fact` or `gotcha` depending on shape.

Do NOT write a KB entry for:

- One-off answers specific to this session only (the customer will ask again if they care).
- Speculation ("I think this might be the issue"). Verify first.
- Trivia that will be stale within a week (latest CVE numbers, current prices).

## Content shape

A good `content` field is:

- **Short paragraphs**, not walls of text. Break after every 2-3 sentences.
- **Specific** — names, ports, exact error messages, reproducible commands.
- **Self-contained** — the entry should make sense to a reader with no other context.
- **Action-oriented** for runbooks ("do this, then this, then verify"). Each step should be a sentence.

Avoid:

- Vague language ("sometimes", "might", "usually") — be specific or don't write it.
- First-person ("I found that...") — write the procedure, not the journey.
- Promotional language ("the awesome thing about...") — just say what it is.

For commands, use fenced code blocks:

````
```bash
curl -s http://prometheus:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="snmp")'
```
````

## Tags

Tags are free-form strings. Use them for:

- **Device class** (`windows`, `linux`, `mikrotik`, `cisco`)
- **Protocol** (`snmp`, `wmi`, `winrm`, `ssh`)
- **Component** (`prometheus`, `grafana`, `loki`, `alloy`)
- **Type** (`runbook`, `fact`, `gotcha`) — kind of redundant with `entry_type`, but useful for search.

Don't tag with the entry's id (`entry-42`) or with timestamps. Tags should be reusable across entries.

## The trust ladder

The schema enforces two tracks at the DB level:

- **`status`** ∈ `('pending', 'approved', 'rejected')`. Set automatically at insert time: agent entries → `pending`, customer entries → `approved`. The customer can flip `pending` → `approved`/`rejected` via `kb_update` or the UI. `kb_search` does not filter by status — every entry is findable; `status` is a review-queue marker, not a visibility gate.
- **`trust_level_at_creation`** INTEGER, set at insert time. Currently 0 for agents, 3 for customers. The schema does not enforce a range, so the ladder is free to grow (e.g., a future `approved_agent` level at 1 or 2) without a migration.

What this means in practice:

- **Agent writes** (`kb_add(..., created_by="agent")`) → status=pending, trust=0. The customer sees it in the review queue and approves, rejects, or edits it.
- **Customer writes** (`kb_add(..., created_by="customer")`) → status=approved, trust=3. No review needed; it's their own knowledge.
- **Customers promoting agent entries** → `kb_update(entry_id=, status="approved")`. The trust_level_at_creation stays at 0 (a historical fact); future searches can use status to bias results.

Don't try to "promote" trust on the agent side by passing `created_by="customer"` — that's lying about provenance. Either ask the customer to write it directly, or write it as agent and let the customer approve.

## Worked example: from incident to KB entry

A Win11 VM becomes unreachable. You investigate and find the network interface went `link_down` but the VM is still running.

```python
# 1. Search first — don't duplicate
existing = kb_search("Win11 link_down")
# existing might be empty on a fresh install, or might show a stale entry.

# 2. Write the new entry with a specific, searchable title
kb_add(
    title="Win11 link_down: WinRM service stopped after reboot",
    content=(
        "Win11 VM becomes unreachable in Grafana. The host is running "
        "but the network interface shows link_down in the link_status metric.\n\n"
        "Root cause: WinRM service stopped after the last reboot. The "
        "windows_exporter relies on WinRM for WMI queries; without it, "
        "the exporter exits and the host's link flaps.\n\n"
        "Fix: RDP or console into the VM, open services.msc, set "
        "'Windows Remote Management (WS-Management)' to Automatic "
        "(Delayed Start) and start the service. Verify with "
        "'winrm quickconfig' from an admin cmd.\n\n"
        "Preventative: this happens on every Windows Update reboot. "
        "Either disable the Windows Update reboots or set the WinRM "
        "service to auto-restart on failure."
    ),
    entry_type="gotcha",
    tags=["windows", "winrm", "link_down", "prometheus"],
)
```

Six months later, a customer sees the same symptom, types `Win11 link_down` into the KB search, and finds this entry. Time saved: hours.

## Related skills / files

- `skills/aiamsbs-backup.md` — how the KB database gets backed up.
- `skills/monitoring-observability.md` — where Prometheus, Loki, and the KB live in the AIAMSBS stack.
- BACKLOG #57 (the kb-mcp `/ui/` regression that originally surfaced the title gap).
- The kb-mcp web UI at `http://<aiamsbs-host>:8002/ui/` for human authoring and review.
