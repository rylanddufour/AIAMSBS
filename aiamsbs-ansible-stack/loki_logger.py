# loki_logger.py
# Shared log shipper for the AIAMSBS v1.0 customer Ansible stack.
#
# Pattern: append-only NDJSON to /ansible/logs/<stream>.log. The host's
# Grafana Alloy tails this directory (config/alloy.yml — loki.source.file
# block "aiamsbs_ansible") and pushes to Loki with stable labels:
#     job="aiamsbs-ansible"
#     source="aiamsbs_host"      (or customer host, same idea)
#     stream="<stream>"          (set per event via log_event(stream=...))
#
# Mounted into both aiamsbs-ansible (for in-container use by playbooks) and
# aiamsbs-ansible-runner (for runner-level events like auth, exec start/stop,
# exit codes). Both containers write to the SAME path on the host, so the
# alloy config needs only one loki.source.file block.
#
# No external dependencies. Single function, no class hierarchy. Designed
# to be imported or invoked via `python -m loki_logger <stream> <json>`.

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Where the NDJSON files land. Defaults match the bind mount in
# docker-compose.yml; override with LOKI_LOG_DIR for tests.
LOG_DIR = Path(os.environ.get("LOKI_LOG_DIR", "/ansible/logs"))


def log_event(stream: str, fields: dict) -> None:
    """Append one NDJSON event to /ansible/logs/<stream>.log.

    Args:
        stream: short identifier for this event source (e.g. "playbook",
            "runner"). Becomes the "stream" label on the Loki side.
        fields: arbitrary JSON-serializable dict. Merged with ts + stream.

    Raises:
        OSError: if the directory is unwritable. Callers can choose to
            swallow this so logging never breaks the calling code path.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.time(), "stream": stream, **fields}
    line = json.dumps(record, default=str)
    target = LOG_DIR / f"{stream}.log"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def log_line(stream: str, line: str, **extra) -> None:
    """Convenience wrapper for stdout-style line capture.

    Args:
        stream: stream identifier (e.g. "playbook_stdout").
        line: the raw line (no trailing newline expected; we add one).
        **extra: extra structured fields to attach to the event.
    """
    log_event(stream, {"line": line.rstrip("\n"), **extra})


# Allow: python loki_logger.py <stream> <json>
# Used by ansible-playbook's stdout callback or any shell pipeline that
# wants to ship a single event without importing the module.
def _cli() -> int:
    if len(sys.argv) < 3:
        print("usage: loki_logger.py <stream> <json-or-text>", file=sys.stderr)
        return 2
    stream = sys.argv[1]
    raw = sys.argv[2]
    try:
        fields = json.loads(raw)
        if not isinstance(fields, dict):
            fields = {"line": raw}
    except json.JSONDecodeError:
        fields = {"line": raw}
    log_event(stream, fields)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())