# pages/7_Chat_Sessions.py — AIAMSBS v1.0 customer Chat Sessions.
#
# Card 5 of BACKLOG #64. Top-row layout:
#   [ Days back slider ] [ Session dropdown ]
#   Below: session history + chat_input (when selected)
#          OR friendly prompt (when none selected)
#
# Source of truth:
#   - URL (st.query_params["session_id"]) is the active session.
#   - The slider (st.session_state["cs_days"]) filters the dropdown.
#   - The dropdown (st.session_state["cs_top_select"]) is the UI
#     input that updates the URL.
#   - We never write to a widget-bound key from outside the widget.
#
# Privacy: chat message BODIES are NEVER written to Loki.

from __future__ import annotations

import json
from datetime import datetime, timedelta

import streamlit as st

import hermes_client
from auth import require_auth, render_logout_button
from db import (
    add_chat_message,
    delete_chat_session,
    get_chat_session,
    list_chat_messages,
    list_chat_sessions,
    update_chat_session_response,
)
from settings import load as load_settings
from theme import apply_theme

st.set_page_config(
    page_title="Chat Sessions — AIAMSBS", page_icon="💬", layout="wide",
)

if not require_auth():
    st.stop()

# Theme (BACKLOG #72 — Dark Cyber palette). Applied AFTER
# auth so the login form is the only place the default
# light theme bleeds through.
apply_theme()

settings = load_settings()
user_id: int = int(st.session_state.get("user_id") or 0)
username: str = str(st.session_state.get("user") or "unknown")
if not user_id:
    st.error("Session lost its user_id — please log in again.")
    st.stop()


# ---- Helpers ----
def _short_id(sid: str) -> str:
    return sid.split("-", 1)[0] if "-" in sid else sid[:8]


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


def _relative_time(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    delta = datetime.utcnow() - dt
    if delta.days >= 365:
        return f"{delta.days // 365}y ago"
    if delta.days >= 30:
        return f"{delta.days // 30}mo ago"
    if delta.days >= 7:
        return f"{delta.days // 7}w ago"
    if delta.days >= 1:
        return f"{delta.days}d ago"
    if delta.seconds >= 3600:
        return f"{delta.seconds // 3600}h ago"
    if delta.seconds >= 60:
        return f"{delta.seconds // 60}m ago"
    return "just now"


def _render_message(m: dict) -> None:
    role = m.get("role") or "assistant"
    with st.chat_message(role):
        st.markdown(m.get("content") or "")
        tcs = m.get("tool_calls_json")
        if tcs and role == "assistant":
            try:
                parsed = json.loads(tcs)
            except json.JSONDecodeError:
                parsed = []
            if parsed:
                with st.expander(
                    f"🔧 Tool calls ({len(parsed)})", expanded=False
                ):
                    for tc in parsed:
                        name = tc.get("name", "?")
                        args = tc.get("arguments", "")
                        tc_out = tc.get("output")
                        st.markdown(f"**`{name}`**")
                        if args:
                            st.code(args, language="json")
                        if tc_out is not None:
                            out_str = (
                                tc_out if isinstance(tc_out, str)
                                else json.dumps(tc_out)
                            )
                            truncated = (
                                out_str[:200] + "…"
                                if len(out_str) > 200 else out_str
                            )
                            st.markdown(
                                f"↳ result (≤200 chars): `{truncated}`"
                            )


# ---- Cached session list ----
@st.cache_data(ttl=5, show_spinner=False)
def _load_user_sessions(_user_id: int) -> list[dict]:
    return list_chat_sessions(_user_id)


try:
    rows = _load_user_sessions(user_id)
except Exception as exc:
    st.error(f"Could not load chat sessions: {exc}")
    rows = []


# ============================================================
# ============================================================
# Pages heading
# ============================================================
st.markdown("# 📚 Chat Sessions")
st.caption(
    "Filter by days back, pick a session from the dropdown, then "
    "continue the conversation below."
)


# ============================================================
# Top: days_back slider + session dropdown (full-width, stacked)
# ============================================================
st.markdown("**Days back**")
days_back = st.slider(
    "Days back",
    min_value=1, max_value=365, value=30, step=1,
    key="cs_days",
    label_visibility="collapsed",
)
st.markdown("**Select session**")

# Apply the days-back filter to scope the dropdown.
cutoff = datetime.utcnow() - timedelta(days=int(days_back))
filtered_rows = []
for r in rows:
    dt = _parse_dt(r.get("last_active") or r.get("created_at"))
    if dt is None or dt < cutoff:
        continue
    filtered_rows.append(r)

# Build dropdown options: (display_label, session_id).
session_options: list[str] = []
session_labels: dict[str, str] = {}
for r in filtered_rows:
    title = r.get("title") or "(untitled)"
    short = _short_id(r["id"])
    dt = _parse_dt(r.get("last_active") or r.get("created_at"))
    last_active = _relative_time(dt)
    label = f"💬 {title[:36]} · {short} · {last_active}"
    session_options.append(label)
    session_labels[r["id"]] = label

label_to_id = {label: sid for sid, label in session_labels.items()}

url_session_id = st.query_params.get("session_id", None)

if not session_options:
    st.caption(
        f"No sessions in the last {days_back} day(s). "
        "Widen the slider or start a new chat."
    )
else:
        # Default selection: URL's session_id if it's in the
        # filtered options; otherwise the first option.
        default_label = session_options[0]
        if url_session_id and url_session_id in session_labels:
            default_label = session_labels[url_session_id]
        default_index = (
            session_options.index(default_label)
            if default_label in session_options else 0
        )

        selected_label = st.selectbox(
            "Select session",
            options=session_options,
            index=default_index,
            key="cs_top_select",
            label_visibility="collapsed",
        )
        # Resolve the selected label to a session_id.
        new_id = label_to_id.get(selected_label)
        if new_id and new_id != url_session_id:
            st.query_params["session_id"] = new_id
            hermes_client.log_chat_event(
                "chat_session_loaded",
                user_id=user_id,
                session_id=new_id,
            )
            st.rerun()


# ============================================================
# Main pane: session history + chat_input
# ============================================================
st.markdown("---")

if not url_session_id:
    st.info(
        "👆 Pick a session from the dropdown above, or click "
        "**Agent Chat** in the sidebar to start a new one."
    )
else:
    active_row = get_chat_session(url_session_id, user_id)
    if active_row is None:
        st.warning(
            f"Session `{_short_id(url_session_id)}` is not in your "
            "local store. Pick a different session from the dropdown."
        )
    else:
        title = active_row.get("title") or "(untitled)"
        dt = _parse_dt(
            active_row.get("last_active") or active_row.get("created_at")
        )
        last_active = _relative_time(dt)

        # Header: title + short_id + last_active + delete
        h_cols = st.columns([6, 1])
        with h_cols[0]:
            st.markdown(
                f"## 💬 **{title}**  ·  `{_short_id(url_session_id)}`  ·  "
                f"<small>{last_active}</small>",
                unsafe_allow_html=True,
            )
        with h_cols[1]:
            if st.button(
                "🗑 Delete",
                key="cs_delete_active",
                use_container_width=True,
            ):
                st.session_state["confirm_delete_active"] = True

        if st.session_state.get("confirm_delete_active"):
            cw = st.columns([6, 1, 1])
            with cw[1]:
                if st.button(
                    "Cancel",
                    key="cs_cancel_delete_active",
                    use_container_width=True,
                ):
                    del st.session_state["confirm_delete_active"]
                    st.rerun()
            with cw[2]:
                if st.button(
                    "Confirm delete",
                    key="cs_confirm_delete_active",
                    type="primary",
                    use_container_width=True,
                ):
                    hermes_client.delete_session(url_session_id)
                    deleted = delete_chat_session(url_session_id, user_id)
                    hermes_client.log_chat_event(
                        "chat_session_deleted",
                        user_id=user_id,
                        session_id=url_session_id,
                        deleted=bool(deleted),
                    )
                    del st.query_params["session_id"]
                    del st.session_state["confirm_delete_active"]
                    _load_user_sessions.clear()
                    st.rerun()

        # History
        messages = list_chat_messages(url_session_id)
        if not messages:
            st.caption("(This session has no messages yet.)")
        for m in messages:
            _render_message(m)

        # Continue chat
        prompt = st.chat_input("Continue the conversation…")
        if prompt:
            hermes_client.log_chat_event(
                "chat_message_sent",
                user_id=user_id,
                session_id=url_session_id,
                role="user",
                msg_len=len(prompt),
            )
            with st.chat_message("user"):
                st.markdown(prompt)

            prev = active_row.get("last_response_id") if active_row else None
            with st.spinner("IT_ADMIN is thinking…"):
                try:
                    if not prev:
                        result = hermes_client.start_chat(
                            user=username, first_message=prompt,
                        )
                        returned_id = result["session_id"]
                        if returned_id != url_session_id:
                            st.query_params["session_id"] = returned_id
                        update_kwargs = {
                            "session_id": returned_id,
                            "last_response_id": result.get("response_id", ""),
                        }
                    else:
                        result = hermes_client.continue_chat(
                            session_id=url_session_id,
                            message=prompt,
                            previous_response_id=prev,
                        )
                        update_kwargs = {
                            "session_id": url_session_id,
                            "last_response_id": result.get("response_id", ""),
                        }
                except hermes_client.HermesAuthError as e:
                    st.error(
                        "🔑 **Hermes auth failed.** "
                        "`HERMES_API_KEY` is missing or rejected by "
                        f"the gateway. ({e})"
                    )
                    hermes_client.log_chat_event(
                        "chat_error",
                        user_id=user_id,
                        session_id=url_session_id,
                        error_type="HermesAuthError",
                        error=str(e),
                    )
                    st.stop()
                except hermes_client.HermesAPIError as e:
                    st.error(
                        f"❌ **Hermes API error.** Status {e.status}. "
                        f"Body: `{e.body[:200]}`"
                    )
                    hermes_client.log_chat_event(
                        "chat_error",
                        user_id=user_id,
                        session_id=url_session_id,
                        error_type="HermesAPIError",
                        error=str(e),
                        status=e.status,
                    )
                    st.stop()
                except Exception as e:
                    st.error(f"❌ **Chat failed:** {e}")
                    hermes_client.log_chat_event(
                        "chat_error",
                        user_id=user_id,
                        session_id=url_session_id,
                        error_type=type(e).__name__,
                        error=str(e),
                    )
                    st.stop()

            text = result.get("text", "") or ""
            tool_calls = result.get("tool_calls", []) or []
            sess_id = update_kwargs["session_id"]
            response_id = update_kwargs["last_response_id"]

            add_chat_message(
                session_id=sess_id,
                role="user",
                content=prompt,
            )
            add_chat_message(
                session_id=sess_id,
                role="assistant",
                content=text,
                response_id=response_id,
                tool_calls_json=json.dumps(tool_calls) if tool_calls else None,
            )
            update_chat_session_response(
                session_id=sess_id,
                last_response_id=response_id,
            )
            hermes_client.log_chat_event(
                "chat_session_continued",
                user_id=user_id,
                session_id=sess_id,
                role="user",
                msg_len=len(prompt),
                response_id=response_id,
            )
            hermes_client.log_chat_event(
                "chat_response_received",
                user_id=user_id,
                session_id=sess_id,
                role="assistant",
                msg_len=len(text),
                response_id=response_id,
                tool_call_count=len(tool_calls),
            )
            _load_user_sessions.clear()
            st.rerun()


# ============================================================

# ---- Logout (moved from sidebar to page body) ----
st.markdown("\n---")
render_logout_button()

# Footer: Hermes-side count for ops visibility
# ============================================================
st.markdown("---")
try:
    hermes_rows = hermes_client.list_sessions(user_id=user_id)
    hermes_count = len(hermes_rows)
except Exception:
    hermes_count = None
if hermes_count is not None:
    st.caption(
        f"Local sessions: {len(rows)} · Hermes-side sessions (all "
        f"profiles): {hermes_count}"
    )
else:
    st.caption(
        f"Local sessions: {len(rows)} · Hermes-side list unavailable."
    )
