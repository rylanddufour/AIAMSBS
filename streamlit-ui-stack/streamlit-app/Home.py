# Home.py — AIAMSBS v1.0 customer landing page.
#
# Entry point. Sets page_config + auth gate + the post-login dashboard.
# Card 4 (Run Playbook) and Card 5 (Agent Chat) add pages under pages/
# later; this Home is intentionally minimal — quick links, health
# snapshot, recent activity placeholders.

from __future__ import annotations

import time

import httpx
import streamlit as st

from auth import require_auth, render_logout_button
from db import db, init_schema
from settings import load as load_settings
from theme import AIAMSBS_FAVICON, apply_theme, cyberpunk_title, page_header, page_link_button

st.set_page_config(
    page_title="AIAMSBS v1.0",
    page_icon=AIAMSBS_FAVICON, layout="wide",
    initial_sidebar_state="expanded",
)

# Run schema migrations on every page load (idempotent, ~10ms on a cold
# SQLite file; <1ms after that). Doing it here means Card 4/5 pages can
# assume the schema exists without re-implementing the call.
init_schema()

# Auth gate.
if not require_auth():
    st.stop()

# Theme (BACKLOG #72 — Dark Cyber palette). Applied AFTER auth so the
# login form is the only place the default light theme bleeds through.
apply_theme()

settings = load_settings()

# ---- Sidebar ----
# ---- Header ----
cyberpunk_title(f"AIAMSBS v1.0 — Customer {settings.customer_name}", "home")
st.caption(
    "Private deployment dashboard. Backends below run on the AIAMSBS host. "
    "Pages (Settings, Run Playbook, Agent Chat, etc.) are in the sidebar. "
    "Quick Links point at host IPs by default — edit them on the Settings page."
)

# ---- Quick links ----
# Uses the Quick Links group (browser-facing, host IP) from Settings,
# NOT the Backend URLs (container-internal). Edit these on the
# Settings page if the host IP changes.
st.subheader("Quick links")
ql1, ql2, ql3 = st.columns(3)
quicklinks = dict(settings.quicklinks)
ql1.link_button("Open Grafana", quicklinks.get("Open Grafana", settings.grafana_url), use_container_width=True)
ql2.link_button("Open Hermes Dashboard", quicklinks.get("Open Hermes Dashboard", settings.hermes_url), use_container_width=True)
ql3.link_button("Open KB MCP", quicklinks.get("Open KB MCP", settings.kb_url), use_container_width=True)

st.markdown("---")


# ---- Health snapshot (calls each backend's /health) ----
def _check_one(name: str, base_url: str, health_path: str = "/health", timeout: float = 2.0) -> tuple[bool, int | None]:
    """Return (reachable, latency_ms).

    Same semantics as the old Health page: reachable = any HTTP response,
    not just 200. Connection errors mean unreachable.

    `health_path` defaults to `/health` but each backend may declare its
    own readiness endpoint (Prometheus: `/-/ready`, Grafana: `/api/health`).
    BACKLOG #68 — per-backend health paths enable Prometheus + Grafana tiles.
    """
    start = time.perf_counter()
    try:
        r = httpx.get(f"{base_url.rstrip('/')}{health_path}", timeout=timeout)
        ok = True  # any HTTP response = reachable
    except Exception:
        ok = False
    elapsed = int((time.perf_counter() - start) * 1000)
    return ok, elapsed


@st.cache_data(ttl=10, show_spinner=False)
def _health_snapshot() -> list[dict]:
    """Cached for 10s so a refresh doesn't hammer every backend."""
    rows = []
    for name, url, health_path in load_settings().backends:
        ok, latency = _check_one(name, url, health_path)
        rows.append({"backend": name, "ok": ok, "latency_ms": latency})
    return rows


st.subheader("Health snapshot")
snapshot = _health_snapshot()
hcols = st.columns(len(snapshot))
for col, row in zip(hcols, snapshot):
    with col:
        if row["ok"]:
            st.success(f"✅ {row['backend']}\n{row['latency_ms']} ms", icon="✅")
        else:
            st.error(f"❌ {row['backend']}\n—", icon="❌")

st.caption("Refreshed every 10s. Full diagnostics below.")

st.markdown("---")


# ---- Recent activity (placeholders for Card 4/5) ----
ra1, ra2 = st.columns(2)
with ra1:
    st.subheader("Recent playbook runs")
    with db() as conn:
        rows = conn.execute(
            "SELECT id, playbook, status, created_at FROM playbook_runs "
            "ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No playbook runs yet. The Run Playbook page (Card 4) lands here.")

with ra2:
    st.subheader("Recent chat sessions")
    with db() as conn:
        rows = conn.execute(
            "SELECT id, title, last_active FROM chat_sessions "
            "ORDER BY last_active DESC LIMIT 5"
        ).fetchall()
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No chat sessions yet. The Agent Chat page (Card 5) lands here.")



# ---- Footer: log this visit to Loki ----
try:
    from loki_logger import log_event
    log_event("streamlit", {
        "event": "home_view",
        "page": "Home",
        "user_id": st.session_state.get("user_id"),
        "username": st.session_state.get("user"),
    })
    # Login event is fired from render_login_form in auth.py on first success.
except Exception as e:
    # Loki failures must never break the page.
    st.caption(f"⚠️ loki_logger: {type(e).__name__}: {e}")


# ---- Logout (moved from sidebar to page body) ----
st.markdown("---")
render_logout_button()