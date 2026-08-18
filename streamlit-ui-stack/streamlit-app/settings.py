# settings.py
# Load backend URLs + customer name from environment variables.
#
# v1.0 customer stack sets these in docker-compose.yml. Defaults are
# the monitoring-network container names + host.docker.internal for
# host-side services, so a fresh deploy works without operator config.

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    customer_name: str
    admin_username: str
    hermes_url: str
    kb_url: str
    inventory_url: str
    loki_url: str
    ansible_runner_url: str
    grafana_url: str

    @property
    def backends(self) -> list[tuple[str, str]]:
        """List of (display_name, base_url) for the health page."""
        return [
            ("Hermes Dashboard", self.hermes_url),
            ("KB MCP", self.kb_url),
            ("Inventory MCP", self.inventory_url),
            ("Loki", self.loki_url),
            ("Ansible Runner", self.ansible_runner_url),
        ]


def load() -> Settings:
    return Settings(
        customer_name=os.environ.get("AIAMSBS_CUSTOMER_NAME", "dufour-int"),
        admin_username=os.environ.get("STREAMLIT_ADMIN_USERNAME", "admin"),
        hermes_url=os.environ.get("HERMES_URL", "http://host.docker.internal:9119"),
        kb_url=os.environ.get("KB_MCP_URL", "http://kb-mcp:8002"),
        inventory_url=os.environ.get("INVENTORY_MCP_URL", "http://inventory-mcp:8001"),
        loki_url=os.environ.get("LOKI_URL", "http://loki:3100"),
        ansible_runner_url=os.environ.get(
            "ANSIBLE_RUNNER_URL", "http://aiamsbs-ansible-runner:8000"
        ),
        grafana_url=os.environ.get("GRAFANA_URL", "http://grafana:3000"),
    )
