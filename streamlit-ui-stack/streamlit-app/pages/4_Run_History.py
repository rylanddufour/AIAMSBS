# pages/4_Run_History.py — AIAMSBS v1.0 customer Run History list view.
#
# Card 4 of BACKLOG #64. Lists every playbook_runs row joined with the
# users table so the operator can see who triggered what. Filters: status,
# playbook, date range, username. "New run" link back to the Run Playbook
# page. Click a row → drill into Run_Detail via ?run_id=<uuid>.

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from auth import require_auth, render_logout_button
from db import db
from hermes_client import short_run_id
from settings import load as load_settings
from theme import AIAMSBS_FAVICON, apply_theme, cyberpunk_title, page_header, section_header

st.set_page_config(page_title="Run History — AIAMSBS", page_icon=AIAMSBS_FAVICON, layout="wide")

if not require_auth():
    st.stop()

# Theme (BACKLOG #72 — Dark Cyber palette). Applied AFTER
# auth so the login form is the only place the default
# light theme bleeds through.
apply_theme()

settings = load_settings()

with st.sidebar:
    render_logout_button()

cyberpunk_title("Run History", "run_history")
st.caption("Every playbook execution Card 4 has queued. Click a row to drill in.")


# ---- Load + cache the rows ----
@st.cache_data(ttl=5, show_spinner=False)
def _load_rows() -> list[dict]:
    with db() as conn:
        cur = conn.execute(
            "SELECT pr.id AS run_id, "
            "       pr.playbook, pr.inventory, pr.target, pr.mode, "
            "       pr.status, pr.created_at, pr.started_at, pr.finished_at, "
            "       pr.exit_code, "
            "       u.username "
            "FROM playbook_runs pr "
            "JOIN users u ON u.id = pr.user_id "
            "ORDER BY pr.created_at DESC"
        )
        rows = [dict(r) for r in cur.fetchall()]
    return rows


try:
    rows = _load_rows()
except Exception as exc:
    st.error(f"Could not load run history: {exc}")
    st.stop()

if not rows:
    st.info("No runs yet. Open **Run Playbook** from the sidebar to start one.")
    st.stop()

# ---- Filter UI ----
all_statuses = sorted({r["status"] for r in rows})
all_playbooks = sorted({r["playbook"] for r in rows})
all_users = sorted({r["username"] for r in rows})

fcols = st.columns(4)
with fcols[0]:
    status_filter = st.multiselect("Status", options=all_statuses, default=all_statuses)
with fcols[1]:
    playbook_filter = st.multiselect("Playbook", options=all_playbooks,
                                     default=all_playbooks)
with fcols[2]:
    user_filter = st.multiselect("User", options=all_users, default=all_users)
with fcols[3]:
    # Date range: default = last 30 days. Allow 1..365 days back.
    days_back = st.slider("Days back", min_value=1, max_value=365, value=30, step=1)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # SQLite CURRENT_TIMESTAMP is "YYYY-MM-DD HH:MM:SS" (UTC). Convert
        # to a datetime for comparison.
        return datetime.strptime(s.split(".")[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00").split(".")[0])
        except ValueError:
            return None


cutoff = datetime.utcnow() - timedelta(days=int(days_back))

filtered: list[dict] = []
for r in rows:
    if r["status"] not in status_filter:
        continue
    if r["playbook"] not in playbook_filter:
        continue
    if r["username"] not in user_filter:
        continue
    dt = _parse_dt(r["created_at"])
    if dt is None or dt < cutoff:
        continue
    filtered.append(r)

if not filtered:
    st.info("No runs match the current filters.")
    st.stop()

# ---- Render table ----
section_header("Results")
table_rows: list[dict] = []
for r in filtered:
    started = _parse_dt(r["started_at"])
    finished = _parse_dt(r["finished_at"])
    duration = ""
    if started and finished:
        delta = finished - started
        secs = int(delta.total_seconds())
        duration = f"{secs // 60}m {secs % 60}s"
    elif started:
        duration = "running…"

    status_emoji = {
        "queued": "⏳",
        "running": "▶️",
        "completed": "✅",
        "failed": "❌",
        "cancelled": "⛔",
    }.get(r["status"], "❔")

    table_rows.append({
        "run_id": short_run_id(r["run_id"]),
        "playbook": r["playbook"],
        "target": r["target"] or "—",
        "mode": r["mode"],
        "status": f"{status_emoji} {r['status']}",
        "user": r["username"],
        "created_at": r["created_at"] or "",
        "duration": duration,
        "exit_code": r["exit_code"] if r["exit_code"] is not None else "",
        "_full_id": r["run_id"],  # for the click handler
    })

st.caption(f"Showing {len(filtered)} of {len(rows)} runs in the last {days_back} days.")
st.dataframe(
    [{k: v for k, v in row.items() if k != "_full_id"} for row in table_rows],
    use_container_width=True,
    hide_index=True,
)

# ---- Drill-in ----
section_header("Open a run")
options = [f"{row['_full_id']}  ({row['playbook']}, {row['status']})"
           for row in table_rows]
selected = st.selectbox(
    "Run id",
    options=["—"] + options,
    index=0,
    key="rh_select",
)
if selected != "—":
    full_id = selected.split("  ", 1)[0]
    if st.button(f"Open run `{short_run_id(full_id)}`", key="rh_open",
                 type="primary"):
        # Pass the run_id to 5_Run_Detail via st.switch_page's query_params
        # arg (Streamlit 1.39+). Setting st.query_params["run_id"] = ...
        # before switch_page would only set it on the CURRENT page (Run
        # History), and the URL would not carry it to the next page —
        # so 5_Run_Detail would see no run_id and show 'No run_id in the
        # URL.' (BACKLOG #73).
        st.switch_page("pages/5_Run_Detail.py", query_params={"run_id": full_id})
