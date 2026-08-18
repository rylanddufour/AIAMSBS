# pages/1_Settings.py — read-only settings + health overview.
#
# Card 3 scope: display-only. Writes (changing values, regenerating
# session secrets) land in Card 5/6/7. We still surface the current
# values + a "Danger zone" placeholder so the page isn't a stub.

from __future__ import annotations

import time

import httpx
import streamlit as st

from auth import require_auth, render_logout_button
from settings import load as load_settings

st.set_page_config(page_title="Settings — AIAMSBS", page_icon="⚙️", layout="wide")

if not require_auth():
    st.stop()

settings = load_settings()

with st.sidebar:
    st.markdown(f"**Customer:** `{settings.customer_name}`")
    st.markdown(f"**User:** `{st.session_state.get('user', '?')}`")
    st.markdown("---")
    render_logout_button()

st.title("⚙️ Settings")
st.caption("Read-only in Card 3. Writes (per-customer values, secret rotation) "
           "land in Card 5/6/7.")

# ---- Current configuration ----
st.subheader("Current configuration")
st.table([
    {"key": "Customer name",       "value": settings.customer_name},
    {"key": "Admin username",      "value": settings.admin_username},
    {"key": "Hermes Dashboard",    "value": settings.hermes_url},
    {"key": "KB MCP",              "value": settings.kb_url},
    {"key": "Inventory MCP",       "value": settings.inventory_url},
    {"key": "Loki",                "value": settings.loki_url},
    {"key": "Ansible Runner",      "value": settings.ansible_runner_url},
    {"key": "Grafana",             "value": settings.grafana_url},
])

st.markdown("---")


# ---- Health subsection ----
st.subheader("Backend health")
if st.button("Refresh"):
    st.cache_data.clear()


@st.cache_data(ttl=5, show_spinner=False)
def _check(name: str, url: str) -> dict:
    start = time.perf_counter()
    try:
        r = httpx.get(f"{url.rstrip('/')}/health", timeout=5.0)
        ok = r.status_code == 200
        status = r.status_code
    except Exception as e:
        ok = False
        status = f"err: {type(e).__name__}"
    elapsed = int((time.perf_counter() - start) * 1000)
    return {"backend": name, "ok": ok, "latency_ms": elapsed, "status": status}


rows = [_check(name, url) for name, url in settings.backends]
st.dataframe(
    [{"backend": r["backend"], "status": "✅" if r["ok"] else "❌",
      "latency_ms": r["latency_ms"], "http": r["status"]} for r in rows],
    use_container_width=True, hide_index=True,
)

st.markdown("---")


# ---- Danger zone (placeholder) ----
st.subheader("⚠️ Danger zone")
st.warning(
    "Session secret rotation and write-back configuration land in Card 7. "
    "For now this page is read-only.",
    icon="⚠️",
)
st.button("Regenerate session secret (Card 7)", disabled=True, use_container_width=True)

# ---- Loki log ----
try:
    from loki_logger import log_event
    log_event("streamlit", {
        "event": "page_view",
        "page": "Settings",
        "user_id": st.session_state.get("user_id"),
        "username": st.session_state.get("user"),
    })
except Exception:
    pass
