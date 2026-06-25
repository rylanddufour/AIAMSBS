# AIAMSBS Deployment

**This document is historical.** It used to be a "deployment plan" that an
LLM agent would follow when prompted via `hermes chat -q "$(cat GOAL.md)"`.
That approach has been retired.

## Current deployment path

`bootstrap.sh` is the **single source of truth** for installing AIAMSBS.
It does everything this document used to describe — and more — deterministically
(no LLM in the deploy path):

```bash
curl -fsSL https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/bootstrap.sh | \
  bash -s -- --api-key YOUR_KEY --provider openrouter --model minimax/minimax-m2.5
```

After bootstrap finishes, it prints a customer-facing summary at the end with
URLs, default credentials, listening ports, and a "verify the LLM is working"
hint pointing at `hermes chat -q "hello!"`. That single command is the
end-to-end smoke test that confirms the entire stack is healthy.

## What bootstrap.sh handles (no prompt needed)

| Step | Function in `bootstrap.sh` |
|---|---|
| Install Docker + Compose | `install_docker`, `install_docker_compose` |
| Install Hermes Agent | `install_hermes` |
| Configure API key + model | `configure_hermes_api` |
| Build Dashboard UI | `build_dashboard_ui` |
| Generate Dashboard credentials (basic auth) | `generate_dashboard_credentials` |
| Install + start Dashboard (systemd) | `install_hermes_dashboard_service`, `start_hermes_dashboard` |
| Deploy main observability stack (Prometheus, Loki, Alloy, Promtail, Grafana) | `auto_deploy_stack` |
| Install Grafana skills | `install_grafana_skills` |
| Create Grafana service account for MCP | `create_grafana_mcp_service_account` |
| Deploy Grafana MCP server | `deploy_mcp_stack` |
| Deploy Inventory MCP stack | `deploy_inventory_stack` |
| Verify everything is healthy | `verify_installation` |

## Adding new deployment logic

If you need to change how AIAMSBS is deployed:

1. **Edit `bootstrap.sh`** — add or modify a function, wire it into `main()`.
2. **Re-run bootstrap on a clean VM** (via Proxmox snapshot rollback) to verify.
3. **Commit + push** to the feature branch. The customer-facing summary at the
   end of bootstrap is the visible signal that the change works end-to-end.

## Related docs

- `README.md` — quick start
- `BACKLOG.md` — feature backlog
- `SECURITY.md` — vulnerability reporting
- AIAMSBS_Docs_Diagrams (OneDrive) — full docs project including operational
  walkthroughs and troubleshooting

## Version

- Original: deployment plan consumed by an LLM prompt
- Current: stub pointing at `bootstrap.sh` as source of truth
- Retired: 2026-06-25 (commit `0dcfcc6` on branch
  `feature/bootstrap-customer-experience-20260625`)