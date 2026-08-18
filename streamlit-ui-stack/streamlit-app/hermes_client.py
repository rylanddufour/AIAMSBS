# hermes_client.py
# Shared client utilities for AIAMSBS v1.0 customer Streamlit UI.
#
# Card 4 (BACKLOG #64) introduces this module. It owns:
#
#   * HMAC-SHA256 request signing for the aiamsbs-ansible-runner API.
#     The signature is computed over the raw request body (no canonicalization)
#     so what gets sent over the wire is exactly what gets hashed. The header
#     format is the same Stripe / GitHub pattern: "X-Signature: sha256=<hex>".
#
#   * Body redaction before persisting to playbook_run_events.payload.
#     The Card 4 acceptance criteria explicitly require that no password,
#     passphrase, or secret VALUE lands in the database. We always sign
#     the ORIGINAL body (the runner needs the real creds to exec ansible)
#     and only redact on the way INTO the DB.
#
#   * run_id lifecycle logging to loki_logger so the run can be traced
#     end-to-end via Loki even though Loki does NOT have a `run_id` label
#     (Card 2's alloy.yml only emits `job`/`source` labels from the path
#     matcher; run_id lives in the JSON payload).
#
# SECURITY:
#   - Every call to the runner MUST go through sign_request + post_signed
#     so the HMAC is never bypassed. If you find yourself wanting to call
#     httpx.post(runner_url + "/run", ...) directly, DON'T. Use post_signed.
#   - redact_secrets is best-effort: it scrubs every key in _SENSITIVE_KEYS
#     recursively in dicts and a simple regex pass over free-form strings.
#     It is NOT a defense against a determined attacker exfiltrating the
#     SQL store directly — it's the v1.0 "don't accidentally write
#     passwords to disk" guard.

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from typing import Any

import httpx

try:
    # loki_logger is a sibling symlink in the streamlit-app dir (Card 3
    # setup). Importing is best-effort; if the symlink isn't there the
    # log_run_event call silently no-ops.
    from loki_logger import log_event as _loki_log_event
except Exception:  # pragma: no cover - exercised only if symlink missing
    def _loki_log_event(stream, fields):  # type: ignore[no-redef]
        return None


# ---------------------------------------------------------------------------
# HMAC
# ---------------------------------------------------------------------------

SIG_PREFIX = "sha256="


def runner_secret() -> str:
    """Return the shared secret used to sign requests to aiamsbs-ansible-runner.

    MUST match the runner's RUNNER_HMAC_SECRET. Default
    "dev-secret-rotate-me" matches Card 2's runner compose default. In
    production, set RUNNER_HMAC_SECRET in the streamlit-ui-stack/
    docker-compose.yml environment to the operator's chosen secret.
    """
    s = os.environ.get("RUNNER_HMAC_SECRET", "").strip()
    return s or "dev-secret-rotate-me"


def sign_request(body: bytes, secret: str | None = None) -> str:
    """Compute the X-Signature header value for a request body.

    Returns the string "sha256=<hex>". The body MUST be the EXACT bytes
    that will be sent on the wire. For JSON, json.dumps(payload).encode().

    Args:
        body: raw bytes to sign. Use json.dumps(payload, separators=(",", ":")
            then .encode("utf-8") so the signing canonicalization matches
            whatever the runner reconstructs (it doesn't reconstruct; it
            just hashes request.body() verbatim). Consistency here only
            matters for the client to compute the same digest the server
            will.
        secret: shared secret. Defaults to runner_secret().

    Returns:
        The X-Signature header value, e.g. "sha256=ab12...".
    """
    if secret is None:
        secret = runner_secret()
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIG_PREFIX}{digest}"


def post_signed(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 300.0,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """POST a JSON body to `url` with the X-Signature header attached.

    This is the ONLY caller that should hit the runner. Centralizing the
    signing here means an HMAC bypass requires editing hermes_client.py,
    not silently calling httpx.post directly.

    Args:
        url: full URL, e.g. "http://aiamsbs-ansible-runner:8000/run".
        payload: dict that will be JSON-serialized. Use sort-free,
            canonical form (separators=(",", ":")) so debuggers can
            reproduce the signature.
        timeout: request timeout in seconds. The runner streams NDJSON so
            a 5-minute default covers long playbooks without hanging the
            thread.
        headers: optional extra headers. X-Signature is added
            automatically.

    Returns:
        httpx.Response. Callers stream .iter_lines() for NDJSON.

    Raises:
        httpx.HTTPStatusError: NOT raised here — callers decide whether to
            treat 401 as "auth_failed" and 5xx as a runner outage.
    """
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    h["X-Signature"] = sign_request(body)
    return httpx.post(url, content=body, headers=h, timeout=timeout)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

# Lower-case, plus a few explicit two-word phrases ("ssh_password",
# "become_password"). Match is on substring of the key, not whole word,
# so e.g. "user_password_hash" or "db_passphrase_kid" still get scrubbed.
# The trailing "pass" covers Ansible's short-form variables (Ansible
# docs intentionally recommend both `ansible_ssh_pass` and
# `ansible_ssh_password`; both must be scrubbed).
_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password",
    "passwd",
    "pass",
    "passphrase",
    "secret",
    "api_key",
    "apikey",
    "token",
    "ssh_password",
    "become_password",
    "private_key",
})

# Free-form regex: catches "password=foo" / "secret: bar" inside any string
# value. Conservative — only matches `key=value` / `key: value` patterns
# next to a word from _SENSITIVE_KEYS so we don't scrub innocuous strings.
_REDACT_IN_STRINGS = re.compile(
    r"(?i)(" + "|".join(sorted(_SENSITIVE_KEYS)) + r")\s*[=:]\s*([^\s,;}\]\"']+)"
)


def redact_secrets(value: Any) -> Any:
    """Recursively scrub secrets in-place-style from `value`.

    Behavior:
      - dict: walk every key; if the key matches _SENSITIVE_KEYS, replace
        the VALUE with the literal string "***REDACTED***". Recurse into
        the remaining keys.
      - list/tuple: recurse on each element.
      - str: run a regex pass that catches 'password=foo' style patterns
        and replaces the value half with '***REDACTED***'.
      - everything else: returned unchanged (int, float, bool, None).

    Returns the scrubbed structure (deep-copied; the caller's input is not
    mutated).
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if any(s in str(k).lower() for s in _SENSITIVE_KEYS):
                out[k] = "***REDACTED***"
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(v) for v in value)
    if isinstance(value, str):
        return _REDACT_IN_STRINGS.sub(r"\1=***REDACTED***", value)
    return value


def payload_is_clean(payload_json: str) -> bool:
    """Sanity check for the acceptance criterion: no row containing
    `password=` or `secret=` in the payload JSON.

    Implemented as a substring scan over the (already-redacted) row text.
    Use after INSERT to confirm the row's serialized text would not
    trigger a basic secret-leak audit. Returns True if neither substring
    appears.
    """
    low = payload_json.lower()
    return ("password=" not in low) and ("secret=" not in low)


# ---------------------------------------------------------------------------
# Run lifecycle helpers (DB + Loki)
# ---------------------------------------------------------------------------

def new_run_id() -> str:
    """Return a fresh uuid4 string. Use for playbook_runs.id and Loki tags."""
    return str(uuid.uuid4())


def short_run_id(run_id: str) -> str:
    """Return the first 8 hex chars of a run id. Used in tables to keep
    columns narrow without sacrificing uniqueness within a session."""
    return run_id.split("-", 1)[0] if "-" in run_id else run_id[:8]


def log_run_event(event_type: str, run_id: str, **fields: Any) -> None:
    """Append one streamlit.log event tagged with the run_id.

    Used by 3_Run_Playbook.py and 5_Run_Detail.py to leave an audit
    trail in Loki. Loki's `run_id` is in the JSON PAYLOAD (not a label),
    so Grafana queries must use pipe-filter `|= "run_id=<uuid>"`. See
    5_Run_Detail.py for the pre-built link.
    """
    try:
        _loki_log_event("streamlit", {
            "event": event_type,
            "run_id": run_id,
            "page": "Run_Playbook",
            **fields,
        })
    except Exception:
        pass  # logging must never break the run flow
