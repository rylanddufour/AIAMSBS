#!/bin/sh
# entrypoint.sh — keep the adminlm-ansible container alive indefinitely
# so the adminlm-ansible-runner can `docker exec` ansible-playbook into it.
#
# Why not CMD ["ansible-playbook"]? Because the runner chooses the inventory
# and playbook per request — there is no single "entrypoint command" that
# makes sense. The runner runs something like:
#
#   docker exec adminlm-ansible ansible-playbook -i inventory/... playbooks/...
#
# while we tail the output and ship to NDJSON.

set -eu

# Ensure the expected subdirectories exist (in case the bind mount was
# empty on first boot).
mkdir -p /ansible/playbooks/customer \
         /ansible/playbooks/generated \
         /ansible/inventory/static \
         /ansible/inventory/generated \
         /ansible/artifacts \
         /ansible/logs

# Print a single banner line so the alloy container log shows a clean
# startup signal. This becomes the first Loki entry tagged job=adminlm-ansible
# on container boot.
python -c "import loki_logger; loki_logger.log_event('container', {'event': 'adminlm-ansible ready'})" \
    || echo "[adminlm-ansible] loki_logger init failed (non-fatal)"

# Sleep forever so `docker exec` works. SIGTERM from docker stop will
# propagate cleanly through tini.
exec sleep infinity