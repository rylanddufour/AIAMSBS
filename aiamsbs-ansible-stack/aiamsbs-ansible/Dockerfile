# aiamsbs-ansible — stock Ansible runtime container.
#
# v1.0 customer deployment (BACKLOG #64). Runs ansible-playbook invocations
# triggered by aiamsbs-ansible-runner via docker exec. Has NO exposed port
# and no docker socket — it is invoked, never invokes.
#
# Image philosophy: lean. ansible-core (NOT full ansible) + a small set of
# OEM collections (BACKLOG #59 covers full OEM coverage; keep this minimal
# for v1.0). openssh-client for SSH-based inventories. Python 3.12 slim.

FROM python:3.12-slim

# Avoid buffering — ansible-playbook output should stream line-by-line so
# the runner can ship it to Loki in real time.
ENV PYTHONUNBUFFERED=1 \
    ANSIBLE_FORCE_COLOR=0 \
    ANSIBLE_HOST_KEY_CHECKING=False \
    ANSIBLE_STDOUT_CALLBACK=default

# System packages: ssh client for inventory + minimal deps for ansible
# collections (cisco.ios needs basic crypto libs; community.general pulls
# in jmespath/etc).
RUN apt-get update && apt-get install -y --no-install-recommends \
        openssh-client \
        ca-certificates \
        procps \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Install ansible-core via pip (matches python:3.12-slim; avoids apt's older
# version). Pin a known-good version for reproducibility.
RUN pip install --no-cache-dir \
        ansible-core==2.16.3

# OEM collections. v1.0 starter set — keep this minimal. Add more only if
# a real customer playbook needs them.
#   cisco.ios          — Cisco IOS / IOS-XE device automation
#   ansible.windows    — Windows host automation (WinRM)
#   community.general  — Misc modules (apt, yum, service, file, etc.)
# Full OEM coverage is BACKLOG #59 territory.
RUN ansible-galaxy collection install \
        cisco.ios:==6.1.0 \
        ansible.windows:==2.2.0 \
        community.general:==8.4.0

# Working directory inside the container — keep it predictable so the
# runner can pass relative paths that resolve correctly.
WORKDIR /ansible

# Copy the loki_logger module so ansible can `python -c "import loki_logger"`
# from /ansible (mounted into /ansible/logs).
COPY loki_logger.py /ansible/loki_logger.py

# Entrypoint keeps the container alive indefinitely so the runner can
# docker exec into it. The runner does NOT manage ansible processes
# directly — it shells out to `docker exec` on this container.
COPY aiamsbs-ansible/entrypoint.sh /ansible/entrypoint.sh
RUN chmod +x /ansible/entrypoint.sh

# /ansible subpaths match the bind mounts in docker-compose.yml:
#   /ansible/playbooks/      playbook sources
#   /ansible/inventory/      inventory files
#   /ansible/artifacts/      facts cache + callback output
#   /ansible/logs/           loki_logger NDJSON output (alloy tails here)
RUN mkdir -p /ansible/playbooks/customer \
              /ansible/playbooks/generated \
              /ansible/inventory/static \
              /ansible/inventory/generated \
              /ansible/artifacts \
              /ansible/logs

# tini so PID 1 is sane if we ever override the entrypoint.
ENTRYPOINT ["/usr/bin/tini", "--", "/ansible/entrypoint.sh"]