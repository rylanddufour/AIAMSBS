# aiamsbs-ansible-runner — thin FastAPI bridge.
#
# v1.0 customer deployment (BACKLOG #64). The ONLY container in v1.0 with
# docker.sock access. Streamlit (Card 3) talks to this runner over HTTP,
# which then does `docker exec` into aiamsbs-ansible. This pattern
# eliminates the streamlit → docker.sock privilege escalation risk flagged
# in the #64 prompt.
#
# Endpoints:
#   GET  /health   — liveness check; verifies aiamsbs-ansible container
#                    is reachable via the docker socket.
#   POST /run      — execute a playbook. Body is HMAC-SHA256 signed with
#                    RUNNER_HMAC_SECRET. Streams NDJSON back as the
#                    playbook runs.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# System packages: tini for clean signal handling on PID 1.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Python deps. Pin known-good versions for reproducibility.
RUN pip install --no-cache-dir \
        fastapi==0.115.0 \
        'uvicorn[standard]==0.30.6' \
        docker==7.1.0 \
        httpx==0.27.2

WORKDIR /app

# Copy the loki_logger module so runner-level events (auth failures, exec
# start/stop, exit codes) ship to the same NDJSON directory as playbook
# stdout. The bind mount in docker-compose.yml maps the host's
# /home/ansible/AIAMSBS/aiamsbs-ansible-stack/logs to /ansible/logs inside
# THIS container too — same as in aiamsbs-ansible. Both containers see
# the same files, alloy reads them once.
COPY loki_logger.py /app/loki_logger.py
COPY main.py /app/main.py

EXPOSE 8000

# tini so PID 1 is sane (handles SIGTERM cleanly under docker stop).
ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]