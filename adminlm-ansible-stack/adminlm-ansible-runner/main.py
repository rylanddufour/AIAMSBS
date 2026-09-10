# aiamsbs-ansible-runner FastAPI bridge.
#
# Card 2 of BACKLOG #64. Receives HMAC-signed POST /run requests, shells
# into the aiamsbs-ansible container via docker exec, streams ansible-playbook
# output back as NDJSON, and writes a parallel copy to /ansible/logs/*.log
# (consumed by the host's Grafana Alloy → Loki pipeline).
#
# Security:
#   - HMAC-SHA256 over the raw request body using RUNNER_HMAC_SECRET.
#     Header: X-Signature: sha256=<hex>. Mismatch → 401.
#   - docker.sock is mounted on THIS container ONLY. Streamlit (Card 3)
#     talks to the runner over the monitoring network and never touches
#     the socket — this isolates the docker daemon attack surface.

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
from typing import AsyncIterator, Optional

import docker
from docker.errors import APIError, NotFound
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

import loki_logger  # noqa: E402  (sibling on PYTHONPATH=/app)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANSIBLE_CONTAINER_NAME = os.environ.get("ANSIBLE_CONTAINER_NAME", "aiamsbs-ansible")
HMAC_SECRET = os.environ.get("RUNNER_HMAC_SECRET", "dev-secret-rotate-me")
LISTEN_PORT = int(os.environ.get("RUNNER_PORT", "8000"))

# /ansible is bind-mounted from the host. loki_logger writes here; the
# host's alloy tails the same path. See config/alloy.yml.
LOG_DIR_HOST = os.environ.get("LOG_DIR_HOST", "/ansible/logs")

# How often we flush a partial line to the client if no newline has arrived
# yet. Keeps the NDJSON stream feeling live without spamming tiny fragments.
STREAM_FLUSH_INTERVAL_S = float(os.environ.get("STREAM_FLUSH_INTERVAL_S", "0.5"))

# ---------------------------------------------------------------------------
# HMAC verification
# ---------------------------------------------------------------------------

SIG_PREFIX = "sha256="


def _expected_signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _verify_hmac(body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 compare. False on any malformed input."""
    if not signature_header or not signature_header.startswith(SIG_PREFIX):
        return False
    provided = signature_header[len(SIG_PREFIX):].strip()
    expected = _expected_signature(body, HMAC_SECRET)
    # hmac.compare_digest returns False on length mismatch without raising.
    return hmac.compare_digest(provided, expected)


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------

_docker: Optional[docker.DockerClient] = None


def docker_client() -> docker.DockerClient:
    """Lazy-init the docker client. DOCKER_HOST defaults to
    unix:///var/run/docker.sock from the bind mount."""
    global _docker
    if _docker is None:
        _docker = docker.DockerClient(base_url=os.environ.get(
            "DOCKER_HOST", "unix:///var/run/docker.sock"))
    return _docker


def ansible_container():
    try:
        return docker_client().containers.get(ANSIBLE_CONTAINER_NAME)
    except NotFound:
        loki_logger.log_event("runner", {
            "event": "ansible_container_missing",
            "name": ANSIBLE_CONTAINER_NAME,
        })
        raise HTTPException(
            status_code=503,
            detail=f"ansible container '{ANSIBLE_CONTAINER_NAME}' not found")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="aiamsbs-ansible-runner", version="0.1.0")


@app.get("/health")
async def health():
    """Liveness + reachability check.

    Returns 200 with the list of containers we expect to find via the
    docker socket. Used by docker-compose healthchecks and by Card 3
    (Streamlit) for pre-flight validation.

    `ok` is true iff the ansible container exists AND is in the `running`
    state. `docker stop` leaves the container around (state=`exited`),
    which previously returned 200 because `.id` doesn't raise on a
    stopped container — false-positive on a half-broken install.
    """
    containers: list[str] = []
    ok = False
    try:
        c = ansible_container()
        # .status can be "running", "exited", "paused", etc. Touch .id
        # first to force the API call so a NotFound is raised if the
        # container is gone, THEN check status.
        _ = c.id
        if c.status == "running":
            containers.append(ANSIBLE_CONTAINER_NAME)
            ok = True
        else:
            containers.append(f"{ANSIBLE_CONTAINER_NAME} ({c.status})")
    except HTTPException:
        ok = False
    except APIError as exc:
        loki_logger.log_event("runner", {"event": "docker_api_error", "error": str(exc)})
        ok = False

    body = {
        "status": "ok" if ok else "degraded",
        "containers": containers,
    }
    return JSONResponse(body, status_code=200 if ok else 503)


@app.post("/run")
async def run_playbook(request: Request):
    """Execute ansible-playbook inside the aiamsbs-ansible container.

    Body (JSON, raw bytes signed by HMAC):
        {
            "inline_inventory": "host01 ansible_host=10.0.0.1 ansible_user=opc ansible_connection=ssh,host02 ...,",
            # ^^^ Card 8: REPLACES the legacy `inventory` file-path field.
            # Format: comma-separated host fragments, NO outer shell quotes,
            # trailing comma. Ansible parses the trailing comma as the
            # "this is a list, not a filename" disambiguator. Because we
            # pass the value as a single argv item (no shell), outer shell
            # quotes would be parsed as part of the first host's name.
            "playbook":        "playbooks/generated/hello.yml",   # required, str
            "extra_vars":      {"key": "value"},                   # optional, dict
            "check":           false,                              # optional, bool
            "diff":            false                               # optional, bool
        }

    Returns NDJSON stream; one JSON object per line:
        {"ts": ..., "stream": "exec", "line": "PLAY [Gather Facts] ..."}
        ...
        {"ts": ..., "stream": "exec", "event": "exit", "exit_code": 0}
    """
    # We need the raw bytes for HMAC verification AND the parsed JSON for
    # arg construction. FastAPI's dependency-injected `Body()` would
    # consume the body before we can hash it, so read the raw stream.
    body_bytes = await request.body()

    signature = request.headers.get("X-Signature")
    if not _verify_hmac(body_bytes, signature):
        loki_logger.log_event("runner", {
            "event": "auth_failure",
            "remote": request.client.host if request.client else None,
            "path": "/run",
        })
        raise HTTPException(status_code=401, detail="invalid or missing X-Signature")

    try:
        payload = json.loads(body_bytes or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="request body is not valid JSON")

    # Card 8: inline_inventory is the live-built string from the Streamlit
    # UI, sourced from inventory-mcp. Format: comma-separated host
    # fragments, NO outer shell quotes, trailing comma. The trailing comma
    # is the "this is a list, not a filename" disambiguator that Ansible
    # requires. We pass the value as a single argv item to ansible-playbook
    # via docker exec (no shell in between), so shell-quote-wrapping the
    # value would result in the literal quote being parsed as part of the
    # first host's name.
    inline_inventory = payload.get("inline_inventory")
    playbook = payload.get("playbook")
    if not inline_inventory or not playbook:
        raise HTTPException(
            status_code=400,
            detail="'inline_inventory' and 'playbook' are required")
    if not isinstance(inline_inventory, str):
        raise HTTPException(
            status_code=400,
            detail="'inline_inventory' must be a string")
    # Defence-in-depth: reject any character that could break out of the
    # inventory parsing or inject a flag. Allow only safe hostname chars,
    # whitespace, commas, equals, dots, underscores, and colons (for IPv6).
    # Explicitly forbid quotes (we use argv, not shell).
    if not re.fullmatch(r'[\w\.\s,=\-:/]+', inline_inventory):
        raise HTTPException(
            status_code=400,
            detail="'inline_inventory' contains disallowed characters")
    if len(inline_inventory) > 8192:
        raise HTTPException(
            status_code=400,
            detail="'inline_inventory' exceeds 8KB cap")

    extra_vars = payload.get("extra_vars") or {}
    use_check = bool(payload.get("check", False))
    use_diff = bool(payload.get("diff", False))

    # Build the ansible-playbook command. We intentionally do NOT use a
    # shell — pass argv directly via docker exec's cmd=[...]. This avoids
    # any chance of injection through inventory/playbook paths and keeps
    # the args predictable.
    cmd = ["ansible-playbook", "-i", inline_inventory, playbook]
    if extra_vars:
        cmd.extend(["--extra-vars", json.dumps(extra_vars)])
    if use_check:
        cmd.append("--check")
    if use_diff:
        cmd.append("--diff")

    container = ansible_container()

    loki_logger.log_event("runner", {
        "event": "exec_start",
        "container": ANSIBLE_CONTAINER_NAME,
        "inline_inventory_len": len(inline_inventory),
        "playbook": playbook,
        "check": use_check,
        "diff": use_diff,
    })

    return StreamingResponse(
        _stream_exec(container, cmd),
        media_type="application/x-ndjson",
    )


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

async def _stream_exec(container, cmd: list[str]) -> AsyncIterator[bytes]:
    """Run `cmd` inside `container` via docker exec, yield NDJSON lines.

    The docker SDK's exec_run gives us (exit_code, output) where output is
    a single bytes blob — not a true stream. For real streaming we'd use
    socket_mode=True (demux=True) and read frames. We do that so the
    client gets playbook output in real time as it runs.
    """
    api_client = docker_client().api
    exec_id = api_client.exec_create(
        container=container.id,
        cmd=cmd,
        stdout=True,
        stderr=True,
        workdir="/ansible",
    )["Id"]

    # stream=True + demux=True yields (stdout_chunk, stderr_chunk) tuples.
    # Either side may be None for a given chunk.
    sock = api_client.exec_start(exec_id, stream=True, demux=True)

    stdout_buf = bytearray()
    stderr_buf = bytearray()
    started = time.time()

    def _drain(buf: bytearray, stream: str) -> list[bytes]:
        """Pull complete lines out of buf; return them as NDJSON bytes."""
        out: list[bytes] = []
        while True:
            nl = buf.find(b"\n")
            if nl < 0:
                break
            line = bytes(buf[:nl]).decode("utf-8", errors="replace")
            del buf[:nl + 1]
            obj = {"ts": time.time(), "stream": stream, "line": line}
            out.append((json.dumps(obj) + "\n").encode("utf-8"))
        return out

    try:
        for chunk in sock:
            stdout_chunk, stderr_chunk = chunk
            if stdout_chunk:
                stdout_buf.extend(stdout_chunk)
                for line in _drain(stdout_buf, "exec_stdout"):
                    yield line
            if stderr_chunk:
                stderr_buf.extend(stderr_chunk)
                for line in _drain(stderr_buf, "exec_stderr"):
                    yield line
    except APIError as exc:
        loki_logger.log_event("runner", {
            "event": "exec_stream_error",
            "error": str(exc),
            "exec_id": exec_id,
        })
        err = {"ts": time.time(), "stream": "exec",
               "event": "stream_error", "error": str(exc)}
        yield (json.dumps(err) + "\n").encode("utf-8")

    # Flush any trailing partial lines (playbooks don't always end on \n).
    if stdout_buf:
        line = bytes(stdout_buf).decode("utf-8", errors="replace")
        obj = {"ts": time.time(), "stream": "exec_stdout", "line": line}
        yield (json.dumps(obj) + "\n").encode("utf-8")
        stdout_buf.clear()
    if stderr_buf:
        line = bytes(stderr_buf).decode("utf-8", errors="replace")
        obj = {"ts": time.time(), "stream": "exec_stderr", "line": line}
        yield (json.dumps(obj) + "\n").encode("utf-8")
        stderr_buf.clear()

    # Inspect the exec instance to get the actual exit code. exec_run's
    # output isn't enough — we used streaming mode.
    info = api_client.exec_inspect(exec_id)
    exit_code = int(info.get("ExitCode", 0))
    duration = round(time.time() - started, 3)

    final = {
        "ts": time.time(),
        "stream": "exec",
        "event": "exit",
        "exit_code": exit_code,
        "duration_s": duration,
    }
    yield (json.dumps(final) + "\n").encode("utf-8")

    loki_logger.log_event("runner", {
        "event": "exec_done",
        "exit_code": exit_code,
        "duration_s": duration,
        "playbook": cmd[-1] if cmd else "",
    })