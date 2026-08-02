# skills/aiamsbs-stack-config.md — AIAMSBS stack — config file locations

## Purpose

Canonical paths to the AIAMSBS monitoring stack config files on the AIAMSBS host. When the user asks to add, change, or inspect any AIAMSBS service config (Prometheus targets, Alloy sources, Loki, Grafana, Promtail, Blackbox), this skill points the agent at the right file.

**Not** for general Linux admin or device inventory — those have their own skills.

## Where the configs live

The AIAMSBS monitoring stack lives at `$INSTALL_BASE_DIR/AIAMSBS/` (defaults to `$HOME/AIAMSBS/`). All service config files under `config/` are bind-mounted (read-only) into their respective containers, so the host file is the **single source of truth** — there is no separate "in-container" copy to edit.

| Service | Config file |
|---|---|
| Prometheus | `$INSTALL_BASE_DIR/AIAMSBS/config/prometheus.yml` |
| Alloy | `$INSTALL_BASE_DIR/AIAMSBS/config/alloy.yml` |
| Loki | `$INSTALL_BASE_DIR/AIAMSBS/config/loki.yml` |
| Promtail | `$INSTALL_BASE_DIR/AIAMSBS/config/promtail.yml` |
| Blackbox | `$INSTALL_BASE_DIR/AIAMSBS/config/blackbox.yml` |
| Grafana provisioning | `$INSTALL_BASE_DIR/AIAMSBS/config/grafana/provisioning/` |

## Common mistakes to avoid

- **Editing inside the container.** `docker exec prometheus vim /etc/prometheus/prometheus.yml` will either fail (the bind mount is read-only) or appear to succeed and silently be lost on the next container recreate. Always edit the host file.
- **Editing the wrong file.** When `prometheus` and `promtool` both report the active config, the source of truth is the host file. Container-side tools reflect what the container last read; reload via `curl -X POST http://localhost:9090/-/reload` (Prometheus) or a service restart (others).
- **Forgetting the `-/reload` call.** After editing `prometheus.yml`, Prometheus picks up changes only when you POST to `/-/reload` (or the container restarts). Without that, your edit sits on disk but the running service uses the old config.
- **Putting generated target files in `config/prometheus.yml`.** Per-job target files (e.g., `config/prometheus/targets/blackbox_inventory.json`) live alongside `prometheus.yml` and are referenced by `file_sd_configs`. Don't paste target lists inline into the main file when there's a `file_sd_configs` pattern for them.

## Verification

After any config edit, confirm the service picked up the change:

- Prometheus: `curl -s http://localhost:9090/api/v1/status/config | jq '.data.yaml'` shows the live config
- Loki: `curl -s http://localhost:3100/config` (only after restart)
- Alloy: `curl -s http://localhost:12345/-/ready` + check `docker logs alloy --tail 50`
- Blackbox: targets appear under `http://localhost:9115/` (the blackbox_exporter's web UI)

If the file on disk and the running service disagree, that's a real defect, not "done" — surface it.
