# agent-exporter — Prometheus exporter for AIAMSBS Hermes agent activity.
# BACKLOG #29 (research/agent-activity-dashboard-2026-07-01.md).
#
# Single-file Python script (no shell, no build step beyond pip).
# Mounts ~/.hermes read-only at the same path; reads SQLite + cron/jobs.json
# and exposes /metrics + /healthz on port 9117.

FROM python:3.12-slim

# Labels match the AIAMSBS style used across inventory-stack/ and kb-stack/.
LABEL org.opencontainers.image.title="aiamsbs-agent-exporter" \
      org.opencontainers.image.description="Hermes agent activity Prometheus exporter (BACKLOG #29)" \
      org.opencontainers.image.source="https://github.com/rylanddufour/AIAMSBS" \
      org.opencontainers.image.licenses="MIT"

# Don't write .pyc, don't buffer stdout/stderr.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Only one runtime dep. Pin minor for reproducibility.
COPY agent_exporter.py /app/agent_exporter.py
RUN pip install --no-cache-dir "prometheus_client>=0.20,<1.0"

# Hermes data is read-only; the container must never write to it.
# Compose mounts ~/.hermes:/home/ansible/.hermes:ro so the in-container path
# matches the on-host path (matches alloy's mount convention).
USER nobody:nogroup

EXPOSE 9117

# Scrape interval 15s is the prom-side default; env knob lets ops tune it.
ENV AGENT_EXPORTER_PORT=9117 \
    AGENT_EXPORTER_INTERVAL=15 \
    HERMES_HOME=/home/ansible/.hermes

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9117/healthz', timeout=3).status==200 else 1)"

ENTRYPOINT ["python", "/app/agent_exporter.py"]
