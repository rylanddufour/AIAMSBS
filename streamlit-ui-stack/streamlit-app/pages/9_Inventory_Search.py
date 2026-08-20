# pages/9_Inventory_Search.py — AIAMSBS v1.0 customer Inventory Search.
#
# Card 6 of BACKLOG #64. Read view over the inventory-mcp backend.
# All access goes through `mcp_client` (MCP HTTP transport). No
# direct SQLite / shared FS access from this page.
#
# Spec adherence:
# - Auth gate + sidebar logout (consistent with other pages).
# - Top: search input, OS multi-select, role multi-select, vendor
#   multi-select, result count.
# - Submit -> inventory_list(query) -> results table.
# - Click hostname -> ?device_id=<id> drill-down: full attributes,
#   recent alerts (Loki), related KB entries, "Run playbook" link.
# - Loki events: {stream="inventory", event="search", user_id,
#   query_len, result_count} (no query body).
#
# Per BACKLOG #64 v1.0: inventory is READ-ONLY here. Add/edit happen
# via inventory-mcp agent or BACKLOG #14 flows. The page only ever
# calls list_devices / get_device / search_devices.

from __future__ import annotations

import json

import streamlit as st

from auth import require_auth, render_logout_button
from mcp_client import (
    MCPFormatError,
    MCPUnavailableError,
    MCPToolError,
    inventory_get,
    inventory_list,
    kb_search,
    loki_query,
)
from settings import load as load_settings

st.set_page_config(
    page_title="Inventory Search — AIAMSBS",
    page_icon="🖧",
    layout="wide",
)

if not require_auth():
    st.stop()

settings = load_settings()
user_id: int = int(st.session_state.get("user_id") or 0)
username: str = str(st.session_state.get("user") or "unknown")
if not user_id:
    st.error("Session lost its user_id — please log in again.")
    st.stop()

# ---- Loki logger (best-effort; never break the page on logging) ----
def _log(event: str, **fields) -> None:
    """Log an inventory page event. NEVER includes the query body."""
    try:
        from loki_logger import log_event
        log_event(
            "inventory",
            {
                "event": event,
                "page": "Inventory_Search",
                "user_id": user_id,
                "username": username,
                **{k: v for k, v in fields.items() if v is not None},
            },
        )
    except Exception:
        pass


st.title("🖧 Inventory Search")
st.caption(
    "Search and inspect devices in the inventory. Read-only in v1.0."
)


# ---- Search/filter row ----
# Discover available OS / role / vendor values from a quick unfiltered
# list so the multi-select options are real. Cached for 30s.
@st.cache_data(ttl=30, show_spinner=False)
def _device_universe() -> list[dict]:
    try:
        return inventory_list(query=None)
    except Exception:
        return []


_universe = _device_universe()
_os_options = sorted({(d.get("os") or "?") for d in _universe if d})
_role_options = sorted({(d.get("role") or "?") for d in _universe if d})
_vendor_options = sorted({(d.get("vendor") or "?") for d in _universe if d})

fcol1, fcol2, fcol3, fcol4 = st.columns([3, 2, 2, 2])
with fcol1:
    query = st.text_input(
        "Search",
        value=st.session_state.get("inv_search_query", ""),
        placeholder="hostname, IP, vendor, description…",
        key="inv_search_query_input",
    )
with fcol2:
    os_filter = st.multiselect(
        "OS",
        options=_os_options or ["?"],
        default=[],
        key="inv_os_filter",
    )
with fcol3:
    role_filter = st.multiselect(
        "Role",
        options=_role_options or ["?"],
        default=[],
        key="inv_role_filter",
    )
with fcol4:
    vendor_filter = st.multiselect(
        "Vendor",
        options=_vendor_options or ["?"],
        default=[],
        key="inv_vendor_filter",
    )

search_clicked = st.button(
    "Search", type="primary", use_container_width=False, key="inv_search_btn"
)


# ---- Helpers ----
_STATUS_COLORS = {
    "up": "🟢",
    "down": "🔴",
    "unknown": "⚪",
}


def _status_badge(status: str | None) -> str:
    s = (status or "unknown").lower()
    return f"{_STATUS_COLORS.get(s, '⚪')} {s}"


def _matches_filters(d: dict) -> bool:
    if os_filter and (d.get("os") or "?") not in os_filter:
        return False
    if role_filter and (d.get("role") or "?") not in role_filter:
        return False
    if vendor_filter and (d.get("vendor") or "?") not in vendor_filter:
        return False
    return True


# ---- Run the search ----
results: list[dict] = []
err_msg: str | None = None

# Auto-load "all devices" on first visit so the table isn't empty.
# The MCP backend already has data from prior nmap-discovery work.
auto_run = (
    query == ""
    and not search_clicked
    and not st.session_state.get("inv_first_load_done", False)
)


def _run_search(q: str) -> tuple[list[dict], str | None]:
    try:
        rows = inventory_list(query=q.strip() if q else None)
        return rows, None
    except MCPUnavailableError as e:
        return [], f"Inventory service unavailable: {e}"
    except MCPFormatError as e:
        return [], f"non-MCP response: {str(e)[:300]}"
    except MCPToolError as e:
        return [], f"Inventory tool error: {e}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


if auto_run or query or search_clicked:
    with st.spinner("Querying inventory…"):
        results, err_msg = _run_search(query)
    if err_msg:
        st.warning(f"⚠️ {err_msg}")
        if not auto_run:
            _log(
                "inventory_search_error",
                query_len=len(query),
                error=err_msg[:300],
            )
    st.session_state["inv_first_load_done"] = True
    _log(
        "search",
        query_len=len(query),
        result_count=len(results),
    )

# Apply client-side filters (server returns everything; we narrow).
filtered = [d for d in results if _matches_filters(d)]
st.caption(f"**{len(filtered)}** of {len(results)} device(s)")


# ---- Retry banner if service was unavailable ----
if err_msg and "unavailable" in err_msg.lower():
    if st.button("🔄 Retry", key="inv_retry"):
        st.rerun()


# ---- Drill-down ----
url_device_id = st.query_params.get("device_id", None)
drill: dict | None = None
if url_device_id:
    try:
        drill = inventory_get(url_device_id)
    except MCPUnavailableError:
        drill = None
        st.warning("Inventory service unavailable for drill-down. Retry later.")
    except MCPToolError:
        drill = None

if drill:
    st.markdown("---")
    hostname = drill.get("hostname") or drill.get("device_id", "(unknown)")
    st.markdown(f"### 🖧 {hostname}")
    cols = st.columns(4)
    cols[0].markdown(
        f"**IP:** `{drill.get('ip_address', '—')}`\n\n"
        f"**MAC:** `{drill.get('mac_address', '—')}`"
    )
    cols[1].markdown(
        f"**OS:** `{drill.get('os', '—')}`\n\n"
        f"**Vendor:** `{drill.get('vendor', '—')}`"
    )
    cols[2].markdown(
        f"**Role:** `{drill.get('role', '—')}`\n\n"
        f"**Type:** `{drill.get('device_type', '—')}`"
    )
    cols[3].markdown(
        f"**Status:** {_status_badge(drill.get('status'))}\n\n"
        f"**Last seen:** `{drill.get('last_seen', '—')}`"
    )

    # Full attributes (JSON formatted).
    with st.expander("All attributes (JSON)", expanded=False):
        st.code(json.dumps(drill, indent=2, default=str), language="json")

    # Recent alerts: pull from Loki. We search job=aiamsbs-anomaly OR
    # any log whose line mentions the hostname. Per the card's open
    # questions, this is "pull from Loki for v1.0".
    st.markdown("#### Recent alerts (Loki, last 24h)")
    try:
        hostname_q = (drill.get("hostname") or drill.get("device_id") or "").replace(
            '"', '\\"'
        )
        if hostname_q:
            loki_lines = loki_query(
                query=f'{{job=~"aiamsbs-anomaly|aiamsbs-ansible"}} |= "{hostname_q}"',
                limit=25,
            )
            if loki_lines:
                for entry in loki_lines[:10]:
                    body = entry.get("body") or entry.get("line")
                    ts = entry.get("ts", "?")
                    if isinstance(body, (dict, list)):
                        st.json(body)
                    else:
                        st.text(f"[{ts}] {body}")
            else:
                st.caption(
                    "_(no recent alerts found in Loki for this hostname)_"
                )
    except MCPUnavailableError:
        st.caption("_(Loki unavailable — recent alerts skipped)_")

    # Related KB entries: kb_search(query=hostname).
    st.markdown("#### Related KB entries")
    try:
        kb_rows = kb_search(
            query=(drill.get("hostname") or drill.get("device_id") or "").strip(),
            k=5,
        )
        if kb_rows:
            for r in kb_rows:
                rid = r.get("id")
                if st.button(
                    f"📄 {r.get('title', '(no title)')}",
                    key=f"inv_rel_kb_{rid}_{url_device_id}",
                ):
                    # Navigate to KB Search drilled into this entry.
                    st.query_params["entry_id"] = str(rid)
                    st.switch_page("pages/8_KB_Search.py")
        else:
            st.caption("_(no related KB entries)_")
    except (MCPUnavailableError, MCPToolError, MCPFormatError) as e:
        st.caption(f"_(KB lookup failed: {e})_")

    # Run playbook CTA.
    target_host = drill.get("hostname") or drill.get("device_id") or ""
    run_qs = f"?target={target_host}" if target_host else ""
    st.markdown(
        f"[▶ Run playbook on this device]"
        f"(/Run_Playbook{run_qs})"
    )
    _log("device_viewed", device_id=url_device_id)
    if st.button("← Back to results", key="inv_back_to_results"):
        del st.query_params["device_id"]
        st.rerun()


# ---- Results table ----
st.markdown("---")
if not filtered and not auto_run and (query or search_clicked):
    st.info("No devices match your search + filters.")
elif not filtered and auto_run:
    st.info("Inventory loaded but no devices match the current filters.")
elif not filtered:
    st.info("Click Search (or wait — first-load auto-runs) to load devices.")

for d in filtered:
    did = d.get("device_id") or d.get("hostname") or "?"
    cols = st.columns([4, 2, 3, 3, 1, 2])
    with cols[0]:
        if st.button(
            f"🖧 {d.get('hostname') or did}",
            key=f"inv_host_{did}",
            use_container_width=True,
        ):
            st.query_params["device_id"] = str(did)
            st.rerun()
    with cols[1]:
        st.code(d.get("ip_address", "—"), language=None)
    with cols[2]:
        st.caption(f"`{d.get('os', '—')} {d.get('os_version', '')}`".rstrip())
    with cols[3]:
        st.caption(f"`{d.get('role', '—')} · {d.get('vendor', '—')}`")
    with cols[4]:
        st.markdown(_status_badge(d.get("status")))
    with cols[5]:
        st.caption(f"`{d.get('last_seen', '—')}`")


# ---- Logout (moved from sidebar to page body) ----
st.markdown("---")
render_logout_button()