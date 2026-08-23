# pages/6_Agent_Chat.py — AIAMSBS v1.0 customer Agent Chat.
#
# Card 5 of BACKLOG #64. Single-page chat that NEVER navigates away.
#
# Why no selectbox (2026-08-19): every pattern that uses a selectbox
# to switch between "new" and "continue existing" fights Streamlit's
# widget-state model. The widget\'s own key cannot be written from
# outside the widget callback (StreamlitAPIException); auto-pinning
# via a separate session_state key needs the selectbox\'s index= to
# reset on the rerun (fragile, has edge cases). The cleanest answer:
# no selectbox at all. The page reads st.session_state for the active
# session id and renders either "empty + prompt" or "history + prompt"
# accordingly. The chat_input widget handles its own clearing and
# triggers a script rerun on every submit.
#
# Privacy: chat message BODIES are NEVER written to Loki. Only metadata
# (user_id, session_id, role, msg_len) is shipped.

from __future__ import annotations

import json

import streamlit as st

import hermes_client
from auth import require_auth, render_logout_button
from db import (
    add_chat_message,
    create_chat_session,
    get_chat_session,
    list_chat_messages,
    update_chat_session_response,
)
from settings import load as load_settings
from theme import AIAMSBS_FAVICON, apply_theme, cyberpunk_title, page_header, page_link_button

st.set_page_config(
    page_title="Agent Chat — AIAMSBS", page_icon=AIAMSBS_FAVICON, layout="wide",
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

# The active session id lives in session_state (NOT a widget key) so
# we can freely write/read it from anywhere in the script.
active_session_id: str | None = st.session_state.get("_active_chat_session_id")


# ---- Page header ----
# Layout: title on the left, "New Session" button on the right when
# a session is active. The button clears the active pointer (the
# chat is already saved to chat_sessions + chat_messages — pick up
# later from /Chat_Sessions).
# Title on its own line — full width, no column fiddling.
cyberpunk_title("Agent Chat", "agent_chat")
st.caption(
    "Type a question below and press Enter. Your conversation "
    "stays here — no jumping between pages."
)

# New Session button: right-aligned, full available width. Only shown
# when there's an active session. Putting it below the title (not in
# a column beside it) avoids Streamlit's column-width quirks that
# caused the button to silently disappear in v3.2.
# Always-render the button; disable when no active session.
# This avoids Streamlit's conditional-widget edge case where a
# button conditional on session_state disappears after a chat_input
# rerun until the user navigates away and back.
btn_l, btn_r = st.columns([5, 2])
with btn_r:
    new_btn = st.button(
        "🆕 New Session",
        key="new_session_top",
        type="primary",
        use_container_width=True,
        disabled=(active_session_id is None),
        help=(
            "End this conversation and start a new one. "
            "The current chat is saved to Chat Sessions history."
            if active_session_id
            else "No active session to close. Send a message first."
        ),
    )
    if new_btn:
        hermes_client.log_chat_event(
            "chat_session_closed",
            user_id=user_id,
            session_id=active_session_id,
        )
        st.session_state.pop("_active_chat_session_id", None)
        st.rerun()



# ---- Helpers ----
def _short_id(sid: str) -> str:
    return sid.split("-", 1)[0] if "-" in sid else sid[:8]


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


# ---- Body: empty vs. active ----
if active_session_id is None:
    st.info(
        "🆕 This is a fresh conversation. Type your question below and "
        "press Enter to start it."
    )
else:
    row = get_chat_session(active_session_id, user_id)
    if row is None:
        # Should never happen unless the local DB was wiped. Defensive.
        st.warning(
            f"Session `{_short_id(active_session_id)}` is not in your "
            "local store. The next message will start a new session."
        )
        st.session_state.pop("_active_chat_session_id", None)
        active_session_id = None
    else:
        title = row.get("title") or "(untitled)"
        st.caption(
            f"Session `{_short_id(active_session_id)}` — **{title}**"
        )
        msgs = list_chat_messages(active_session_id)
        for m in msgs:
            _render_message(m)


# ---- Chat input + send handling ----
# chat_input is the ONE widget on this page. It clears itself and
# triggers a script rerun on every submit. That natural cycle is what
# makes "stay on the same page" work.
prompt = st.chat_input("Ask IT_ADMIN…")

if prompt:
    hermes_client.log_chat_event(
        "chat_message_sent",
        user_id=user_id,
        session_id=active_session_id,
        role="user",
        msg_len=len(prompt),
    )

    # Echo the user message immediately.
    with st.chat_message("user"):
        st.markdown(prompt)

    default_title = prompt.strip().splitlines()[0][:60] if prompt.strip() else "Chat"

    is_new = active_session_id is None
    spinner_msg = (
        "Starting new chat with IT_ADMIN…" if is_new
        else "IT_ADMIN is thinking…"
    )

    with st.spinner(spinner_msg):
        try:
            if is_new:
                result = hermes_client.start_chat(
                    user=username, first_message=prompt,
                )
                new_session_id = result["session_id"]
                response_id = result.get("response_id", "")
                # Persist the new session row.
                create_chat_session(
                    session_id=new_session_id,
                    user_id=user_id,
                    title=default_title,
                    last_response_id=response_id,
                )
                hermes_client.log_chat_event(
                    "chat_started",
                    user_id=user_id,
                    session_id=new_session_id,
                    msg_len=len(prompt),
                    response_id=response_id,
                )
                # Pin the active session id for the NEXT render. No
                # explicit rerun — the chat_input submit already
                # triggered one. After the rest of this script body
                # runs (render assistant reply, persist), Streamlit
                # will re-run the whole page, and on that next run
                # active_session_id will be set, so the history
                # renders above the (now-empty) chat_input.
                st.session_state["_active_chat_session_id"] = new_session_id
                active_session_id = new_session_id
            else:
                sess = get_chat_session(active_session_id, user_id)
                prev = sess.get("last_response_id") if sess else None
                if not prev:
                    # Defensive: no prior handle, start a fresh chat.
                    result = hermes_client.start_chat(
                        user=username, first_message=prompt,
                    )
                    response_id = result.get("response_id", "")
                    # If Hermes gave us a NEW id, swap to it.
                    returned_id = result["session_id"]
                    if returned_id != active_session_id:
                        st.session_state["_active_chat_session_id"] = returned_id
                        active_session_id = returned_id
                        create_chat_session(
                            session_id=returned_id,
                            user_id=user_id,
                            title=default_title,
                            last_response_id=response_id,
                        )
                else:
                    result = hermes_client.continue_chat(
                        session_id=active_session_id,
                        message=prompt,
                        previous_response_id=prev,
                    )
                    response_id = result.get("response_id", "")
                    update_chat_session_response(
                        session_id=active_session_id,
                        last_response_id=response_id,
                    )
                hermes_client.log_chat_event(
                    "chat_session_continued",
                    user_id=user_id,
                    session_id=active_session_id,
                    role="user",
                    msg_len=len(prompt),
                    response_id=response_id,
                )
        except hermes_client.HermesAuthError as e:
            st.error(
                "🔑 **Hermes auth failed.** "
                "`HERMES_API_KEY` is missing or rejected by the gateway. "
                f"({e})"
            )
            hermes_client.log_chat_event(
                "chat_error",
                user_id=user_id,
                session_id=active_session_id,
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
                session_id=active_session_id,
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
                session_id=active_session_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            st.stop()

    text = result.get("text", "") or ""
    tool_calls = result.get("tool_calls", []) or []

    # Persist user + assistant messages.
    add_chat_message(
        session_id=active_session_id,
        role="user",
        content=prompt,
    )
    add_chat_message(
        session_id=active_session_id,
        role="assistant",
        content=text,
        response_id=response_id,
        tool_calls_json=json.dumps(tool_calls) if tool_calls else None,
    )
    hermes_client.log_chat_event(
        "chat_response_received",
        user_id=user_id,
        session_id=active_session_id,
        role="assistant",
        msg_len=len(text),
        response_id=response_id,
        tool_call_count=len(tool_calls),
    )

    # Render the assistant reply in the same run so the user sees it
    # immediately. The chat_input submit already triggered a rerun,
    # so on the next render the history will include this exchange.
    with st.chat_message("assistant"):
        if text:
            st.markdown(text)
        else:
            st.caption("(no text in response — see tool calls)")
        if tool_calls:
            with st.expander(
                f"🔧 Tool calls ({len(tool_calls)})", expanded=False
            ):
                for tc in tool_calls:
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
                        st.caption(f"↳ result: `{truncated}`")


# ---- Logout (moved from sidebar to page body) ----
st.markdown("\n---")
render_logout_button()
