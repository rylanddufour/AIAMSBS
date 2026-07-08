---
name: aiamsbs-stack-config
title: AIAMSBS stack — config file locations
description: Canonical paths to the AIAMSBS monitoring stack config files on the AIAMSBS host. Use when adding/changing/inspecting prometheus, alloy, loki, grafana, promtail, or blackbox configuration.
trigger: When the user asks to add/change/inspect anything in the AIAMSBS monitoring stack (prometheus targets, alloy sources, loki, grafana, promtail, blackbox) on the AIAMSBS host. NOT for general Linux admin or device inventory.
---

# AIAMSBS Stack — Config File Locations

The AIAMSBS monitoring stack lives at `$INSTALL_BASE_DIR/AIAMSBS/` (defaults to `$HOME/AIAMSBS/`). All service config files in `config/` are bind-mounted (read-only) into their respective containers, so the host file is the single source of truth — there is no separate "in-container" copy to edit.

| Service | Config file |
|---|---|
| Prometheus | `$INSTALL_BASE_DIR/AIAMSBS/config/prometheus.yml` |
| Alloy | `$INSTALL_BASE_DIR/AIAMSBS/config/alloy.yml` |
| Loki | `$INSTALL_BASE_DIR/AIAMSBS/config/loki.yml` |
| Promtail | `$INSTALL_BASE_DIR/AIAMSBS/config/promtail.yml` |
| Blackbox | `$INSTALL_BASE_DIR/AIAMSBS/config/blackbox.yml` |
| Grafana provisioning | `$INSTALL_BASE_DIR/AIAMSBS/config/grafana/provisioning/`
