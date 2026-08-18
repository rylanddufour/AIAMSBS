# AIAMSBS v1.0 customer Streamlit UI shell (BACKLOG #64, Card 3).
#
# - python:3.12-slim keeps the image small (~150MB before deps).
# - We install only what streamlit + auth + httpx health checks need.
#   The ansible runner + docker SDK live in aiamsbs-ansible-stack (Card 2)
#   so this image never touches the docker socket.
# - WORKDIR is /app/streamlit-app because we bind-mount ./streamlit-app
#   there at runtime. The bind-mount contains Home.py + pages/ + auth.py
#   + db.py + settings.py + loki_logger.py (symlink to Card 2's module).
#
# No apt-get cache cleanup needed beyond the default slim layout; the
# python:3.12-slim image is already minimal.

FROM python:3.12-slim

WORKDIR /app/streamlit-app

# Install OS deps that pip + bcrypt + httpx want. --no-install-recommends
# keeps the layer small; rm -rf /var/lib/apt/lists/* drops the apt cache.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching. Streamlit >=1.39 (per card
# spec) is the floor; the upper bound <2 keeps us on 1.x until 2.x stabilizes.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Streamlit config is bind-mounted at runtime via ./streamlit-ui-stack/.streamlit
# so source code changes don't require a rebuild. But the config dir layout
# inside the image is fine as a default — the bind mount overlays it.

# Health check from the orchestrator's verify list: curl /_stcore/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8501/_stcore/health || exit 1

EXPOSE 8501

# Entrypoint args mirror the streamlit CLI flags the card specifies. Headless
# mode disables the "is this script still running?" browser auto-open
# behavior, which we don't need in a container.
ENTRYPOINT ["streamlit", "run", "Home.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0", \
            "--server.headless=true", \
            "--server.runOnSave=true", \
            "--browser.gatherUsageStats=false"]
