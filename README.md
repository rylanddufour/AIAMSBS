# AIAMSBS Project

## Goal
Self-hosted AI Agent platform for SMBs

## Host Architecture

![Host Architecture](diagrams/host-architecture.excalidraw)

## Service Ports

| Port | Service           | Note                     |
|------|------------------|--------------------------|
| :3000 | Grafana          | Web UI                   |
| :3100 | Loki            | Logs                     |
| :9090 | Prometheus     | Monitoring               |
| :9119 | Hermes Dashboard  | UI for Hermes Web        |
| :8787 | Hermes WebUI     | Local access only        |
| :9443 | Portainer       | Docker management        |

## README.md:9443 | Portainer       |