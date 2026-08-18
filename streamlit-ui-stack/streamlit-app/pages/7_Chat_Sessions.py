# pages/7_Chat_Sessions.py — AIAMSBS v1.0 customer Chat Sessions list.
#
# Card 5 of BACKLOG #64. Lists every chat_session for the current user,
# with filters (title LIKE search, date range, "last_active > N days"),
# a continue button (jumps to 6_Agent_Chat.py?session_id=<id>) and a
# delete button (which also calls Hermes's DELETE /api/sessions/<id>).
#
# Hermes-side sessions are NOT shown here directly. v1.0 is single-
# admin, so the local SQLite mirror IS the user's view of their
# conversations. We DO surface Hermes's `preview` / message_count /
# tokens metadata if the operator opts to merge the two sources in a
# future card — for now, we keep it simple.

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

import hermes_client
from auth import require_auth, render_logout_button
from db import (
    delete_chat_session,
    list_chat_sessions,
)
from settings import load as load_settings

st.set_page_config(
    page_title="Chat Sessions — AIAMSBS", page_icon="�", layout="wide",
)

if not require_auth():
    st.stop()

settings = load_settings()
user_id: int = int(st.session_state.get("user_id") or 0)
username: str = str(st.session_state.get("user") or "unknown")
if not user_id:
    st.error("Session lost its user_id — please log in again.")
    st.stop()

with st.sidebar:
    st.markdown(f"### AIAMSBS\n**Customer:** `{settings.customer_name}`")
    st.markdown(f"**User:** `{username}`")
    st.markdown("---")
    st.markdown("**Chat Sessions**")
    st.caption("Every IT_ADMIN conversation you've had.")
    st.markdown("---")
    render_logout_button()

st.title("📚 Chat Sessions")
st.caption(
    "Past conversations with IT_ADMIN. Click **Continue** to pick up "
    "where you left off, or **Delete** to remove."
)

# ---- Top links ----
top_cols = st.columns([1, 6])
with top_cols[0]:
    st.page_link(
        "pages/6_Agent_Chat.py",
        label="➕ New chat",
        icon="�",
        use_container_width=True,
    )


# ---- Load + cache the rows ----
@st.cache_data(ttl=5, show_spinner=False)
def _load_user_sessions(_user_id: int) -> list[dict]:
    return list_chat_sessions(_user_id)


try:
    rows = _load_user_sessions(user_id)
except Exception as exc:
    st.error(f"Could not load chat sessions: {exc}")
    st.stop()

if not rows:
    st.info(
        "No chat sessions yet. Use **➕ New chat** above (or the "
        "Agent Chat page) to start one."
    )
    st.stop()


# ---- Filters ----
fcols = st.columns(3)
with fcols[0]:
    title_query = st.text_input(
        "Title contains", value="",
        placeholder="e.g. inventory",
        key="cs_title",
    ).strip()
with fcols[1]:
    days_back = st.slider(
        "Days back", min_value=1, max_value=365, value=30, step=1,
        key="cs_days",
    )
with fcols[2]:
    show_archived = st.checkbox(
        "Include archived", value=False, key="cs_archived",
        help="Archived = Hermes DELETE failed and the row was soft-deleted.",
    )


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.split(".")[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.fromisoformat(
                s.replace("Z", "+00:00").split(".")[0]
            )
        except ValueError:
            return None


cutoff = datetime.utcnow() - timedelta(days=int(days_back))


def _passes(r: dict) -> bool:
    if title_query:
        title = (r.get("title") or "").lower()
        if title_query.lower() not in title:
            return False
    dt = _parse_dt(r.get("last_active") or r.get("created_at"))
    if dt is None or dt < cutoff:
        return False
    return True


filtered = [r for r in rows if _passes(r)]
if not filtered:
    st.info("No sessions match the current filters.")
    st.stop()

st.caption(
    f"Showing {len(filtered)} of {len(rows)} sessions in the last "
    f"{days_back} day(s)."
)


# ---- Render table ----
# Build a list of {id, title, last_active, created_at, _full_id, ...}.
# We hide the long response_id from the table for readability but keep it
# in the row dict so we can show it on demand.
table_rows: list[dict] = []
for r in filtered:
    title = r.get("title") or "(untitled)"
    last_active = r.get("last_active") or r.get("created_at") or ""
    table_rows.append({
        "title": title,
        "last_active": last_active,
        "session": r["id"].split("-", 1)[0],
        "_full_id": r["id"],
        "_response_id": r.get("last_response_id") or "",
    })

st.dataframe(
    [{k: v for k, v in row.items() if not k.startswith("_")}
     for row in table_rows],
    use_container_width=True,
    hide_index=True,
)


# ---- Per-row Continue / Delete ----
st.markdown("---")
st.subheader("Manage sessions")

for row in table_rows:
    full_id = row["_full_id"]
    short = row["session"]
    cols = st.columns([4, 2, 2])
    with cols[0]:
        st.markdown(f"**{row['title']}**  ·  `{short}`")
        if row["_response_id"]:
            st.caption(f"last response: `{row['_response_id'][:20]}…`")
    with cols[1]:
        if st.button(
            "▶️ Continue",
            key=f"continue_{full_id}",
            type="primary",
            use_container_width=True,
        ):
            hermes_client.log_chat_event(
                "chat_session_loaded",
                user_id=user_id,
                session_id=full_id,
            )
            st.query_params["session_id"] = full_id
            st.switch_page("pages/6_Agent_Chat.py")
    with cols[2]:
        if st.button(
            "�️ Delete",
            key=f"delete_{full_id}",
            use_container_width=True,
        ):
            st.session_state[f"confirm_delete_{full_id}"] = True

    # Confirmation row (separate from the columns to keep the UI clean).
    if st.session_state.get(f"confirm_delete_{full_id}"):
        cw = st.columns([5, 1, 1])
        with cw[1]:
            if st.button(
                "Cancel",
                key=f"cancel_{full_id}",
                use_container_width=True,
            ):
                del st.session_state[f"confirm_delete_{full_id}"]
                st.rerun()
        with cw[2]:
            if st.button(
                "Confirm delete",
                key=f"confirm_{full_id}",
                type="primary",
                use_container_width=True,
            ):
                # 1. Tell Hermes (if reachable). delete_session is
                # idempotent + non-fatal: if Hermes is down or 404s, the
                # local SQLite row is still removed (the call returns
                # True for 404).
                hermes_client.delete_session(full_id)
                # 2. Drop from local SQLite.
                deleted = delete_chat_session(full_id, user_id)
                hermes_client.log_chat_event(
                    "chat_session_deleted",
                    user_id=user_id,
                    session_id=full_id,
                    deleted=bool(deleted),
                )
                del st.session_state[f"confirm_delete_{full_id}"]
                _load_user_sessions.clear()
                st.rerun()

# ---- Hermes-side count for ops visibility ----
# Pull the Hermes-side list (best-effort). If it fails, fall back to the
# local SQLite count only.
try:
    hermes_rows = hermes_client.list_sessions(user_id=user_id)
    hermes_count = len(hermes_rows)
except Exception:
    hermes_count = None

st.markdown("---")
if hermes_count is not None:
    st.caption(
        f"Local sessions: {len(rows)} · Hermes-side sessions (all "
        f"profiles): {hermes_count}"
    )
else:
    st.caption(f"Local sessions: {len(rows)} · Hermes-side list unavailable.")
