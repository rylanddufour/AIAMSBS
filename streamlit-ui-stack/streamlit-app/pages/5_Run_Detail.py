# pages/5_Run_Detail.py — AIAMSBS v1.0 customer single-run drilldown.
#
# Card 4 of BACKLOG #64. URL: /Run_Detail?run_id=<uuid>. Reads the row
# and its events from the local SQLite, then renders four tabs:
#   * Timeline — ordered list of status_change + exec_* events.
#   * Stdout   — pretty-printed exec_stdout events (already redacted
#                on write by 3_Run_Playbook; we re-redact defensively
#                in case anything snuck in).
#   * Stderr   — exec_stderr events.
#   * Loki     — pre-built Grafana Explore deep link with run_id="<uuid>"
#                pipe-filtered query (Loki labels in this stack are
#                job/source only — run_id lives in the JSON payload;
#                see config/alloy.yml and orchestrator's open-question
#                resolution on Card 4).
#
# If ?run_id is missing or invalid, render a friendly empty state.

from __future__ import annotations

import html as html_lib
import json
from urllib.parse import quote

import httpx
import streamlit as st

from auth import require_auth, render_logout_button
from db import db
from hermes_client import redact_secrets, short_run_id
from settings import load as load_settings

st.set_page_config(page_title="Run Detail — AIAMSBS", page_icon="🔎", layout="wide")

if not require_auth():
    st.stop()

settings = load_settings()

with st.sidebar:
    st.markdown(f"### AIAMSBS\n**Customer:** `{settings.customer_name}`")
    st.markdown(f"**User:** `{st.session_state.get('user', '?')}`")
    st.markdown("---")
    render_logout_button()

st.title("🔎 Run Detail")

# Read run_id from URL (?run_id=<uuid>) or session state fallback
run_id = st.query_params.get("run_id")
if not run_id:
    st.warning("No run_id in the URL. Open a run from Run History.")
    st.page_link("pages/4_Run_History.py", label="← Back to Run History",
                 icon="📜")
    st.stop()

# ---- Load the run row ----
with db() as conn:
    row = conn.execute(
        "SELECT pr.*, u.username "
        "FROM playbook_runs pr "
        "JOIN users u ON u.id = pr.user_id "
        "WHERE pr.id = ?",
        (run_id,),
    ).fetchone()

if row is None:
    st.error(f"No run with id `{short_run_id(run_id)}` found in the local DB.")
    st.stop()

run = dict(row)

# ---- Header ----
status_emoji = {
    "queued": "⏳", "running": "▶️", "completed": "✅",
    "failed": "❌", "cancelled": "⛔",
}.get(run["status"], "❔")

header_cols = st.columns([3, 2])
with header_cols[0]:
    st.markdown(f"### {status_emoji} `{short_run_id(run['id'])}`")
    st.caption(
        f"**Playbook:** `{run['playbook']}`  •  **Inventory:** "
        f"`{run['inventory']}`  •  **Target:** `{run['target']}`  •  "
        f"**Mode:** `{run['mode']}`"
    )
with header_cols[1]:
    st.markdown(
        f"**User:** `{run['username']}`  •  **Status:** `{run['status']}`  •  "
        f"**Exit code:** `{run['exit_code']}`"
    )
    st.caption(
        f"created={run['created_at']} · started={run['started_at']} · "
        f"finished={run['finished_at']}"
    )

st.markdown("---")

# ---- Load events ----
with db() as conn:
    events = [dict(r) for r in conn.execute(
        "SELECT id, event_type, payload, ts FROM playbook_run_events "
        "WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    ).fetchall()]

tab_t, tab_o, tab_e, tab_l = st.tabs(["Timeline", "Stdout", "Stderr", "Loki"])

# ---- Timeline ----
with tab_t:
    if not events:
        st.caption("(no events recorded yet)")
    else:
        for ev in events:
            try:
                payload = json.loads(ev["payload"])
            except json.JSONDecodeError:
                payload = {"raw": ev["payload"]}
            try:
                payload_str = json.dumps(redact_secrets(payload), default=str,
                                         indent=2)
            except Exception:
                payload_str = html_lib.escape(str(payload))
            summary = ""
            if "status" in payload:
                summary = f"status=`{payload['status']}`"
            if "exit_code" in payload:
                summary += f" exit_code=`{payload['exit_code']}`"
            if "event" in payload:
                summary += f" event=`{payload['event']}`"
            st.markdown(
                f"`{ev['ts'] or ''}` · **{ev['event_type']}** "
                f"{summary}"
            )
            with st.expander("payload", expanded=False):
                st.code(payload_str, language="json")

# ---- Stdout / Stderr ----
def _render_event_text(filter_type: str, tab) -> None:
    matching = [ev for ev in events if ev["event_type"] == filter_type]
    with tab:
        if not matching:
            st.caption(f"(no {filter_type} events)")
            return
        for ev in matching:
            try:
                p = json.loads(ev["payload"])
            except json.JSONDecodeError:
                p = {"line": ev["payload"]}
            line = p.get("line", "")
            # Belt-and-braces: strip any stray password= substrings.
            line = redact_secrets(line)
            st.text(line)


_render_event_text("exec_stdout", tab_o)
_render_event_text("exec_stderr", tab_e)

# ---- Loki link ----
with tab_l:
    st.markdown(
        f"To view this run in Loki, open the link below. The query filters "
        f"`job=\"aiamsbs-streamlit\"` and pipes for the run_id in the JSON "
        f"payload (Loki does not have `run_id` as a label — it's an "
        f"orchestrator's open-question resolution, see Card 4 body)."
    )
    # Grafana Explore deep link with the run_id pre-filtered.
    grafana_base = settings.grafana_url.rstrip("/")
    # Loki datasource UID on the AIAMSBS host varies. v1.0 customers use
    # the default Grafana Loki datasource which Grafana auto-creates
    # with a uuid — but the "Data sources" filter in Explore works without
    # the UID (Grafana prompts on click). Build a query that works on
    # both — start with the pipeline filter.
    query = f'{{job="aiamsbs-streamlit"}} |= "run_id={run_id}"'
    explore_url = (
        f"{grafana_base}/explore?orgId=1&left="
        f"%5B%22now-1h%22%2C%22now%22%2C%22Loki%22%2C%7B%22expr%22%3A"
        f"{quote(query)}%7D%5D"
    )
    st.markdown(
        f"[Open in Grafana Explore →]({explore_url})  \n"
        f"_Equivalent query: `{query}`_"
    )
    # Offer a copy-paste Loki HTTP query if operator wants curl.
    loki_url = settings.loki_url.rstrip("/")
    loki_query_url = (
        f"{loki_url}/loki/api/v1/query_range"
        f"?query={quote(query)}&limit=200"
    )
    st.code(loki_query_url, language="text")
    # Optional: try to fetch recent Loki entries client-side so the
    # operator sees the audit trail without leaving the page. Network
    # may be unreliable; show the error if so.
    try:
        r = httpx.get(loki_query_url, timeout=5.0)
        if r.status_code == 200:
            data = r.json()
            streams = (data.get("data") or {}).get("result") or []
            if not streams:
                st.caption("No matching Loki entries in the last 1h.")
            else:
                for s in streams:
                    for v in s.get("values", []):
                        ts_ns, line = v
                        # line is a stringified JSON line.
                        try:
                            obj = json.loads(line)
                            st.text(
                                f"[{obj.get('ts','')}] "
                                f"{obj.get('event','?')}: {line}"
                            )
                        except json.JSONDecodeError:
                            st.text(line)
        else:
            st.caption(f"Loki returned {r.status_code} — use the Grafana link.")
    except Exception as exc:
        st.caption(f"Loki not reachable from this container ({type(exc).__name__}) — use the Grafana link.")

st.markdown("---")
nav_cols = st.columns([1, 1, 6])
with nav_cols[0]:
    st.page_link("pages/4_Run_History.py", label="← Run History",
                 icon="📜", use_container_width=True)
with nav_cols[1]:
    st.page_link("pages/3_Run_Playbook.py", label="➕ New run",
                 icon="▶️", use_container_width=True)
