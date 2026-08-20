# mcp_client.py
# AIAMSBS v1.0 customer Streamlit UI — MCP HTTP transport client.
#
# Card 6 of BACKLOG #64. The streamlit-ui container talks to kb-mcp
# (:8002) and inventory-mcp (:8001) exclusively through the MCP
# **Streamable-HTTP transport** (POST /mcp, JSON-RPC 2.0, SSE
# response). It does NOT mount the kb-mcp / inventory-mcp SQLite
# databases and it does NOT call them on their /health or other
# sidecar endpoints — only /mcp. This is the BACKLOG #30 / #14 rule
# that the Streamlit UI surface is enforced to honor so the underlying
# backends can be replaced without rewriting the UI.
#
# Architecture:
#
#   streamlit-ui → KB_MCP_URL=http://kb-mcp:8002/mcp  (Streamable HTTP)
#   streamlit-ui → INVENTORY_MCP_URL=http://inventory-mcp:8001/mcp  (same)
#   streamlit-ui → LOKI_URL=http://loki:3100  (REST, no session)
#
# Each MCP server uses the FastMCP "Streamable-HTTP" transport. That
# requires:
#   1. POST /mcp with `initialize` first → response carries an
#      `Mcp-Session-Id` header and a Server-Sent Events body. Keep
#      that session id and reuse it for every subsequent tools/call.
#   2. All requests must send Accept: application/json,text/event-stream
#      and Content-Type: application/json. SSE is the wire format on the
#      response.
#   3. Each response is a single `event: message\ndata: <json>\n\n` SSE
#      frame; we extract the JSON payload from the `data:` line.
#
# We keep ONE session per MCP server per Streamlit worker process
# (`_stcore` is multi-threaded but each page-script runs in-process for
# a session; v1.0 is single-user so this is fine). If a tools/call
# fails with "session invalid", we silently re-initialize.
#
# Errors:
# - If the server returns a non-MCP-shaped body (e.g. 404 HTML), we
#   raise `MCPFormatError` so callers can render a friendly message.
# - If the server is unreachable (connection refused / DNS / timeout),
#   we raise `MCPUnavailableError` so callers can show a Retry button.
#
# Privacy:
# - KB and Inventory helpers NEVER log query bodies here. Logging is
#   the page's job (via loki_logger.log_event); page code only ships
#   metadata (user_id, query_len, result_count) — never the query text.

from __future__ import annotations

import json
import os
import threading
from typing import Any

import httpx

# ----------------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------------


class MCPUnavailableError(RuntimeError):
    """MCP server is unreachable (network error, timeout, DNS)."""


class MCPFormatError(RuntimeError):
    """MCP server returned a body that is not an MCP JSON-RPC response."""


class MCPToolError(RuntimeError):
    """MCP server returned isError=true on a tools/call."""

    def __init__(self, message: str, payload: dict | None = None) -> None:
        super().__init__(message)
        self.payload = payload or {}


# ----------------------------------------------------------------------------
# Low-level MCP HTTP transport
# ----------------------------------------------------------------------------

# Cap a single MCP HTTP call at 15s; the backends are local on the
# monitoring Docker network, so anything slower usually means they
# are down and we want a fast failure to render Retry UI.
_HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# Sessions are guarded by a lock so the first concurrent page render
# from one Streamlit process can't race with another.
_init_locks: dict[str, threading.Lock] = {}
_session_ids: dict[str, str] = {}
_locks_guard = threading.Lock()


def _lock_for(base_url: str) -> threading.Lock:
    with _locks_guard:
        lk = _init_locks.get(base_url)
        if lk is None:
            lk = threading.Lock()
            _init_locks[base_url] = lk
        return lk


def _parse_sse_data(text: str) -> dict:
    """Pull the JSON payload out of a single SSE message frame.

    FastMCP's Streamable-HTTP transport returns frames like:
        event: message
        data: {"jsonrpc":"2.0",...}

    Some debug endpoints return a plain JSON document — that's also
    tolerated but flagged as MCPFormatError if it doesn't have
    `jsonrpc` (it's not really MCP).

    Raises MCPFormatError if the body is empty, not JSON, or missing
    the jsonrpc field. The page must surface the *whole* response
    body in that case (per BACKLOG #14).
    """
    if not text or not text.strip():
        raise MCPFormatError("empty response body")
    # Pick out the data: payload if SSE, else treat whole text as JSON.
    data_line: str | None = None
    for line in text.splitlines():
        if line.startswith("data:"):
            data_line = line[len("data:") :].strip()
            break
    raw = data_line if data_line is not None else text
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise MCPFormatError(
            f"non-JSON MCP response: {e}; body[:300]={text[:300]!r}"
        ) from e
    if not isinstance(obj, dict) or "jsonrpc" not in obj:
        raise MCPFormatError(
            f"response missing jsonrpc field; body[:300]={text[:300]!r}"
        )
    return obj


def _ensure_session(client: httpx.Client, base_url: str) -> str:
    """Initialize an MCP session if we don't have one yet.

    Returns the Mcp-Session-Id to attach to subsequent POSTs.
    """
    sid = _session_ids.get(base_url)
    if sid:
        return sid
    lk = _lock_for(base_url)
    with lk:
        sid = _session_ids.get(base_url)
        if sid:
            return sid
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "aiamsbs-streamlit-ui", "version": "1.0"},
            },
        }
        try:
            r = client.post(
                base_url,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json=init_payload,
                timeout=_HTTP_TIMEOUT,
            )
        except httpx.HTTPError as e:
            raise MCPUnavailableError(
                f"initialize {base_url} failed: {type(e).__name__}: {e}"
            ) from e
        if r.status_code >= 500:
            raise MCPUnavailableError(
                f"initialize {base_url} returned HTTP {r.status_code}"
            )
        sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
        if not sid:
            raise MCPFormatError(
                f"initialize {base_url} returned no Mcp-Session-Id header; "
                f"status={r.status_code} body[:300]={r.text[:300]!r}"
            )
        _session_ids[base_url] = sid
        return sid


def _drop_session(base_url: str) -> None:
    """Forget the cached session so the next call re-initializes."""
    _session_ids.pop(base_url, None)


def _tools_call(
    base_url: str, tool_name: str, arguments: dict | None = None
) -> Any:
    """Call an MCP tool and return its decoded result payload.

    Returns the unwrapped value (the `result` field from the JSON-RPC
    envelope), which for FastMCP wrap_result tools is either a dict
    (when the tool returns an object) or a list (when it returns a
    list). The caller normalises further if needed.

    Raises:
        MCPUnavailableError: connection / timeout issues
        MCPFormatError: server returned a non-JSON-RPC body
        MCPToolError: server returned isError=true on the tool call
    """
    arguments = arguments or {}
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        # Try the call; if the server has rotated its session, fall
        # through to a re-init + retry once.
        last_exc: Exception | None = None
        for attempt in (1, 2):
            sid = _ensure_session(client, base_url)
            payload = {
                "jsonrpc": "2.0",
                "id": 100 + attempt,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            try:
                r = client.post(
                    base_url,
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                        "Mcp-Session-Id": sid,
                    },
                    json=payload,
                    timeout=_HTTP_TIMEOUT,
                )
            except httpx.HTTPError as e:
                raise MCPUnavailableError(
                    f"POST {base_url} {tool_name} failed: "
                    f"{type(e).__name__}: {e}"
                ) from e

            if r.status_code == 404 and attempt == 1:
                # Stale session — server forgot our session id.
                _drop_session(base_url)
                last_exc = MCPUnavailableError(
                    f"{base_url} returned 404 (stale session?), retrying"
                )
                continue
            if r.status_code == 400 and "session" in r.text.lower() and attempt == 1:
                _drop_session(base_url)
                last_exc = MCPUnavailableError(
                    f"{base_url} said session invalid; retrying"
                )
                continue
            if r.status_code >= 500:
                raise MCPUnavailableError(
                    f"{base_url} {tool_name} returned HTTP {r.status_code}"
                )
            if r.status_code >= 400:
                raise MCPFormatError(
                    f"{base_url} {tool_name} returned HTTP {r.status_code}; "
                    f"body[:500]={r.text[:500]!r}"
                )
            try:
                obj = _parse_sse_data(r.text)
            except MCPFormatError:
                raise
            err = obj.get("error")
            if err:
                raise MCPToolError(
                    f"{base_url} tool={tool_name} error: {err.get('message')}",
                    payload=err if isinstance(err, dict) else {"value": err},
                )
            res = obj.get("result")
            if not isinstance(res, dict):
                raise MCPFormatError(
                    f"{base_url} {tool_name} result is not a JSON object; "
                    f"body[:500]={r.text[:500]!r}"
                )
            if res.get("isError") is True:
                raise MCPToolError(
                    f"{base_url} tool={tool_name} returned isError=true",
                    payload=res,
                )
            # FastMCP exposes the actual payload under
            # structuredContent (preferred) OR `content[0].text` (legacy).
            sc = res.get("structuredContent")
            if isinstance(sc, dict) and "result" in sc:
                return sc["result"]
            if isinstance(sc, list):
                return sc
            content = res.get("content")
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict) and isinstance(first.get("text"), str):
                    try:
                        decoded = json.loads(first["text"])
                    except json.JSONDecodeError:
                        return first["text"]
                    return decoded
            # Return the raw result so the caller still has something
            # serialisable to show.
            return res
        # second attempt also failed
        if last_exc:
            raise last_exc
        raise MCPFormatError(f"{base_url} {tool_name} failed without a body")


# ----------------------------------------------------------------------------
# KB MCP wrapper
# ----------------------------------------------------------------------------


def _kb_base_url() -> str:
    return os.environ.get(
        "KB_MCP_URL", "http://kb-mcp:8002"
    ).rstrip("/") + "/mcp"


def _inventory_base_url() -> str:
    return os.environ.get(
        "INVENTORY_MCP_URL", "http://inventory-mcp:8001"
    ).rstrip("/") + "/mcp"


def kb_search(query: str, k: int = 10) -> list[dict]:
    """Free-text search across kb_entries. Returns a list of dicts.

    Each result has at least: id, title, content, status,
    trust_level_at_creation, entry_type, tags, created_at, updated_at,
    snippet, rank. The KB wraps content as a single string with a
    FTS5 snippet — the full original content lives on entry.content.
    """
    res = _tools_call(_kb_base_url(), "kb_search", {"query": query, "limit": k})
    # FastMCP returns a list of dicts; tolerate list-shaped responses.
    if isinstance(res, list):
        return res
    if isinstance(res, dict) and "result" in res and isinstance(res["result"], list):
        return res["result"]
    return []


def kb_get(entry_id: int | str) -> dict | None:
    """Fetch a single KB entry by id.

    kb-mcp does NOT expose a kb_get tool directly. We approximate it
    by calling kb_search with a high limit and filtering for the id;
    because the search returns full rows (with content), this gives the
    page the data it needs for drill-down without depending on
    internals. Returns None if no entry matches.

    Note: this is NOT a substitute for kb_list filtering — but it
    matches the page behaviour ("click a row → see full content").
    """
    target = str(entry_id).strip()
    if not target:
        return None
    # Try a small id-targeted query first. FTS5 won't index integers,
    # so we look across a broad sample and filter ourselves.
    rows = kb_search(query=target, k=50)
    for row in rows:
        if str(row.get("id")) == target:
            return row
    # Fall back: empty dataset so far; try a generic search to see if
    # the entry exists at all (id may show up as content substring).
    return None


def kb_add(
    title: str,
    content: str,
    entry_type: str = "runbook",
    tags: list[str] | None = None,
    created_by: str = "customer",
) -> dict:
    """Add a new KB entry. Returns the new row.

    The kb-mcp enforces title != '' at THREE layers (schema CHECK,
    function validation, web UI). Passing a blank title is a
    programming error and will fail at the DB layer — surface it to the
    user as "Title is required".

    `created_by` defaults to "customer" because v1.0 streamlit-ui's
    admin user IS the customer on a private deployment. The server
    uses created_by to set the initial status (customer → "approved",
    agent → "pending") and trust level (3 vs 0). We do NOT expose a
    `status` arg here because the server doesn't accept one — to
    change status after add, call kb_update.
    """
    if not title or not title.strip():
        raise MCPToolError("title is required and must be a non-empty string")
    args: dict[str, Any] = {
        "title": title.strip(),
        "content": content,
        "entry_type": entry_type,
        "tags": tags or [],
        "created_by": created_by,
    }
    res = _tools_call(_kb_base_url(), "kb_add", args)
    if isinstance(res, dict):
        return res
    # FastMCP sometimes wraps a single-row tool call in a list.
    if isinstance(res, list) and res and isinstance(res[0], dict):
        return res[0]
    return {"raw": res}


# ----------------------------------------------------------------------------
# Inventory MCP wrapper
# ----------------------------------------------------------------------------


def inventory_list(
    device_type: str = "",
    limit: int = 500,
    query: str | None = None,
) -> list[dict]:
    """List devices.

    The card spec calls this `inventory_list(query)`. We accept a free
    text `query` and route it through `search_devices` for a sensible
    match; if `query` is None or empty we use `list_devices` to keep
    behaviour identical to the spec. `device_type` is forwarded either
    way as an additional exact filter.
    """
    base = _inventory_base_url()
    if query and query.strip():
        res = _tools_call(
            base,
            "search_devices",
            {"query": query.strip(), "device_type": device_type, "limit": limit},
        )
    else:
        res = _tools_call(
            base, "list_devices", {"device_type": device_type, "limit": limit}
        )
    if isinstance(res, list):
        return res
    if isinstance(res, dict) and "result" in res and isinstance(res["result"], list):
        return res["result"]
    return []


def inventory_get(device_id: str) -> dict | None:
    """Fetch a single device record by device_id.

    Returns None if the device does not exist (inventory-mcp returns
    an error-shaped result for unknown ids; we surface it as None so
    the page can render a friendly "not found").
    """
    try:
        res = _tools_call(_inventory_base_url(), "get_device", {"device_id": device_id})
    except MCPToolError as e:
        # Common: "device not found" comes back as isError=true
        # with a message. We treat it as None rather than crashing.
        payload = e.payload or {}
        content = payload.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and isinstance(first.get("text"), str):
                # Look for 'not found' / 'no such' in the error text.
                if any(
                    needle in first["text"].lower()
                    for needle in ("not found", "no such", "does not exist")
                ):
                    return None
        raise
    if isinstance(res, dict):
        return res
    return None


# ----------------------------------------------------------------------------
# Loki query helper (for the Inventory drill-down's "Recent alerts")
# ----------------------------------------------------------------------------


def _loki_base_url() -> str:
    return os.environ.get("LOKI_URL", "http://loki:3100").rstrip("/")


def loki_query(
    query: str, start_ns: int | None = None, end_ns: int | None = None, limit: int = 50
) -> list[dict]:
    """Run a Loki query_range and return decoded log lines.

    Returns a list of {"ts": <str>, "labels": {...}, "line": <str>}.
    Each entry has the parsed-out JSON body if the line was NDJSON
    JSON, otherwise the raw line.

    Notes:
    - Loki URL is configurable via LOKI_URL env var (default
      http://loki:3100). No session management is needed (it's plain
      REST).
    - 5s timeout because we're querying a local Loki container that
      backs the same dashboard the operator uses.
    """
    base = _loki_base_url()
    if end_ns is None:
        import time as _t
        end_ns = int(_t.time()) * 1_000_000_000
    if start_ns is None:
        start_ns = end_ns - 24 * 60 * 60 * 1_000_000_000  # last 24h

    with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
        try:
            r = client.get(
                f"{base}/loki/api/v1/query_range",
                params={
                    "query": query,
                    "start": start_ns,
                    "end": end_ns,
                    "limit": limit,
                    "direction": "backward",
                },
            )
        except httpx.HTTPError as e:
            raise MCPUnavailableError(
                f"Loki query failed: {type(e).__name__}: {e}"
            ) from e

    if r.status_code >= 400:
        # Treat 4xx/5xx as "no results" so the page degrades gracefully
        # rather than crashing on a transient Loki issue.
        return []
    try:
        data = r.json()
    except json.JSONDecodeError:
        return []
    streams = (data.get("data") or {}).get("result") or []
    out: list[dict] = []
    for s in streams:
        labels = s.get("stream") or {}
        for ts, line in s.get("values") or []:
            body: Any = line
            try:
                body = json.loads(line)
            except json.JSONDecodeError:
                pass
            out.append({"ts": ts, "labels": labels, "line": line, "body": body})
    return out
