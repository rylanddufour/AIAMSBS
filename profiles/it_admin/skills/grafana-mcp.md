# skills/grafana-mcp.md — Observability via the Grafana MCP Server

## Purpose

This skill teaches the IT_ADMIN agent to use the `grafana-mcp` MCP server
(the Grafana MCP shipped by `mcp/grafana/`) in the course of normal
datacenter-administration work — health checks, alert triage, dashboard
inspection, log/error analysis, and incident response.

The MCP server is already registered in this profile's
`~/.hermes/profiles/it_admin/config.yaml` by `bootstrap.sh` (BACKLOG #7 +
#21). This skill is what makes the agent *aware* of the tools and follow
safe workflows when using them.

## Non-Destructive Policy

This skill inherits the global non-destructive operating policy from
`soul.md` and the destructive-operation guardrails from
`skills/non-destructive-operations.md`.

Read-only tools (`list_*`, `get_*`, `query_*`, `search_*`, `check_*`) may be
called directly. Write operations (`create_*`, `update_*`, `delete_*`,
`install_*`, `alerting_manage_rules` create/update/delete) require
explicit human approval per the confirmation policy in `soul.md`.

## When to use grafana-mcp

Use `grafana-mcp` whenever the task involves observability — typically
*before* opening an SSH/PowerShell/CLI session on a managed device
("is it actually down, or is it just one probe failing?") and *during*
incident triage ("what alerts fired, what does the dashboard say, what's
in the logs?").

Common triggers:

- "Is service X healthy right now?" → `check_datasources_health`,
  `query_prometheus` for `up`/`probe_success`, `query_loki_logs` for
  recent errors from that service
- "What alerts are firing?" → `list_alert_groups`, `get_alert_group`,
  `alerting_manage_rules` (operation: 'list')
- "Add a CPU alert rule to the AIAMSBS Health dashboard" →
  `search_dashboards` → `get_dashboard_panel_queries` → draft rule →
  approval → `alerting_manage_rules` (operation: 'create')
- "Where did the 5xx errors spike?" → `query_loki_logs` with `{job="..."}`
  → `find_error_pattern_logs` → `find_slow_requests`
- "What dashboards cover this service?" → `search_dashboards` by tag/job
- "Who's on call right now?" → `list_oncall_schedules` →
  `get_current_oncall_users`
- "Document incident X" → `get_incident`, `add_activity_to_incident`
- "Why is this Prometheus query returning nothing?" →
  `list_prometheus_metric_names` → `list_prometheus_label_values` to
  verify label names match what your query assumes

## Tool groups (64 tools total — these are the ones IT_ADMIN actually uses)

The full list is available via the MCP `tools/list` method or by running
`mcporter call list_tools --http-url http://localhost:8000/mcp`. Grouped
by purpose:

### Health & queries (most-used)

- `check_datasources_health` — quick all-up check on Prometheus / Loki /
  other datasources; run this first when troubleshooting "Grafana looks empty"
- `query_prometheus(expr)` — PromQL instant/ range query
- `query_prometheus_histogram(expr)` — histogram quantiles
- `query_loki_logs({label_filters}, since)` — LogQL query for recent logs
- `query_loki_patterns(query)` — pattern-aggregated log view (good for
  spotting recurring error shapes)
- `query_loki_stats(query)` — log ingestion rate
- `query_pyroscope(query)` — profiling data
- `find_error_pattern_logs({job, since})` — auto-extract error patterns
- `find_slow_requests({job, since})` — slowest requests from logs

### Label & metric discovery

- `list_prometheus_metric_names({job})` — what metrics exist?
- `list_prometheus_label_names({job})` / `list_prometheus_label_values(name, {job})`
- `list_prometheus_metric_metadata(metric)` — type, help, unit
- `list_loki_label_names({job})` / `list_loki_label_values(name, {job})`
- `analyze_loki_labels({job})` — recommended label cardinality config
- `list_pyroscope_label_names` / `list_pyroscope_label_values` /
  `list_pyroscope_profile_types`

### Dashboards

- `search_dashboards(query)` — find by title/tag/folder
- `get_dashboard_by_uid(uid)` — full dashboard JSON
- `get_dashboard_summary(uid)` — title + panel count + tags (lightweight)
- `get_dashboard_panel_queries(uid)` — PromQL/LogQL per panel (great for
  copying query patterns into alerts)
- `get_dashboard_property(uid, key)` — one specific field
- `update_dashboard(dashboard)` — write back JSON; **requires approval**
- `create_folder` / `search_folders` — organize dashboards

### Datasources

- `list_datasources` / `get_datasource(uid)`
- `create_datasource` / `update_datasource` — **requires approval**
- `check_datasources_health` — health-check all

### Alerts & routing

- `list_alert_groups` / `get_alert_group(id)`
- `alerting_manage_rules(operation, ...)` — list/get/versions/create/
  update/delete alert rules. **Create/update/delete require approval.**
  Before creating a rule, always call this with operation: 'list' +
  a label selector to check for duplicates and operation: 'get' to see
  the full rule config schema.
- `alerting_manage_routing(operation, ...)` — notification policies,
  contact points, mute intervals (read-only here; write requires approval)

### Annotations

- `get_annotations` / `get_annotation_tags`
- `create_annotation` / `update_annotation` — **requires approval**

### Incidents & OnCall (Grafana Incident + OnCall)

- `list_incidents` / `get_incident(id)` / `create_incident` /
  `add_activity_to_incident` — `create_incident` requires approval
- `list_oncall_schedules` / `list_oncall_teams` / `list_oncall_users`
- `get_oncall_shift` / `get_current_oncall_users`

### Sift (Grafana Sift investigation)

- `list_sift_investigations` / `get_sift_investigation(id)` /
  `get_sift_analysis(id)`

### Snapshots, plugins, provisioning

- `list_snapshots` / `get_snapshot` / `create_snapshot` /
  `delete_snapshot` — **write ops require approval**
- `list_provisioning_repositories` / `validate_provisioning_file`
- `search_plugin_information` / `get_plugin` / `install_plugin` —
  `install_plugin` requires approval
- `get_assertions` / `generate_deeplink` / `get_panel_image` /
  `grafana_api_request` / `suggest_loki_alloy_label_config`

## Workflow: troubleshooting a service outage

1. **`check_datasources_health`** — is Prometheus itself up?
2. **`query_prometheus`** for `up{job="<job>"} == 0` — which targets are
   down? (or `probe_success` for blackbox-monitored services)
3. **`query_loki_logs`** with `{job="<service>"} | json | level="error"`
   for the last 30 minutes — what's failing?
4. **`find_error_pattern_logs`** — group recurring errors
5. **`list_alert_groups`** — what's already firing? Has anyone ack'd?
6. **`list_oncall_schedules`** → **`get_current_oncall_users`** —
   who's responsible for this service right now?
7. **Open an SSH session to the device** (using inventory-mcp
   `lookup_by_ip` to get the credential reference first)
8. **Document what you found** in an incident via `create_incident` +
   `add_activity_to_incident` (requires approval)

## Workflow: creating a new alert rule

1. **`search_dashboards`** for an existing dashboard that covers the
   condition (usually there's already a panel with the PromQL you want)
2. **`get_dashboard_panel_queries(uid)`** to copy the PromQL exactly
3. **`list_prometheus_label_names`** to confirm label names match
   (e.g. is it `instance` or `pod`?)
4. **`alerting_manage_rules(operation='list', label_selectors=...)`**
   to check for duplicate rules
5. **Draft the rule** with all required fields (folder_uid, rule_group,
   for, no_data_state, exec_err_state, condition, data, labels,
   annotations, notification_settings)
6. **Present the rule to the Customer** for approval (per soul.md
   Confirmation Standard)
7. After approval: **`alerting_manage_rules(operation='create', ...)`**
8. Verify with **`alerting_manage_rules(operation='get', uid=<new>)`**

## Related skills

- **`skills/inventory-management.md`** — use inventory-mcp to look up the
  managed device's IP, vendor/model, and credential reference *before*
  opening a remote session
- **`skills/monitoring-observability.md`** — broader monitoring guidance
  (Prometheus, Loki, Alloy concepts)
- **`skills/non-destructive-operations.md`** — confirmation flow for
  write operations

## Reference

- MCP server: `grafana-mcp` (container `grafana-mcp`, port 8000)
- Source: `mcp/grafana/` (grafana/mcp-grafana Docker image)
- Bootstrap step: `register_grafana_mcp` in `bootstrap.sh` (BACKLOG #21)
- All 64 tools: run `mcporter call list_tools --http-url
  http://localhost:8000/mcp --allow-http`