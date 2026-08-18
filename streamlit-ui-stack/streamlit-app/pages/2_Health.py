# pages/2_Health.py — per-backend health probe page.
#
# For each backend in settings.backends, GET <url>/health with a 5s timeout.
# Render name + ✅/❌ + latency_ms + last_checked_at. Refresh button
# invalidates the cache and re-probes.

from __future__ import annotations

import time
from datetime import datetime

import httpx
import streamlit as st

from auth import require_auth, render_logout_button
from settings import load as load_settings

st.set_page_config(page_title="Health — AIAMSBS", page_icon="🩺", layout="wide")

if not require_auth():
    st.stop()

settings = load_settings()

with st.sidebar:
    st.markdown(f"**Customer:** `{settings.customer_name}`")
    st.markdown(f"**User:** `{st.session_state.get('user', '?')}`")
    st.markdown("---")
    render_logout_button()

st.title("🩺 Backend health")
st.caption("HTTP GET <url>/health for every backend on the monitoring network. "
           "5s timeout per probe.")

# Refresh button + last-checked-at banner.
col_btn, col_when = st.columns([1, 4])
with col_btn:
    if st.button("Refresh", use_container_width=True):
        st.cache_data.clear()
with col_when:
    last_check = st.session_state.get("health_last_checked", "—")
    st.caption(f"Last refresh: {last_check}")


@st.cache_data(ttl=5, show_spinner=False)
def _probe(name: str, url: str) -> dict:
    """Probe one backend. Cached 5s. Returned dict has all fields for the table."""
    start = time.perf_counter()
    try:
        r = httpx.get(f"{url.rstrip('/')}/health", timeout=5.0)
        ok = r.status_code == 200
        http = r.status_code
    except httpx.TimeoutException:
        ok, http = False, "timeout"
    except Exception as e:
        ok, http = False, f"{type(e).__name__}"
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {
        "backend": name,
        "url": url,
        "ok": ok,
        "http": http,
        "latency_ms": elapsed_ms,
        "checked_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


# Render a tile per backend.
rows = [_probe(name, url) for name, url in settings.backends]
st.session_state["health_last_checked"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

tiles = st.columns(len(rows))
for col, row in zip(tiles, rows):
    with col:
        if row["ok"]:
            st.success(f"✅ {row['backend']}\n\n{row['latency_ms']} ms", icon="✅")
        else:
            st.error(f"❌ {row['backend']}\n\n{row['http']}", icon="❌")
        st.caption(row["url"])

st.markdown("---")

# Detailed table.
st.subheader("Details")
st.dataframe(
    [
        {
            "backend": r["backend"],
            "status": "✅ OK" if r["ok"] else f"❌ {r['http']}",
            "latency_ms": r["latency_ms"],
            "last_checked_at": r["checked_at"],
            "url": r["url"],
        }
        for r in rows
    ],
    use_container_width=True, hide_index=True,
)

# ---- Loki log ----
try:
    from loki_logger import log_event
    log_event("streamlit", {
        "event": "page_view",
        "page": "Health",
        "user_id": st.session_state.get("user_id"),
        "username": st.session_state.get("user"),
    })
except Exception:
    pass
