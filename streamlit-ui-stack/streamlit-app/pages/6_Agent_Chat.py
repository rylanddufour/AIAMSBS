# pages/6_Agent_Chat.py — AIAMSBS v1.0 customer Agent Chat.
#
# Card 5 of BACKLOG #64. Chat UI that drives the Hermes Responses API
# via hermes_client.start_chat / continue_chat. Conversation history is
# persisted to the local SQLite chat_messages table; per-turn handles
# (response_id) are kept in chat_sessions.last_response_id so the next
# turn can chain via previous_response_id.
#
# Privacy: chat message BODIES are NEVER written to Loki. Only metadata
# (user_id, session_id, role, msg_len) is shipped — see
# hermes_client.log_chat_event. Bodies live only on the customer's box.

from __future__ import annotations

import json
from typing import Any

import streamlit as st

import hermes_client
from auth import require_auth, render_logout_button
from db import (
    add_chat_message,
    create_chat_session,
    db,
    get_chat_session,
    list_chat_messages,
    list_chat_sessions,
    update_chat_session_response,
)
from settings import load as load_settings

st.set_page_config(page_title="Agent Chat — AIAMSBS", page_icon="💬", layout="wide")

if not require_auth():
    st.stop()

settings = load_settings()
user_id: int = int(st.session_state.get("user_id") or 0)
username: str = str(st.session_state.get("user") or "unknown")
if not user_id:
    # require_auth() set user_id from get_or_create_user, but defensive:
    st.error("Session lost its user_id — please log in again.")
    st.stop()

with st.sidebar:
    st.markdown(f"### AIAMSBS\n**Customer:** `{settings.customer_name}`")
    st.markdown(f"**User:** `{username}`")
    st.markdown("---")
    st.markdown("**Agent Chat**")
    st.caption("Stateless per turn — Hermes holds the chain via response_id.")
    st.markdown("---")
    render_logout_button()

# ---- Page header ----
st.title("💬 Agent Chat")
st.caption(
    "Ask IT_ADMIN anything. The conversation chains via Hermes's "
    "`previous_response_id`; you can keep the thread or click "
    "**Clear context** to start fresh."
)

# ---- Session selection ----
# Use ?session_id=<uuid> from the URL (set by 7_Chat_Sessions.py click)
# or fall back to the session_state default. "new" means a fresh session.
url_session_id = st.query_params.get("session_id", None)
default_idx = 0  # "New chat" is the first option

# Pull the user's chat sessions from SQLite for the selector.
# Cached for 5s so reruns during a chat don't re-query.
@st.cache_data(ttl=5, show_spinner=False)
def _load_user_sessions(_user_id: int) -> list[dict]:
    return list_chat_sessions(_user_id)


sessions = _load_user_sessions(user_id)
session_options: list[str] = ["new"] + [s["id"] for s in sessions]
session_labels: dict[str, str] = {"new": "➕ New chat"}
for s in sessions:
    title = (s.get("title") or "(untitled)").strip()
    label = f"{title[:48]}  ·  {s['id'][:8]}"
    session_labels[s["id"]] = label

# Pick default — if the URL said session_id=foo, default to that; else "new".
if url_session_id and url_session_id in session_options:
    default_idx = session_options.index(url_session_id)
    # Clear the URL param so refresh doesn't re-pin it (one-shot selection).
    del st.query_params["session_id"]

selected = st.selectbox(
    "Session",
    options=session_options,
    index=default_idx,
    format_func=lambda sid: session_labels.get(sid, sid),
    key="chat_session_selector",
)
current_session_id: str | None = None if selected == "new" else selected


# ---- Helpers ----
def _short_session_id(sid: str) -> str:
    """Return first 8 chars of a session id (matches Card 4 style)."""
    return sid.split("-", 1)[0] if "-" in sid else sid[:8]


def _render_history(session_id: str) -> None:
    """Render all messages for `session_id` as st.chat_message blocks."""
    msgs = list_chat_messages(session_id)
    for m in msgs:
        with st.chat_message(m["role"]):
            st.markdown(m["content"] or "")
            # Tool calls: render the JSON if present (assistant turns only).
            tcs = m.get("tool_calls_json")
            if tcs and m["role"] == "assistant":
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
                                    f"↳ result (≤200 chars): "
                                    f"`{truncated}`"
                                )


def _render_placeholder_for_new() -> None:
    """What to show when the user picked 'New chat'."""
    st.info(
        "🆕 Type your question below and press Enter to start a new "
        "conversation with IT_ADMIN."
    )


# ---- Render chat body ----
if current_session_id is None:
    _render_placeholder_for_new()
else:
    row = get_chat_session(current_session_id, user_id)
    if row is None:
        # URL param pointed to a session that no longer exists.
        st.warning(
            f"Session `{_short_session_id(current_session_id)}` is not "
            "in your local store. Starting a new chat."
        )
        current_session_id = None
        _render_placeholder_for_new()
    else:
        title = row.get("title") or "(untitled)"
        st.caption(
            f"Session `{_short_session_id(current_session_id)}` — "
            f"**{title}**"
        )
        _render_history(current_session_id)


# ---- Tool calls panel for the latest turn ----
# The card spec says "Below input: 'Tool calls' panel showing any tool
# invocations from `output` array". We already inline tool calls into each
# assistant message (above); the panel below the input shows tool calls
# for the most recent assistant turn if the user is mid-session. This is
# useful when the assistant did multiple tool calls and the user wants a
# flat summary.
if current_session_id is not None:
    last_assistant = None
    for m in reversed(list_chat_messages(current_session_id)):
        if m["role"] == "assistant":
            last_assistant = m
            break
    if last_assistant and last_assistant.get("tool_calls_json"):
        try:
            tcs: list[dict[str, Any]] = json.loads(last_assistant["tool_calls_json"])
        except json.JSONDecodeError:
            tcs = []
        if tcs:
            with st.expander(
                f"🔧 Tool calls (last turn, {len(tcs)})", expanded=False
            ):
                for tc in tcs:
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


# ---- Clear context ----
top_cols = st.columns([1, 6])
with top_cols[0]:
    if st.button(
        "🧹 Clear context",
        key="chat_clear",
        help="Start a brand-new conversation (drops the current session).",
    ):
        hermes_client.log_chat_event(
            "chat_session_cleared",
            user_id=user_id,
            session_id=current_session_id,
        )
        # Switch back to "new" — next message will start a new session.
        st.session_state["chat_session_selector"] = "new"
        st.rerun()


# ---- Chat input + send handling ----
prompt = st.chat_input("Ask IT_ADMIN…")

if prompt:
    hermes_client.log_chat_event(
        "chat_message_sent",
        user_id=user_id,
        session_id=current_session_id,
        role="user",
        msg_len=len(prompt),
    )
    # Echo the user message immediately so the UI feels responsive while
    # Hermes thinks.
    with st.chat_message("user"):
        st.markdown(prompt)

    # Decide: new session or continue?
    is_new = current_session_id is None

    # Pre-compute a default title (first 60 chars of the first message).
    default_title = prompt.strip().splitlines()[0][:60] if prompt.strip() else "Chat"

    with st.spinner(
        "Starting new chat with IT_ADMIN…" if is_new
        else "IT_ADMIN is thinking…"
    ):
        try:
            if is_new:
                result = hermes_client.start_chat(
                    user=username, first_message=prompt,
                )
                current_session_id = result["session_id"]
                create_chat_session(
                    session_id=current_session_id,
                    user_id=user_id,
                    title=default_title,
                    last_response_id=result["response_id"],
                )
                hermes_client.log_chat_event(
                    "chat_started",
                    user_id=user_id,
                    session_id=current_session_id,
                    msg_len=len(prompt),
                    response_id=result["response_id"],
                )
            else:
                sess = get_chat_session(current_session_id, user_id)
                prev = sess.get("last_response_id") if sess else None
                if not prev:
                    # Defensive: if we somehow lost the handle, start fresh.
                    result = hermes_client.start_chat(
                        user=username, first_message=prompt,
                    )
                    current_session_id = result["session_id"]
                    create_chat_session(
                        session_id=current_session_id,
                        user_id=user_id,
                        title=default_title,
                        last_response_id=result["response_id"],
                    )
                else:
                    result = hermes_client.continue_chat(
                        session_id=current_session_id,
                        message=prompt,
                        previous_response_id=prev,
                    )
                    update_chat_session_response(
                        session_id=current_session_id,
                        last_response_id=result["response_id"],
                    )
                hermes_client.log_chat_event(
                    "chat_session_continued",
                    user_id=user_id,
                    session_id=current_session_id,
                    role="user",
                    msg_len=len(prompt),
                    response_id=result["response_id"],
                )
        except hermes_client.HermesAuthError as e:
            st.error(
                "🔑 **Hermes auth failed.** "
                f"`HERMES_API_KEY` is missing or rejected by the gateway. "
                f"({e})"
            )
            hermes_client.log_chat_event(
                "chat_error",
                user_id=user_id,
                session_id=current_session_id,
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
                session_id=current_session_id,
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
                session_id=current_session_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            st.stop()

    # Persist the user message (now that we have a session id).
    add_chat_message(
        session_id=current_session_id,
        role="user",
        content=prompt,
    )

    # Render the assistant reply.
    text = result.get("text", "") or ""
    tool_calls = result.get("tool_calls", []) or []
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

    add_chat_message(
        session_id=current_session_id,
        role="assistant",
        content=text,
        response_id=result.get("response_id", ""),
        tool_calls_json=(
            json.dumps(tool_calls) if tool_calls else None
        ),
    )
    hermes_client.log_chat_event(
        "chat_response_received",
        user_id=user_id,
        session_id=current_session_id,
        role="assistant",
        msg_len=len(text),
        response_id=result.get("response_id", ""),
        tool_call_count=len(tool_calls),
    )

    # Invalidate the cached session list (new session may have appeared).
    # st.cache_data exposes .clear() on the wrapper to drop the cached
    # value so the next render re-queries the DB.
    try:
        _load_user_sessions.clear()
    except Exception:
        pass
    st.rerun()
