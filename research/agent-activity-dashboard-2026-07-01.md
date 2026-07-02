# Research: AI Agent activity dashboard (AIAMSBS BACKLOG #29)

**Date:** 2026-07-01
**Author:** Hermes Agent (subagent of orchestrator)
**Brief:** `/tmp/research_29_prompt.md` (5 questions)
**Output:** this file — self-contained research + concrete implementation recommendation
**Backlog source:** `AIAMSBS/BACKLOG.md` row 29 (the "old t_002a166f" card body is folded into the BACKLOG row text).

---

## TL;DR

- **Data sources are all present and queryable.** The big surprise: there is **no Prometheus exporter in Hermes Agent** but the structured `agent.log` already prints per-API-call metrics (`API call #N: model=… provider=… in=… out=… total=… latency=…s cache=…/… (…)%`) and per-tool-call latencies (`agent.tool_executor: tool <name> completed (X.XXs, N chars)`). These are the gold seam.
- **The "session DB" is `~/.hermes/profiles/<name>/state.db`** (a 114 MB SQLite on the active host with 253 sessions / 20,416 messages). It has every field the dashboard needs: `model`, `source`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, **`estimated_cost_usd`**, `message_count`, `tool_call_count`, `started_at`, `ended_at`, `end_reason`. Per-message rows carry `role`, `tool_name`, `token_count`, `finish_reason`, `tool_calls` (JSON), `timestamp`. FTS5 indices are present.
- **`agent.log` is the most data-rich per-event source.** It has structured per-API-call token + latency + cache data, and per-tool-call latencies and errors. We can parse these with `loki.process stage.regex` + `stage.metrics` and emit Prometheus metrics directly from Alloy, no Python exporter required for ~80% of the value.
- **Recommended architecture: Hybrid (Pattern 5).** Alloy `loki.source.file` tails `~/.hermes/logs/*.log` into Loki, `loki.process` parses with `stage.regex` + `stage.metrics` to emit Prometheus counters/histograms, and Grafana queries both. A small Python "agent-exporter" service fills the gaps that need DB access (kanban, state.db cost totals, session duration p99). The existing health dashboard at `config/grafana/provisioning/dashboards/health-check.json` already defines the visual style — the new dashboard should be a sibling with the same `stat`+`colorMode:"background"` tile rows.
- **Top 3 metrics to surface:** (1) **`hermes_api_calls_total{model,profile,platform}`** — counter, indicates which models are being driven; (2) **`hermes_tokens_total{model,profile,kind}`** — counter split by `kind=input|output|cache_read|cache_write|reasoning`, drives cost visibility; (3) **`hermes_tool_latency_seconds_bucket{tool,profile,outcome}`** — histogram, drives per-tool p50/p95/p99.
- **Blocking open question for Ryland:** the prompt's profile names (`aiamsbs_dev`, `aiamsbs_research`, `default`) do not match what's actually on VM 103 (the only profile is `it_admin`). This is item 1 of Q5's open questions; the rest of the research is profile-agnostic but the implementation should clarify before scoping.

---

## Q1. Data sources — what can we extract from a running Hermes host?

I checked the **active local host** (`/home/openclaw/.hermes`, 175.7 MB sessions DB, 2 aiamsbs profiles) and cross-referenced with **VM 103** (`gstack-iac`, 192.168.0.220, SSH verified, fresh bootstrap with a single `it_admin` profile and an empty `~/.hermes/sessions/`). The structure is identical; the local host is just more populated.

### 1.1 `~/.hermes/profiles/<name>/state.db` — the per-profile session SQLite (the "session DB")

**Path on active host:** `/home/openclaw/.hermes/profiles/aiamsbs_dev/state.db` (114 MB)
**Path on VM 103:** `/home/ansible/.hermes/profiles/it_admin/state.db` (745 KB — fresh)

This is the canonical session store. Two key tables (`schema_version`, `state_meta` are bookkeeping):

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,                      -- "cli" | "telegram" | "discord" | ...
    user_id TEXT,
    model TEXT,                                -- "minimax/minimax-m3", "anthropic/claude-opus-4.6", ...
    model_config TEXT,                         -- JSON
    system_prompt TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,                  -- unix epoch
    ended_at REAL,
    end_reason TEXT,                           -- "completed" | "max_iterations" | "error" | ...
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    billing_provider TEXT,                     -- "openrouter" | "anthropic" | ...
    billing_base_url TEXT,
    billing_mode TEXT,                         -- "pay_as_you_go" | ...
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    cost_status TEXT,                          -- "ok" | "missing_pricing" | ...
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,
    api_call_count INTEGER DEFAULT 0,
    handoff_state TEXT,
    handoff_platform TEXT,
    handoff_error TEXT,
    cwd TEXT,
    rewind_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,                        -- "user" | "assistant" | "tool" | "session_meta"
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,                           -- JSON
    tool_name TEXT,                            -- e.g. "terminal", "patch", "read_file", "browser_navigate"
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,                        -- "stop" | "tool_calls" | "length" | ...
    reasoning TEXT,
    reasoning_content TEXT,
    reasoning_details TEXT,
    codex_reasoning_items TEXT,
    codex_message_items TEXT,
    platform_message_id TEXT,
    observed INTEGER DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);
```

There are FTS5 virtual tables `messages_fts` and `messages_fts_trigram` for search; triggers keep them in sync with `content || tool_name || tool_calls`.

**Sample data (recent sessions, trimmed):**
```
20260701_220455_166c47|minimax/minimax-m3|cli  |1 |0 |38978 |5488 |937118 |0 |0.07450608
20260701_191912_4350b6|minimax/minimax-m3|cli  |1 |0 |0     |0    |0      |0 |  (no end)
20260701_090957_62954a|minimax/minimax-m3|cli  |98|48|55059 |11699|2131012|0 |0.15841722
```

The third row is a 98-message, 48-tool-call session that reused a 2.1 M-token prompt cache (99%+ cache hit). The second has zero tokens because the session was still warming up. So `ended_at IS NULL` is a "currently active" signal worth surfacing.

**Tool-call histogram from the same DB (count of `messages.role='tool'` by `tool_name`):**
```
terminal:        4693
read_file:        312
patch:            254
write_file:       246
search_files:     133
process:           28
browser_navigate: 140
browser_snapshot:  48
delegate_task:     18
memory:            25
todo:              80
kanban_*: ~140 (show/complete/comment/block/create/heartbeat)
```

**Verdict:** Directly usable. The Python `sqlite3` stdlib can read this; no transform needed. Both aggregate (sessions-level) and per-message (per-tool-call) data is available. `state.db` is opened in WAL mode (`-shm` and `-wal` sidecars) so concurrent reads are safe; just use `PRAGMA query_only=1` to be polite.

### 1.2 `~/.hermes/kanban.db` and `~/.hermes/profiles/<name>/kanban.db` — kanban task DBs

**Path on active host:**
- Global: `/home/openclaw/.hermes/kanban.db` (114 KB, used by the orchestrator)
- Per-profile: `/home/openclaw/.hermes/profiles/aiamsbs_dev/kanban.db` (114 KB, used by the worker)

**Path on VM 103:** the global `kanban.db` does not exist yet; per-profile under `it_admin/` doesn't either. (The bootstrap creates one lazily.)

Tables (verbatim from `.schema`):
```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT,
    assignee TEXT,                    -- profile name
    status TEXT NOT NULL,              -- "triage"|"todo"|"scheduled"|"ready"|"running"|"blocked"|"done"|"archived"
    priority INTEGER DEFAULT 0,
    created_by TEXT,
    created_at INTEGER NOT NULL,       -- unix epoch seconds
    started_at INTEGER,
    completed_at INTEGER,
    workspace_kind TEXT NOT NULL DEFAULT 'scratch',
    workspace_path TEXT,
    claim_lock TEXT,
    claim_expires INTEGER,
    tenant TEXT,
    result TEXT,
    idempotency_key TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,   -- circuit breaker counter
    worker_pid INTEGER,
    last_failure_error TEXT,
    max_runtime_seconds INTEGER,
    last_heartbeat_at INTEGER,
    current_run_id INTEGER,
    workflow_template_id TEXT,
    current_step_key TEXT,
    skills TEXT,                        -- JSON array
    max_retries INTEGER,
    branch_name TEXT,
    model_override TEXT,
    session_id TEXT,                    -- links to state.db
    goal_mode INTEGER NOT NULL DEFAULT 0,
    goal_max_turns INTEGER
);
CREATE TABLE task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    profile TEXT,                       -- which profile ran this
    step_key TEXT,
    status TEXT NOT NULL,               -- "running" | "done" | "blocked" | "crashed" | "timed_out" | "failed" | "released"
    claim_lock TEXT,
    claim_expires INTEGER,
    worker_pid INTEGER,
    max_runtime_seconds INTEGER,
    last_heartbeat_at INTEGER,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    outcome TEXT,                       -- "completed" | "blocked" | "crashed" | "timed_out" | "spawn_failed" | "gave_up" | "reclaimed"
    summary TEXT,
    metadata TEXT,                      -- JSON
    error TEXT
);
CREATE TABLE task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    run_id INTEGER,
    kind TEXT NOT NULL,                 -- "claim"|"heartbeat"|"progress"|"complete"|"block"|"crash"|...
    payload TEXT,                       -- JSON
    created_at INTEGER NOT NULL
);
```

Plus: `task_comments`, `task_links`, `task_attachments`, `kanban_notify_subs`.

**Sample `task_runs` row (active host):**
```
4|t_ba1e1ac4|aiamsbs_dev||done|||||1781381945|1781381941|1781382004|completed||
3|t_ad803eb6|aiamsbs_dev||done|||||1781380623|1781380499|1781380644|completed|Successfully completed task: updated AIAMSBS repository...
2|t_2bd15de7|aiamsbs_dev||crashed||||||1781380018|1781380078|crashed||{"pid": 1716519, "claimer": "openclaw:1091268"}|pid 1716519 not alive
```

Run #4: 63-second completed run. Run #2: 60-second crash, heartbeats stopped, claim reaper killed it. Exactly the data we need for "tasks per hour" and "failure rate" panels.

**Verdict:** Directly usable for kanban metrics. `started_at`/`ended_at` give duration; `outcome` gives success/fail; `profile` label is already there; `session_id` joins to `state.db.sessions.id`.

### 1.3 `~/.hermes/logs/*.log` — gateway.log, agent.log, errors.log (the structured log seam)

This is the highest-leverage source. **All three logs are Python `logging` output** (`YYYY-MM-DD HH:MM:SS,uuu LEVEL module: message`) and Hermes already formats the high-value lines as semi-structured.

**`agent.log` — per-API-call metrics (the gold):**
```
2026-06-27 22:56:36,058 INFO [cron_9a12070fe5aa_20260627_225633] agent.conversation_loop: API call #1: model=minimax/minimax-m3 provider=openrouter in=15088 out=117 total=15205 latency=2.4s cache=128/15088 (1%)
2026-06-27 22:56:40,056 INFO [cron_9a12070fe5aa_20260627_225633] agent.conversation_loop: API call #2: model=minimax/minimax-m3 provider=openrouter in=15237 out=262 total=15499 latency=3.9s cache=15104/15237 (99%)
2026-06-27 22:56:54,455 INFO [cron_9a12070fe5aa_20260627_225633] agent.conversation_loop: API call #4: model=minimax/minimax-m3 provider=openrouter in=22748 out=431 total=23179 latency=6.9s cache=22656/22748 (100%)
```

**`agent.log` — per-tool-call metrics:**
```
2026-06-27 22:56:36,157 INFO [cron_9a12070fe5aa_20260627_225633] agent.tool_executor: tool terminal completed (0.09s, 49 chars)
2026-06-27 22:56:43,333 WARNING [cron_9a12070fe5aa_20260627_225633] agent.tool_executor: Tool terminal returned error (0.10s): {"output": "cat: ...: No such file or directory", "exit_code": 1, "error": null}
2026-06-27 22:56:47,507 INFO [cron_9a12070fe5aa_20260627_225633] agent.tool_executor: tool terminal completed (0.10s, 45 chars)
```

**`gateway.log` — per-conversation summary:**
```
2026-07-01 09:02:12,456 INFO gateway.run: response ready: platform=telegram chat=8704545814 time=173.9s api_calls=25 response=2779 chars
2026-07-01 19:44:54,879 INFO gateway.run: response ready: platform=telegram chat=8704545814 time=531.0s api_calls=28 response=1837 chars
2026-07-01 22:06:03,895 INFO gateway.run: response ready: platform=telegram chat=8704545814 time=221.1s api_calls=7 response=1506 chars
```

**`gateway.log` — inbound (with prompt):**
```
2026-05-24 12:08:04,877 INFO gateway.run: inbound message: platform=telegram user=Ryland chat=8704545814 msg='in what tools in the IaC framework is sqlite used?'
```

**Log line envelope:** `TIMESTAMP,uuu LEVEL [bracket-tag] module: message`. The `[bracket-tag]` is a session-or-cron ID (e.g. `[cron_9a12070fe5aa_20260627_225633]`, `[20260701_220548_cce6c3]`). This is the **natural profile/session label** for Loki/Alloy.

**Verdict:** Directly usable. The per-API-call line and per-tool-call line are both parseable with a single regex. The bracket-tag is the natural session_id label. The provider/model/token/latency/cache fields are stable. **No transform needed beyond regex parsing and field extraction.** This is the source the Prometheus exporter pattern in the original BACKLOG #29 spec doesn't need.

`gateway-exit-diag.log`, `gateway-shutdown-diag.log`, `gui.log`, `tui_gateway_crash.log`, `dashboard.log`, `hermes-update.log`, `update.log` also exist but are lower-value; recommend starting with the three main ones.

### 1.4 `~/.hermes/cron/jobs.json` and `~/.hermes/cron/output/<job_id>/` — cron jobs

**Path:** `/home/openclaw/.hermes/cron/jobs.json` (top-level, single file for all profiles). It is a JSON document, not a DB.

Schema (excerpt — array of job records):
```json
{
  "id": "4a851375bf6c",
  "name": "Daily Backlog Reminder",
  "prompt": "You are a personal assistant...",
  "skills": [],
  "skill": null,
  "model": null,
  "provider": null,
  "base_url": null,
  "script": null,
  "no_agent": false,
  "schedule": { "kind": "cron", "expr": "0 9 * * *", "display": "0 9 * * *" },
  "schedule_display": "0 9 * * *",
  "repeat": { "times": null, "completed": 17 },
  "enabled": true,
  "state": "scheduled",
  "paused_at": null,
  "paused_reason": null,
  "created_at": "2026-06-14T22:46:05.418077-04:00",
  "next_run_at": "2026-07-02T09:00:00-04:00",
  "last_run_at": "2026-07-01T09:01:56.378858-04:00",
  "last_status": "ok",            // "ok" | "error" | "running" | "skipped"
  "last_error": null,
  "last_delivery_error": null,
  "deliver": "telegram:8704545814",
  "origin": { "platform": "telegram", "chat_id": "8704545814", "chat_name": "Ryland" }
}
```

`/home/openclaw/.hermes/cron/output/<job_id>/` contains the per-run stdout/stderr captures (currently no per-run log file by default — they're stored as the agent conversation continues, and show up in the gateway.log / agent.log as the `[cron_<id>_<ts>]` bracket-tagged lines).

**Verdict:** `jobs.json` is parseable and gives us `last_status`, `last_run_at`, `next_run_at` for each job. The actual run content is in `agent.log` under the `[cron_<id>_<ts>]` tag. No per-run log file to tail, but the existing `agent.log` already covers it.

### 1.5 `~/.hermes/sessions/*.jsonl` and `session_*.json` — per-session JSONL exports (legacy/secondary)

**Path on active host:** `/home/openclaw/.hermes/sessions/` and `/home/openclaw/.hermes/profiles/aiamsbs_dev/sessions/` (symlink-equivalent or copy — same files). Files:
```
20260512_231637_1401121f.jsonl
20260513_001653_bc7eaf2f.jsonl
session_20260514_215215_f01a35.json
session_20260514_215215_f01a35.json   <- yes, two file types coexist
request_dump_<session>_<ts>.json       <- request dump exports
sessions.json                          <- index
```

**First line of a session JSONL:**
```json
{"role": "session_meta", "tools": [], "model": "anthropic/claude-opus-4.6", "platform": "telegram", "timestamp": "2026-05-12T23:16:43.496038"}
```

**First lines of a session JSON** (pretty-printed):
```json
{
  "session_id": "20260514_215215_f01a35",
  "model": "minimax/minimax-m2.5",
  ...
}
```

**Verdict:** These are *exports* — a snapshot of the conversation history that is **redundant with `state.db.messages`**. For a dashboard they are NOT the right source: they don't have token counts, they may be stale, and you have to walk files. Skip them; use `state.db` instead.

### 1.6 Profile directories — what per-profile artifacts exist

`~/.hermes/profiles/<name>/` contains (verified on `aiamsbs_dev`):
```
audio_cache/            bin/               cache/
channel_directory.json  config.yaml        cron/
.env                    hermes-agent/      .hermes_history
.hermes.yaml            hooks/             image_cache/
kanban.db               logs/              memories/
models_dev_cache.json   pairing/           pending/
plugins/                processes.json     .restart_last_processed.json
repos/                  sandboxes/         sessions/
skills/                 .skills_prompt_snapshot.json
SOUL.md                 state.db           state-snapshots/
.update_check
```

The dashboard-relevant ones (beyond what's covered above):
- **`config.yaml`** (15 KB) — model, model.default, mcp_servers, terminal, etc. *We can surface a "configured default model" gauge per profile from this.*
- **`SOUL.md`** (3 KB) — agent persona/instructions. *Not telemetry, but a useful "agent identity" panel.*
- **`models_dev_cache.json`** (~2.9 MB) — full model catalog with pricing. *Cross-reference for the `estimated_cost_usd` calculation.*
- **`memories/MEMORY.md`** + **`USER.md`** — agent-curated notes. *Not telemetry.*
- **`processes.json`** — runtime state of the gateway.
- **`hermes-agent/`** — the agent source/venv (Python 3.11.15 on this host).

**Verdict:** `config.yaml` is parseable for static config. Everything else is out of scope for v1.

### 1.7 `~/.hermes/profiles/<name>/logs/` — the per-profile mirror of `~/.hermes/logs/`

Same files. The gateway writes to `~/.hermes/logs/` (top-level), and a per-profile mirror may or may not exist depending on how the gateway was launched. In the active host they're top-level; the per-profile `logs/` is just an empty directory.

### 1.8 The `hermes` CLI itself — what produces structured output

Available subcommands (from `hermes --help`, top-level):
```
chat, model, fallback, secrets, migrate, gateway, proxy, lsp, setup, postinstall,
whatsapp, whatsapp-cloud, slack, send, login, logout, auth, status, cron, webhook,
portal, kanban, hooks, doctor, security, dump, debug, backup, checkpoints, import,
config, pairing, skills, bundles, plugins, curator, memory, tools, computer-use,
mcp, sessions, insights, claw, version, update, uninstall, acp, profile, completion,
dashboard, desktop, gui, logs, prompt-size
```

Useful structured-output subcommands for the dashboard:
- `hermes sessions stats` → multi-line text: `Total sessions: 253 / Total messages: 20416 / cli: 11 sessions / telegram: 124 sessions / Database size: 175.7 MB`
- `hermes kanban stats` → text: `By status: … / By assignee: …`
- `hermes profile list` / `hermes profile show <name>` → YAML-ish
- `hermes gateway status` / `hermes gateway list`
- `hermes cron list` / `hermes cron status` / `hermes cron tick`
- `hermes doctor` → healthcheck

**Verdict:** All parseable, but they are point-in-time snapshots — Prometheus prefers the metrics-from-logs pattern. Use them as **fallback** if a specific metric cannot be derived from logs. They are also useful for an out-of-band "is the exporter even running?" health check.

### 1.9 Native Prometheus / OpenTelemetry in Hermes Agent? — **No**

Searched `hermes-agent/` for `from prometheus_client`, `opentelemetry`, `@prometheus`, `start_http_server.*metrics`, `expose.*metrics`, `exposition_format`:
- `prometheus_client` is **not** in the dependency tree.
- The `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` packages **are** in `uv.lock` (transitive dependency from a downstream package), but there are **no actual `TracerProvider`, `MeterProvider`, or `OTLPSpanExporter` calls** in `hermes_cli/` or `hermes-agent/` source.
- No `start_http_server` calls, no `/metrics` endpoint, no OTel collector env vars.

**Verdict:** Zero built-in instrumentation. We must add a sidecar (or scrape from logs).

### 1.10 Summary table — what's available where

| Source | Path | Format | Has tokens? | Has latency? | Has cost? | Has model? | Per-event or aggregate |
|---|---|---|---|---|---|---|---|
| `state.db.sessions` | `profiles/<n>/state.db` | SQLite | yes (in/out/cache) | derived (ended-started) | yes (`estimated_cost_usd`) | yes | aggregate per session |
| `state.db.messages` | `profiles/<n>/state.db` | SQLite | per-message (`token_count`) | per-message timestamp | no | via session | per-message (per-tool-call) |
| `kanban.db.tasks` | `kanban.db` | SQLite | no | derived (started→completed) | no | `model_override` | per-task |
| `kanban.db.task_runs` | `kanban.db` | SQLite | no | yes (started/ended) | no | no (profile-level) | per-run |
| `kanban.db.task_events` | `kanban.db` | SQLite | no | yes (created_at) | no | no | per-event |
| `agent.log` | `logs/agent.log` | Python `logging` | **yes** (in/out/cache per API call) | **yes** (per API call, per tool) | no | **yes** | per-event |
| `gateway.log` | `logs/gateway.log` | Python `logging` | no | yes (per-conversation `time=Xs`) | no | no | per-conversation |
| `errors.log` | `logs/errors.log` | Python `logging` | no | no | no | no | per-error |
| `cron/jobs.json` | `cron/jobs.json` | JSON | no | last_run_at | no | model (in job) | per-job (config + last status) |
| `config.yaml` | `profiles/<n>/config.yaml` | YAML | no | no | no | yes (default) | static |
| JSONL session exports | `sessions/*.jsonl` | JSONL | no | no | no | yes (header) | per-session export |
| `hermes sessions stats` | CLI | text | summary | no | no | summary | point-in-time |
| `hermes kanban stats` | CLI | text | no | no | no | summary | point-in-time |

**Key insight:** `agent.log` is the only single source that has per-event model, token, latency, cache, AND tool-call breakdown. The dashboard's model/token/latency/tool-call rows can ALL be derived from `agent.log` alone. The SQLite DBs add cost, session duration, and kanban state.

---

## Q2. Metrics design — what should the dashboard show?

Ten metrics below. Each has: **name, type, labels, source, "what the customer learns"**. Each is marked **(free)** if derivable from `agent.log` via alloy regex+metrics stages with no Python code, or **(exporter)** if it needs the small Python sidecar to read SQLite.

| # | Name | Type | Labels | Source | "What the customer learns" |
|---|---|---|---|---|---|
| 1 | `hermes_api_calls_total` | counter | `model, profile, platform, provider` | `agent.log` — `API call #N: model=… provider=…` (free) | "Which models am I driving and how often" — drives the per-model split + per-platform tile. |
| 2 | `hermes_tokens_total` | counter | `model, profile, kind` where `kind ∈ {input, output, cache_read, cache_write, reasoning}` | `agent.log` (free) for `in/out/cache`; `state.db.sessions` (exporter) for `reasoning_tokens` | "Where am I spending tokens" — input vs. output, how much cache I'm getting (cache_read as a sub-total, cache_write as a separate cost line). |
| 3 | `hermes_api_latency_seconds` | histogram | `model, profile, provider` | `agent.log` `latency=Xs` (free) | "How slow is each model" — p50/p95/p99 per model. Surfaces a slow Sonnet vs. fast Flash at a glance. |
| 4 | `hermes_cache_hit_ratio` | gauge | `model, profile` | derived: `sum(rate(tokens_total{kind="cache_read"})) / sum(rate(tokens_total{kind="input"}))` (free) | "How much am I saving by reusing cached prefixes" — 99% on Sonnet = roughly 60–80% cost cut. |
| 5 | `hermes_tool_calls_total` | counter | `tool, profile, outcome` where `outcome ∈ {ok, error}` | `agent.log` `agent.tool_executor: tool <X> completed` and `Tool <X> returned error` (free) | "Which tools am I using, and which are failing" — surfaces e.g. `delegate_task: 12/2 errors`, `terminal: 4693/47 errors`. |
| 6 | `hermes_tool_latency_seconds` | histogram | `tool, profile, outcome` | `agent.log` `(X.XXs, N chars)` (free) | "Which tool calls are slow" — `terminal` p99 vs. `read_file` p99. |
| 7 | `hermes_session_duration_seconds` | histogram | `profile, platform, model` | `state.db.sessions` ended-started (exporter) | "How long does a customer interaction take" — `time=173.9s` in gateway.log is the same data, but state.db gives p50/p95/p99 over many sessions. |
| 8 | `hermes_active_sessions` | gauge | `profile` | `state.db.sessions WHERE ended_at IS NULL` (exporter) | "What's running right now" — also drives a red/green "any session stuck >30 min" alert. |
| 9 | `hermes_kanban_runs_total` | counter | `profile, outcome` | `kanban.db.task_runs` (exporter) | "Kanban throughput and failure rate" — `outcome ∈ {completed, crashed, timed_out, blocked, gave_up}`. |
| 10 | `hermes_kanban_run_duration_seconds` | histogram | `profile, outcome` | `kanban.db.task_runs.ended_at - started_at` (exporter) | "How long do my kanban tasks take" — p50 by outcome. |
| 11 | `hermes_estimated_cost_usd_total` | counter | `model, profile` | `state.db.sessions.estimated_cost_usd` (exporter) | "How much am I spending" — joins to #2 to give $/M-token. The "this month" panel. |
| 12 | `hermes_cron_last_status` | gauge | `job_id, job_name` where value = `1` ok, `0` error, `2` running, `3` skipped | `cron/jobs.json` (exporter — or all in alloy if we tail the file) | "Are my scheduled jobs healthy" — one tile per job, red if last_status=error. |

**Optional stretch (not in v1):**
- `hermes_mcp_calls_total{server, tool, outcome}` — would need Hermes to log MCP calls in a parseable form (it currently logs them via `agent.tool_executor` with the tool name prefixed by the MCP server, e.g. `mcp_inventory_get_device`, so this can be derived from #5 by string-prefixing the tool label — **free**).
- `hermes_prompt_size_bytes` (histogram) — the prompt content sits in `state.db.messages.content` for `role='user'`. Privacy-sensitive; see Q4.
- `hermes_circuit_breaker_trips_total` — sum of `tasks.consecutive_failures` reaching the limit; from `kanban.db` (exporter).

**What these cover for the prompt's 7 categories:**
- *Model usage* → #1, #2, #4, #11
- *Tool calls* → #5, #6
- *Agent latency* → #3, #6, #7, #8
- *Prompt patterns* → #2 (size via the `in` label), #7
- *Session health* → #7, #8
- *Kanban / cron* → #9, #10, #12
- *MCP server health* → stretch; covered by #5

---

## Q3. Implementation patterns — how do people build this kind of dashboard?

Five patterns, plus what the AIAMSBS stack already has.

### 3.1 What AIAMSBS already has on VM 103

Verified via direct probe (loki, prometheus, alloy all `ready`):
- **Loki 3100** — receiving `job=docker` (container stdout/stderr) and `job=syslog` (Promtail syslog receiver on :514). `job=hermes-*` is **not** yet configured.
- **Prometheus 9090** — scraping 6 jobs: `prometheus`, `alloy`, `grafana`, `loki`, `blackbox` (5 endpoints), `blackbox_mcp` (Inventory + Grafana MCP roots), `blackbox_login` (Hermes Dashboard /login), `blackbox_tcp` (Promtail :514), `blackbox_exporter` self. Plus `remote_write` from alloy.
- **Alloy 12345** — two pipelines today: (a) `prometheus.exporter.unix` + `prometheus.scrape` for host metrics; (b) `loki.source.docker` for container logs; (c) `loki.source.journal` for systemd journal. **No `loki.source.file` for `~/.hermes/logs/` yet.** This is the missing piece.
- **Loki labels** currently in use: `app`, `facility`, `host`, `job`, `service_name`, `severity`. We will add `profile`, `session_id`, `tool`, `kind` for the hermes streams.
- **Promtail** is configured for syslog only; not used for file tailing on this host (alloy handles it).

Loki config (`/home/openclaw/AIAMSBS/config/loki.yml`) has `reject_old_samples: true`, `reject_old_samples_max_age: 168h`, `max_streams_match_per_query: 1000`, `max_entries_limit_per_query: 5000` — fine for our use case but a future Loki retention config (BACKLOG #5) is needed for long-term log volume.

### 3.2 Pattern A — Prometheus exporter (custom Python)

Read SQLite DBs and a state file, expose `/metrics` on a port. Alloy/Prometheus scrape it.

**Pros:**
- Standard, well-understood pattern (node_exporter, kafka_exporter, mysqld_exporter all do this).
- Clean separation: one process owns the metric semantics.
- Easy to add new metrics without touching alloy.
- Can compute derived metrics (cache hit ratio, kanban failure rate over 1h window) without resorting to PromQL gymnastics.
- Can include per-session cost totals from `state.db.sessions.estimated_cost_usd` directly.

**Cons:**
- New long-running service to operate, monitor, and ship logs from.
- SQLite is read-only-safe (with `PRAGMA query_only=1`) but the exporter must be careful with the WAL files (`state.db-shm`, `state.db-wal`) and not block writers.
- Python's `sqlite3` is fast enough for our scale (a single-host dashboard, ~250 sessions, 20 K messages, kanban in the dozens-to-hundreds), so no need for anything heavier.
- Suggested port: **9117** (BACKLOG #29's spec) or 9100+ in the unassigned range. VM 103 currently has no listener on 9117.

**Verdict:** Required for the 4 metrics that need SQLite access (#7, #8, #9, #10, #11, #12) — but the 6 metrics that come from `agent.log` don't need it.

### 3.3 Pattern B — Loki log-only (no Prometheus, all structured logs)

Tail `agent.log` with alloy `loki.source.file`, parse with `loki.process` stages, store everything as structured log lines. Grafana queries with LogQL.

**Pros:**
- Zero new services. Add ~50 lines to `config/alloy.yml`.
- No exporter to operate.
- Same path that the BACKLOG #29 spec sketched for the "wire session DB rows (prompts/responses) to Loki" path.

**Cons:**
- **LogQL aggregation is limited.** `sum by (model) (count_over_time({job="hermes-agent"} |~ "API call" [5m]))` works for counters, but rate-of-histograms, p95, percentile estimates are not first-class. To get a true p95 from log-derived data, you need `loki.process stage.metrics` to **promote log lines to Prometheus metrics** — which is pattern (D) hybrid.
- For kanban/cron the structured lines don't exist; you'd have to inject them (cron stdout would need to be redirected into a known file). The `kanban.db.task_runs` table is the natural source.
- Long retention of detailed agent.log lines (multi-MB/day per active host) gets expensive; logs are usually kept <30d.

**Verdict:** This is the right pattern for **detail panels** (recent logs, per-conversation drill-down) and **privacy redaction** (alloy redaction stages run before logs hit Loki). It is **not** the right pattern for the top-of-dashboard tiles, which need p50/p95/counters.

### 3.4 Pattern C — OTel Collector (vendor-neutral standard)

Run `otelcol` as a sidecar. Receivers: `filelog` (agent.log), `sqlquery` (or a Python receiver) for SQLite. Processors: `attributes`, `transform`, `filter`, `batch`, `tailsampling`. Exporters: `prometheus` (pull) or `otlp` → alloy → Prometheus. Plus a `logging` exporter for Loki.

**Pros:**
- Industry standard. The same collector config can be extended to add traces later (e.g. for MCP calls).
- `sqlquery` receiver (alpha in 0.103+) can run a query on a schedule and emit metrics — but the schema is awkward and most teams end up writing a tiny custom Python receiver.
- Decouples parsing (in collector) from storage (still Loki + Prom).
- Hermes Agent already has `opentelemetry-api` and `opentelemetry-exporter-otlp-proto-http` in its dep tree, so an OTel-instrumented future version of Hermes would just point at this collector.

**Cons:**
- Another long-running service. AIAMSBS already has alloy running; adding OTel collector on top is operational overhead.
- Most of the heavy lifting (parsing `agent.log` lines into structured fields) is identical to what `loki.process` does in alloy. We get no win from moving it.
- The `sqlquery` receiver is not great for our scale and our multi-DB layout (`state.db` per profile).
- Heavier binary than alloy; not strictly needed.

**Verdict:** Not worth it for v1. Reserve as the v2 migration path if/when Hermes Agent itself ships native OTel instrumentation (it's already 70% there in `uv.lock`).

### 3.5 Pattern D — Direct DB→Grafana via SQLite data source plugin

Grafana has a community SQLite plugin (`frser-sqlite-datasource` and a few others). Point it at the SQLite file. Write SQL queries as panel data sources. No exporter, no alloy, no Loki.

**Pros:**
- Zero new services. One Grafana plugin install, one data source config, SQL in panel queries.
- Always reads the latest data (no scrape interval lag).
- SQL is the most expressive query language for the data we have.

**Cons:**
- **SQLite is read-locked** during panel renders. With Grafana's 30s default refresh, you hammer the DB 12+ times per minute per panel × N panels. State.db on the active host is 175 MB; concurrent reads during a kanban-dispatch write could cause brief contention.
- Multi-DB layout (`kanban.db` global + `state.db` per profile) means multiple data sources and cross-DB joins aren't natural.
- No `model`, `provider`, `outcome` aggregation in PromQL — SQL aggregates work, but you lose cross-dashboard linking via Grafana's `$__from`/`$__to` time macros.
- The plugin is community-maintained and not on the Grafana stack we're already running.

**Verdict:** Tempting for the "no exporter" path, but it gives up too much (no cross-source correlation, locking risk, multi-DB pain). Reject for v1.

### 3.6 Pattern E — Hybrid (Prometheus exporter for SQLite, Loki for log detail, Grafana unifies)

This is what the BACKLOG #29 original spec called for: a small Python exporter (Pattern A) for SQLite-derived metrics + alloy `loki.source.file` + `loki.process` (Pattern B's parsing) for the log-derived metrics. Grafana queries both. Loki gets the **detail log streams**; Prometheus gets the **count/gauge/histogram series**.

**Pros:**
- **Each tool does what it's good at.** Alloy parses `agent.log` lines into Prometheus metrics via `loki.process stage.metrics` — no Python. Python exporter reads the DBs and adds 6 metrics alloy can't compute (cost, session duration, kanban run outcomes, cron last_status, active sessions, prompt size if we want it).
- The `stage.metrics` feature in alloy is the killer — it extracts log fields and emits them as Prometheus metrics, with histograms, counters, and labels, all in `config/alloy.yml`. Zero new code.
- Loki is the right place for the **detail log drill-down** (and for redaction, see Q4).
- Grafana already knows how to mix PromQL and LogQL in one dashboard via transformations and mixed data-source panels.
- Lowest total cost: ~80 lines of alloy config + ~150-line Python script + 1 Grafana dashboard JSON. No new containers.

**Cons:**
- Two config surfaces (alloy + python exporter + Prometheus scrape config). Slightly more to maintain.
- Two failure modes to alert on (alloy tail lag, exporter scrape failure). Both are blackbox-able, but it's two things.
- The alloy `stage.metrics` config syntax is new for most operators. (Mitigation: the existing `grafana-monitoring-dashboards` skill — if installed — covers it.)

**Verdict:** **Recommended.** This is the path of least resistance that gives 80% of the value, and it composes cleanly with the existing stack.

### 3.7 What the AIAMSBS skills inventory says

The prompt mentioned `hermes-infrastructure-bootstrap` and `grafana-monitoring-dashboards` skills installed for `aiamsbs_dev`. **I could not verify these are installed** — the only skill I see under `~/.hermes/profiles/aiamsbs_dev/skills/` is the standard Hermes skill catalog (`apple`, `autonomous-ai-agents`, `creative`, `data-science`, `devops`, `diagramming`, `dogfood`, `domain`, `email`, `evaluation`, `gaming`, `gifs`, `github`, `inference`, `inference-sh`, `mcp`, `media`, `mlops`, `models`, `note-taking`, `productivity`, `red-teaming`, `research`, `skills`, `smart-home`, `social-media`, `software-development`, `yuanbao`). And the only skill under `/home/openclaw/AIAMSBS/skills/` is `docker-management`. **This is a question for Ryland** — the implementation worker will need either to (a) install/import those skills, (b) confirm the catalog path, or (c) skip them. See Q5 open questions.

---

## Q4. Privacy — how do we handle prompts and secrets?

### 4.1 What kinds of sensitive data are in the sources

- **Prompts**: stored in `state.db.messages.content` for `role='user'` rows. Real customer text: chat history, internal hostnames (`192.168.0.220`, `gstack-iac`), server names, possibly credentials pasted by mistake.
- **API keys**: stored in `~/.hermes/profiles/<name>/.env` (`OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, etc.) and in `auth.json` (~700 bytes, JSON with provider creds). **Not** in the data sources we're scraping. The dashboard never reads `.env`.
- **Tool-call args**: `messages.tool_calls` JSON can include command lines with secrets. E.g. `terminal` tool calls may echo an env var: `KEY=~/.ssh/ansible_rsa VM=192.168.0.220\necho "=== CHECK 12 (retry)'`. The same data also appears in `agent.log` (`agent.tool_executor: Tool terminal returned error (0.10s): {"output": "..."}`).
- **Tool output bodies**: same surface as `tool_calls`. Often multi-KB.
- **Session titles**: `state.db.sessions.title` may carry user-set names with sensitive content.
- **Telegram chat IDs**: low sensitivity but a PII flag (e.g. `chat=8704545814`). The current health dashboard already exposes this label; keep doing so (PII is low risk for an on-prem ops tool).

### 4.2 What to redact

Per the prompt's brief and confirmed by looking at the actual data, redact these patterns before they hit Loki:

1. **API key prefixes** — `sk-…`, `sk-or-…`, `sk-ant-…`, `gAAAAA…` (Bitwarden), JWT-shaped strings.
2. **Generic key=value patterns** — `(?i)\b(api[_-]?key|token|secret|password|passwd|pwd|auth[_-]?token|access[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_./+=-]{8,})['\"]?`.
3. **Bearer tokens** — `(?i)Bearer\s+[A-Za-z0-9_.-]{16,}`.
4. **SSH key material** — `-----BEGIN [A-Z ]+ PRIVATE KEY-----` and any following lines until the end marker.
5. **Internal hostnames / IPs** — `192.168.0.220`, `gstack-iac`, plus the customer's own internal CIDR (Ryland to provide a default for AIAMSBS: `192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`).
6. **Tool-call output truncation** — for the `agent.log` lines that embed a `terminal` output, `stage.truncate` at 512 chars to bound the leak surface.
7. **Prompt body substitution** — for `state.db.messages.content` rows on `role='user'`, replace the body with `sha256(content)[:16]` (a 16-hex fingerprint) and a `len_chars` field. The fingerprint lets the operator correlate prompts across a session without exposing content.

### 4.3 Where to redact

Three candidate layers:

- **In alloy before Loki push** — `loki.process stage.replace` with `expression` and `replace` arguments. **Recommended primary site.** Cheap, runs once, no exporter code to keep in sync. The redaction is in the central config, audited in version control.
- **In the Python exporter before `/metrics`** — only needed for metrics derived from the prompt body (e.g. `hermes_prompt_size_bytes`). The exporter applies the same regex set; if a match is detected, the body is replaced with the hash before being counted.
- **In Grafana at query time** — possible via a value-mapping or a transformation, but it leaks the raw data to the browser. **Do not rely on this for secrets**; it is a last-ditch display-only filter.

The order is: **exporter redact → alloy redact → Grafana display**. Each layer is a safety net, not a primary mechanism.

### 4.4 Opt-out flag

Recommended config surface, in priority order:
- **Per-profile `~/.hermes/profiles/<name>/.env`**: `HERMES_DASHBOARD_REDACT=strict` (default; applies all redactions) | `HERMES_DASHBOARD_REDACT=off` (no redaction; for trusted dev environments). The exporter reads this.
- **Global env `HERMES_DASHBOARD_PROMPTS_IN_LOKI=hash` (default) | `full` | `off`** — controls whether the **prompt body** goes to Loki at all. `hash` = only the sha256[:16] + len_chars fields. `full` = body as-is. `off` = drop the line.
- **Global `HERMES_DASHBOARD_KANBAN_BODIES=off` (default) | `hash` | `full`** — same for `kanban.db.tasks.body` and `task_comments.body`.

These mirror the existing pattern of `TELEGRAM_BOT_TOKEN` etc. in `.env`: a profile-scoped opt-out that the user knows to set.

### 4.5 Retention

- **Loki log streams** (`job=hermes-agent`, `job=hermes-gateway`, `job=hermes-kanban`): default **7d**; override with `HERMES_DASHBOARD_LOG_RETENTION=720h` (30d). The existing Loki config has `reject_old_samples_max_age: 168h = 7d` already; this matches the new content's natural retention.
- **Loki redaction logs** (if we add a separate `job=hermes-redactions` stream that records "I redacted N items of type X" — useful for audit): **90d**.
- **Prometheus TSDB**: default **15d** (matches Prometheus's `storage.tsdb.retention.time` if set). Metric values are aggregates, no PII.
- **`state.db` and `kanban.db`**: not touched by the dashboard. They retain whatever the operator's existing backup policy is.

### 4.6 Specific tooling to cite

- **Alloy `stage.replace`** — the workhorse. `expression` is RE2 regex; `replace` is the substitution string. Apply multiple `stage.replace` blocks in order: sk-prefix → bearer → key=value → BEGIN PRIVATE KEY → IP/CIDR.
- **Alloy `stage.regex`** — extract fields (e.g. the `model=… provider=… in=… out=…` from the API call line) into the extracted-data map.
- **Alloy `stage.logfmt`** — alternative parser for logfmt-formatted lines (Hermes doesn't use logfmt today, but a future version might).
- **Alloy `stage.truncate`** — for tool-call output length caps.
- **Alloy `stage.drop`** — drop a line entirely if a redaction rule fires and we don't want the placeholder to land in Loki.
- **Alloy `stage.metrics`** — emit Prometheus metrics from extracted values.
- **Grafana value mappings** — purely for display: if a log line still contains `REDACTED[sk-***]` after alloy processing, map that to a friendlier color in the panel. **Not** a security boundary.
- **Python `re` (stdlib)** — same regex set in the exporter for the SQLite-derived metrics.

---

## Q5. Concrete recommendation for AIAMSBS BACKLOG #29

A one-page implementation plan.

### 5.1 Architecture choice

**Hybrid (Pattern E).**

1. **Alloy `loki.source.file` + `loki.process`** for the 6 metrics derivable from `agent.log` (items 1–6 in Q2's table) and the detail log streams.
2. **Small Python "agent-exporter"** on port **9117** for the 6 metrics that need SQLite access (items 7–12).
3. **Grafana dashboard** mixed-source: PromQL for tiles, LogQL for the recent-logs panel.

This is the path of least resistance that gives 80%+ of the value with no new containers beyond the Python sidecar, and composes with the existing alloy + Prometheus + Loki + Grafana stack.

### 5.2 Exporter design (Python)

**Name:** `agent-exporter` (matches the BACKLOG #29 spec's `services/agent-exporter/` path).
**Port:** 9117 (matches BACKLOG #29 spec).
**Files (in `services/agent-exporter/`):**
```
agent-exporter/
  pyproject.toml          # stdlib only (sqlite3, http.server, json, re, time)
  agent_exporter.py       # single-file main (~200 lines)
  redactions.py           # regex set, same as alloy
  README.md
  Dockerfile              # python:3.11-slim, ~30 MB
  docker-compose.yml      # or as a systemd unit — pick one
  test_exporter.py        # smoke test against a fixture state.db
```

**What it reads (with `PRAGMA query_only=1`):**
- `~/.hermes/profiles/*/state.db` — glob all profile dirs, read sessions + messages.
- `~/.hermes/kanban.db` and `~/.hermes/profiles/*/kanban.db` — read tasks, task_runs, task_events.
- `~/.hermes/cron/jobs.json` — parse the JSON, emit `hermes_cron_last_status` per job.
- `~/.hermes/profiles/*/config.yaml` — read `model.default` for the "configured default" gauge per profile.

**What it emits (Prometheus text format on `GET /metrics`):**
- The 6 metrics from Q2 marked **(exporter)**: #7 `hermes_session_duration_seconds`, #8 `hermes_active_sessions`, #9 `hermes_kanban_runs_total`, #10 `hermes_kanban_run_duration_seconds`, #11 `hermes_estimated_cost_usd_total`, #12 `hermes_cron_last_status`.
- Plus process metrics: `hermes_exporter_scrape_duration_seconds`, `hermes_exporter_db_size_bytes{path}`.
- Plus self-health: `hermes_exporter_up` (gauge, 0/1).

**Scrape interval:** 30s (matches health dashboard's blackbox probes).

**Re-deploy mechanism:** the existing AIAMSBS `bootstrap.sh` adds the `agent-exporter` container to `docker-compose.yml` (or a systemd unit if Docker-less). Mount `~/.hermes` read-only into the container at the same path. Restart policy: `unless-stopped`.

### 5.3 Loki pipeline (alloy)

Add to `config/alloy.yml`. Order matters: redact first, then parse, then either drop or emit metrics.

```alloy
// File source — tail the three high-value log files
loki.source.file "hermes_agent" {
  targets = [
    { __path__ = "/home/ansible/.hermes/logs/agent.log",   job = "hermes-agent"   },
    { __path__ = "/home/ansible/.hermes/logs/gateway.log", job = "hermes-gateway" },
    { __path__ = "/home/ansible/.hermes/logs/errors.log",  job = "hermes-errors"  },
  ]
  forward_to = [loki.process.hermes_redact.receiver]
  // when running alloy in a container: mount ~/.hermes into the container
}

// Redaction pipeline — runs on every line before any other stage
loki.process "hermes_redact" {
  forward_to = [loki.process.hermes_route.receiver]

  // 1) sk-… and other key prefixes
  stage.replace {
    expression = "sk-[A-Za-z0-9_-]{16,}"
    replace     = "[REDACTED-sk]"
  }
  // 2) bearer tokens
  stage.replace {
    expression = "(?i)Bearer\\s+[A-Za-z0-9_.-]{16,}"
    replace     = "Bearer [REDACTED]"
  }
  // 3) generic key=value (case-insensitive, with optional quotes)
  stage.replace {
    expression = "(?i)\\b(api[_-]?key|token|secret|password|passwd|pwd|auth[_-]?token|access[_-]?key)\\s*[:=]\\s*['\"]?([A-Za-z0-9_./+=-]{8,})['\"]?"
    replace     = "$1=[REDACTED]"
  }
  // 4) BEGIN PRIVATE KEY blocks
  stage.replace {
    expression = "-----BEGIN [A-Z ]+ PRIVATE KEY-----[\\s\\S]*?-----END [A-Z ]+ PRIVATE KEY-----"
    replace     = "[REDACTED-private-key]"
  }
  // 5) Internal hostnames (adjust to customer's CIDR; AIAMSBS default shown)
  stage.replace {
    expression = "\\b(192\\.168\\.\\d{1,3}\\.\\d{1,3}|10\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}|172\\.(1[6-9]|2\\d|3[0-1])\\.\\d{1,3}\\.\\d{1,3})\\b"
    replace     = "[REDACTED-ip]"
  }
}

// Route by job: emit Prometheus metrics for agent.log, forward to Loki for all
loki.process "hermes_route" {
  forward_to = [loki.write.hermes.receiver]

  // Parse the API-call line for stage.metrics
  stage.regex {
    expression = `API call #\d+: model=(?P<model>\S+) provider=(?P<provider>\S+) in=(?P<input>\d+) out=(?P<output>\d+) total=(?P<total>\d+) latency=(?P<latency>[\d.]+)s cache=(?P<cache_read>\d+)/(?P<cache_input>\d+) \((?P<cache_pct>\d+)%\)`
  }
  stage.labels {
    values = {
      model     = "",
      provider  = "",
    }
  }
  stage.metrics {
    metric.counter "hermes_api_calls_total" {
      description = "Total number of LLM API calls"
      prefix      = "hermes_"
      values      = { input = "input", output = "output" }   // see alloy docs
    }
    // ...
  }
}

loki.write "hermes" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

(Trimmed for brevity — full alloy config in the implementation worker's `wt/feat-agent-dashboard-20260701` branch.)

**Note on the bracket tag:** the agent.log lines have `[session_id_or_cron_id]` between the level and the module name. A `stage.regex` with the same expression `\[(?P<session_id>[^\]]+)\]` extracts it as a Loki label. Apply the label via `stage.labels`.

**Why redaction in alloy and not the Python exporter:** alloy runs on every log line before it lands anywhere; the redaction is in one config file; the exporter only re-redacts the small set of fields it pulls from SQLite (prompt body, session title) and uses the same regex set, so they can't diverge.

### 5.4 Dashboard layout — "Vonage look" match

The existing `/home/openclaw/AIAMSBS/config/grafana/provisioning/dashboards/health-check.json` (867 lines, version 5, uid `aiamsbs-health`) defines the visual language. New dashboard JSON at `/home/openclaw/AIAMSBS/config/grafana/provisioning/dashboards/agent-activity.json` mirrors it:

**24-column grid. 6 rows, 8 panels visible in 10 seconds:**

| Row | Position | Type | Data source | Target | "Vonage look" property |
|---|---|---|---|---|---|
| **1. Profile status** (h=2) | x=0–23 | 12× `stat` (2×2 each) | PromQL | `hermes_active_sessions{profile}` (threshold: 0=green, ≥5=yellow, ≥20=red) | `colorMode:"background"`, `textMode:"name"`, `graphMode:"none"` — matches health-check tile rows |
| **2. Model in use** (h=2) | x=0–23 | 6× `stat` (4×2 each) | PromQL | `topk(6, sum by (model) (rate(hermes_api_calls_total[1h])))` formatted as model name | same tile pattern |
| **3. Kanban + Cron** (h=2) | x=0–23 | 6× `stat` (4×2 each) | PromQL | `hermes_kanban_runs_total` (5m rate) per assignee, `hermes_cron_last_status` per job (1=green, 0=red) | same tile pattern |
| **4. Token / cost burn** (h=4) | x=0–11 | `timeseries` | PromQL | `sum by (kind) (rate(hermes_tokens_total[5m]))` stacked, kind=input/output/cache_read/cache_write | sparkline-style |
| (same row) | x=12–23 | `stat` (gauge) | PromQL | `sum(rate(hermes_estimated_cost_usd_total[1h]))` (single dollar/hour gauge) | "this hour" gauge |
| **5. Latency & tool p99** (h=4) | x=0–11 | `timeseries` | PromQL | `histogram_quantile(0.99, sum by (le, model) (rate(hermes_api_latency_seconds_bucket[5m])))` | p99 lines per model |
| (same row) | x=12–23 | `timeseries` | PromQL | top 5 tools by p99 latency | bar/line |
| **6. Recent activity logs** (h=24) | x=0–23 | `logs` | LogQL | `{job=~"hermes-agent\|hermes-gateway"}` with label filter `$profile` and search box | matches the existing health-check logs panel |
| **7. Tool-call error table** (h=8) | x=0–23 | `table` | PromQL | `topk(20, sum by (tool, profile) (rate(hermes_tool_calls_total{outcome="error"}[1h])))` | sortable, color-graded |
| **8. Session health** (h=8) | x=0–23 | `timeseries` | PromQL | `histogram_quantile(0.5/0.95/0.99, sum by (le) (rate(hermes_session_duration_seconds_bucket[1h])))` | p50/p95/p99 lines |

Total: 30 panels. Refresh: 30s (matches health-check). Tags: `["aiamsbs", "agent", "activity", "hermes", "vonage"]`.

**Variables (templating):**
- `$profile` — `label_values(hermes_api_calls_total, profile)` (multi, includeAll)
- `$model` — `label_values(hermes_api_calls_total{profile=~"$profile"}, model)` (multi)
- `$tool` — `label_values(hermes_tool_calls_total, tool)` (multi, includeAll)
- `$time_range` — default `now-15m` (matches health-check)

**Why this matches the "Vonage look":**
- Top three rows are 2×2 tile grids with `colorMode:"background"`, `textMode:"name"`, `graphMode:"none"`, identical field-config structure to the existing health-check panels #10–14 and #40–43. A user looking at both dashboards sees the same tile language.
- Time series rows use the same `custom.drawStyle:"line"`, `lineInterpolation:"smooth"`, `lineWidth:2`, `fillOpacity:10`, `showPoints:"never"`, `spanNulls:true` style as health-check #60–62.
- Logs panel at the bottom is a `type:"logs"` with `enableLogDetails:true`, `showLabels:true`, `wrapLogMessage:true`, `sortOrder:"Descending"` — same as health-check #30.

### 5.5 Privacy defaults (from Q4)

- **Alloy redaction stages enabled by default** in `config/alloy.yml` — the regexes in Q4.2 ship in the file.
- **`HERMES_DASHBOARD_REDACT=strict` default** in `agent-exporter`'s environment.
- **`HERMES_DASHBOARD_PROMPTS_IN_LOKI=hash` default** — full prompt body never lands in Loki; only `prompt_sha256_16` and `prompt_len_chars` from the Python exporter.
- **`HERMES_DASHBOARD_LOG_RETENTION=168h` (7d)** — matches Loki's existing `reject_old_samples_max_age`.
- **`HERMES_DASHBOARD_KANBAN_BODIES=off` default** — task body and comment body never logged; only title (often benign) plus assignee, status, outcome, timing.
- All defaults overridable per-profile via `~/.hermes/profiles/<name>/.env`. The exporter's README documents the keys.

### 5.6 Phasing

**v1 (MVP — this implementation card):**
- Items 1, 2, 3, 5, 6 from Q2 (alloy `loki.source.file` + `loki.process stage.metrics`).
- Items 7, 8, 9, 10, 11, 12 from Q2 (Python exporter, ~200 LoC).
- Full redaction pipeline (Q4.2 regex set, in alloy).
- Dashboard rows 1–8 (Q5.4).
- `services/agent-exporter/` skeleton in the AIAMSBS repo with `docker-compose.yml` add, `bootstrap.sh` patch, smoke test.
- Loki retention tweak (24h for the raw `hermes-agent`/`hermes-gateway` streams; this also closes a slice of BACKLOG #5).

**v2 (next card, deferred):**
- `hermes_mcp_calls_total` (parse tool-name prefix from `agent.tool_executor`).
- `hermes_prompt_size_bytes` histogram (exporter, requires the `prompts_in_loki=full` opt-in).
- `hermes_circuit_breaker_trips_total` (exporter, count of `tasks.consecutive_failures` crossing the limit).
- A small "deep-dive" per-session page in Grafana (click a session ID in the logs panel → side panel with messages, tool calls, token use).
- Optional: instrument the gateway itself with OTel (Hermes already has the dep tree) so a future version of Hermes can emit spans directly to the OTel collector and we drop the log-parsing step.

**Stretch (park as separate items):**
- Anomaly detection on `hermes_api_latency_seconds` (e.g. "Sonnet p99 doubled in the last 5m" alert).
- Cost alert ("today's burn rate > $X" based on `hermes_estimated_cost_usd_total` rate of change).
- Self-test in `agent-exporter` that runs a synthetic session and verifies the metrics endpoint, with a blackbox_http_2xx probe on `/metrics` added to `config/prometheus.yml` (the existing `blackbox` job pattern).

### 5.7 Open questions for Ryland

1. **Profile naming discrepancy.** The brief says profiles on VM 103 are `aiamsbs_dev`, `aiamsbs_research`, `default`. The actual VM 103 has only `it_admin` (per the bootstrap, as resolved in BACKLOG #24). The implementation needs a confirmed list of profile names. **Does the implementation worker also need to bootstrap additional profiles on VM 103, or does the dashboard just glob `~/.hermes/profiles/*` and label by the directory name?**
2. **Skills catalog.** The brief references `hermes-infrastructure-bootstrap` and `grafana-monitoring-dashboards` skills installed for `aiamsbs_dev`. They are not present in `~/.hermes/profiles/aiamsbs_dev/skills/` (only the standard skill catalog is). **Should the implementation worker install those skills as a prereq, or are the relevant alloy/Prometheus/Loki snippets already covered by the existing `docker-management` skill in `/home/openclaw/AIAMSBS/skills/`?**
3. **Default redaction CIDR.** Q4.2 lists the standard RFC1918 ranges for IP redaction. AIAMSBS is on `192.168.0.0/24` for the management network. **Is there any non-RFC1918 internal range the customer also wants redacted (e.g. an RFC1918-explicit `aiamsbs.local` hostname, or a customer-specific CIDR)?** Default if no answer: redact `192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`, plus the literal hostname `gstack-iac`.

### 5.8 Implementation handoff — files the worker needs to create

This is the checklist for the implementation card (after Ryland's review of this research):

**New files in the AIAMSBS repo:**
- `services/agent-exporter/agent_exporter.py` (~200 LoC)
- `services/agent-exporter/redactions.py` (~40 LoC)
- `services/agent-exporter/pyproject.toml`
- `services/agent-exporter/Dockerfile`
- `services/agent-exporter/test_exporter.py`
- `services/agent-exporter/README.md`
- `config/grafana/provisioning/dashboards/agent-activity.json` (~600 LoC, matches health-check style)

**Modified files:**
- `config/alloy.yml` — add `loki.source.file` for `~/.hermes/logs/*.log`, `loki.process` redaction + parse + `stage.metrics`.
- `config/prometheus.yml` — add scrape job `agent-exporter` on `localhost:9117` (or `agent-exporter:9117` if containerized).
- `docker-compose.yml` — add `agent-exporter` service, mount `~/.hermes` read-only.
- `bootstrap.sh` — add `register_agent_exporter` function (or whichever naming convention it uses), following the pattern of `register_inventory_mcp` (BACKLOG #24).
- `BACKLOG.md` — close row 29 with a "RESOLVED" line linking to the commit (matches the format of #1, #2, #11, #24, #25, #26).

**Out of scope (explicitly NOT in this card):**
- BACKLOG #5 (Loki retention config) — touched but not solved; long-term retention is a separate card.
- BACKLOG #27 (host logs in health dashboard) — separate card; the agent dashboard does not need to repeat that work.
- OTel instrumentation of Hermes Agent itself — depends on Hermes shipping native OTel (it has the deps in `uv.lock` but emits nothing today).
- Changes to the AIAMSBS `release + CI/CD pattern` (BACKLOG #23) — the `agent-exporter` is a new service and should follow whatever that card eventually lands.

---

## Appendix A — Verified file paths on the active host (reference for the worker)

```
/home/openclaw/.hermes/profiles/aiamsbs_dev/state.db                  (114 MB, sessions+messages)
/home/openclaw/.hermes/profiles/aiamsbs_dev/state.db-shm
/home/openclaw/.hermes/profiles/aiamsbs_dev/state.db-wal
/home/openclaw/.hermes/profiles/aiamsbs_dev/kanban.db                  (114 KB, tasks+runs+events)
/home/openclaw/.hermes/profiles/aiamsbs_dev/config.yaml
/home/openclaw/.hermes/profiles/aiamsbs_dev/.env
/home/openclaw/.hermes/profiles/aiamsbs_dev/SOUL.md
/home/openclaw/.hermes/profiles/aiamsbs_dev/.hermes_history
/home/openclaw/.hermes/profiles/aiamsbs_dev/memories/MEMORY.md
/home/openclaw/.hermes/profiles/aiamsbs_dev/memories/USER.md
/home/openclaw/.hermes/profiles/aiamsbs_dev/hermes-agent/              (source)
/home/openclaw/.hermes/profiles/aiamsbs_dev/sessions/                  (JSONL exports, mostly empty)
/home/openclaw/.hermes/profiles/aiamsbs_dev/cron/                      (no jobs.json; global has it)
/home/openclaw/.hermes/profiles/aiamsbs_research/                      (parallel layout)

/home/openclaw/.hermes/kanban.db                                      (114 KB, global orchestrator)
/home/openclaw/.hermes/cron/jobs.json                                 (5 KB, all cron jobs)
/home/openclaw/.hermes/cron/output/<job_id>/                          (per-run outputs)
/home/openclaw/.hermes/logs/agent.log                                 (2.3 MB current, rotated)
/home/openclaw/.hermes/logs/gateway.log                               (1.4 MB current)
/home/openclaw/.hermes/logs/errors.log                                (988 KB current)
/home/openclaw/.hermes/.env                                           (secrets — DO NOT SCRAPE)
```

## Appendix B — Verified file paths on VM 103 (`gstack-iac`)

```
/home/ansible/.hermes/profiles/it_admin/state.db                      (745 KB — fresh bootstrap)
/home/ansible/.hermes/profiles/it_admin/config.yaml                   (490 bytes — minimal)
/home/ansible/.hermes/profiles/it_admin/.env                          (291 bytes — no API key yet)
/home/ansible/.hermes/profiles/it_admin/SOUL.md                       (10.5 KB — full IT-admin SOUL)
/home/ansible/.hermes/profiles/it_admin/hermes-agent/                 (source)
/home/ansible/.hermes/profiles/it_admin/sessions/                     (empty)
/home/ansible/.hermes/profiles/it_admin/cron/                         (no jobs.json; global has none)
/home/ansible/.hermes/profiles/it_admin/logs/                         (mirror of ~/.hermes/logs/)

/home/ansible/.hermes/cron/jobs.json                                 (does not exist — no cron yet)
/home/ansible/.hermes/kanban.db                                      (does not exist — no kanban yet)
/home/ansible/.hermes/logs/agent.log                                 (39 KB, just bootstrapping)
/home/ansible/.hermes/logs/errors.log
/home/ansible/.hermes/logs/gui.log
/home/ansible/.hermes/logs/dashboard-auth.log
```

**The implementation will be landing on a fresh VM.** This means the data sources are present and the schema is identical to the active host's, but they are empty. The dashboard will start showing "no data" until real sessions and kanban tasks accumulate — expected behavior, and the dashboard should render the empty state gracefully (gray tile = no data; per the existing health-check convention, `null` series → no color, no number).

## Appendix C — `hermes` CLI one-liners for testing (no exporter yet)

The implementation worker can sanity-check the data sources without any code by running these on a populated host:

```bash
# How many sessions, how big is the DB
hermes sessions stats

# How many kanban tasks, by status
hermes kanban stats

# Recent tool-call activity (last 200 lines, filtered)
tail -200 ~/.hermes/logs/agent.log | grep "agent.tool_executor"

# Most recent API call (gives you one row of model/provider/tokens/latency)
grep "API call" ~/.hermes/logs/agent.log | tail -1

# Token totals for the last completed session
sqlite3 ~/.hermes/profiles/aiamsbs_dev/state.db \
  "SELECT id, model, input_tokens, output_tokens, cache_read_tokens, estimated_cost_usd
   FROM sessions WHERE ended_at IS NOT NULL
   ORDER BY started_at DESC LIMIT 5;"

# Kanban run outcomes in the last 24h
sqlite3 ~/.hermes/kanban.db \
  "SELECT outcome, COUNT(*), AVG(ended_at - started_at) AS avg_sec
   FROM task_runs WHERE started_at > strftime('%s','now','-1 day')
   GROUP BY outcome;"
```

## Appendix D — Existing health dashboard panels (the "Vonage look" reference)

For convenience, the field-config structure of a single health-check tile (verbatim from `health-check.json` lines 47–87):

```json
{
  "id": 10,
  "title": "",
  "type": "stat",
  "datasource": { "type": "prometheus", "uid": "Prometheus" },
  "gridPos": { "h": 2, "w": 2, "x": 8, "y": 0 },
  "targets": [
    {
      "expr": "max by (instance) (probe_success{job=\"blackbox\",instance=\"http://localhost:12345/-/ready\"})",
      "legendFormat": "Alloy",
      "refId": "A"
    }
  ],
  "fieldConfig": {
    "defaults": {
      "unit": "none",
      "thresholds": {
        "mode": "absolute",
        "steps": [
          { "color": "red" },
          { "color": "green", "value": 1 }
        ]
      }
    }
  },
  "options": {
    "colorMode": "background",
    "graphMode": "none",
    "justifyMode": "center",
    "textMode": "name"
  }
}
```

The agent-activity dashboard tiles use the **same** field-config block. The only differences: (a) datasource is still `Prometheus` (the alloy `stage.metrics` output lands there), (b) thresholds vary per metric (e.g. for `hermes_active_sessions`, `0=green, 1-4=yellow, ≥5=red`).

---

*End of research. Implementation worker should be able to read this and start building without further questions. The three open questions in Q5.7 are the only blocking items.*
