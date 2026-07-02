# agent-exporter (BACKLOG #29)

Prometheus exporter that surfaces **AI Agent activity** from a running Hermes
host: session counts, model/token usage, cost, tool calls (latency + error
rate), kanban run outcomes, and cron job health.

This is the SQLite-derived half of the **Hybrid (Pattern E)** architecture
described in `research/agent-activity-dashboard-2026-07-01.md`. The other half
(alloy `loki.process stage.metrics` for log-derived metrics) lives in
`config/alloy.yml`.

## Data sources (read-only, no writes)

| Path | What we read |
| --- | --- |
| `~/.hermes/profiles/*/state.db` | `sessions` (model, tokens, cost, duration, end_reason), `ended_at IS NULL` for active |
| `~/.hermes/kanban.db` and `~/.hermes/profiles/*/kanban.db` | `tasks` (assignee), `task_runs` (status, outcome, timing) |
| `~/.hermes/cron/jobs.json` | per-job `last_status`, `last_run_at` (ISO-8601 → unix epoch) |

All SQLite reads use `file:...mode=ro` URI + `PRAGMA query_only=1`. WAL
sidecars (`-wal`, `-shm`) are honored automatically.

## Metrics emitted on `/metrics`

| Metric | Type | Labels | Source |
| --- | --- | --- | --- |
| `hermes_session_duration_seconds` | histogram | `profile`, `end_reason` | sessions.ended_at - started_at |
| `hermes_sessions_active` | gauge | `profile` | count(sessions WHERE ended_at IS NULL) |
| `hermes_estimated_cost_usd_total` | counter | `model`, `profile` | sessions.estimated_cost_usd |
| `hermes_kanban_runs_total` | counter | `assignee`, `outcome` | task_runs (terminal status only) |
| `hermes_kanban_runs_in_flight` | gauge | `assignee` | task_runs WHERE status='running' |
| `hermes_cron_job_last_success_timestamp` | gauge | `job_name` | cron/jobs.json last_status=ok → unix epoch |
| `hermes_exporter_up` | gauge | — | self-health: 1 if last scrape succeeded |
| `hermes_exporter_scrape_duration_seconds` | histogram | — | self-health: scrape wall time |
| `hermes_exporter_db_size_bytes` | gauge | `path` | self-health: SQLite file size in bytes |

Six metrics from `agent.log` (API calls, tokens, tool latencies, errors) are
emitted by the alloy pipeline in `config/alloy.yml` — this exporter does not
parse logs.

## Run it

```bash
# from the AIAMSBS repo root:
docker compose -f services/agent-exporter/docker-compose.yml up -d

# verify:
curl -s http://localhost:9117/healthz
curl -s http://localhost:9117/metrics | head
```

The bootstrap script (`bootstrap.sh` → `deploy_agent_exporter()`) runs the
same `docker compose up -d` so a fresh customer bootstrap brings the exporter
up alongside Prometheus.

## Environment variables

| Var | Default | Description |
| --- | --- | --- |
| `AGENT_EXPORTER_PORT` | `9117` | HTTP listen port |
| `AGENT_EXPORTER_INTERVAL` | `15` | (informational) scrape interval, in seconds |
| `AGENT_EXPORTER_LOG_LEVEL` | `INFO` | Python logging level |
| `HERMES_HOME` | `~/.hermes` | Where to find state.db / kanban.db / cron/jobs.json |

## Profile discovery

The exporter **globs** `~/.hermes/profiles/*/state.db` and labels every metric
with `{profile=<dirname>}`. It never hardcodes profile names. If a customer
has only one profile (`it_admin`), metrics carry that label; if a customer
later adds `default`, the labels update automatically on the next scrape.

## Privacy

- No prompt content is read. `state.db.sessions.system_prompt` and
  `messages.content` are never queried.
- No tool call arguments are read. `messages.tool_calls` JSON is not exposed.
- Cost is the only row-level numeric data exposed; it's already aggregate.
- The alloy redaction pipeline (Q4.2 regex set in `config/alloy.yml`) is
  the primary defense for log-side privacy. Per-customer redaction (CIDR
  lists, custom secrets) is a follow-up; the v1 default is "ship metrics,
  not content."

## Files

```
agent-exporter/
  agent_exporter.py     # single-file main (~540 LoC, stdlib + prometheus_client)
  Dockerfile            # python:3.12-slim, no build step
  docker-compose.yml    # network_mode: host, ro mount, restart unless-stopped
  README.md             # this file
```

## Out of scope (BACKLOG #29 v1)

- Log-derived metrics — those come from alloy `loki.process stage.metrics`,
  not this exporter. See `config/alloy.yml`.
- Per-message tool-call histograms — the exporter only emits session-level
  aggregates. v2 may add `hermes_tool_calls_total` from the messages table.
- Per-prompt cost alerts, anomaly detection — separate card.
