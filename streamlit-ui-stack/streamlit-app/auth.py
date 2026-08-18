# auth.py
# Single-admin username/password auth for the v1.0 customer Streamlit UI
# (BACKLOG #64, Card 3). bcrypt-hashed when available; plain-text fallback
# for v1.0 private deployment (logs a warning, does not crash).
#
# v2 multi-user: extend with a users table lookup + bcrypt verify per row.

from __future__ import annotations

import os
import warnings

import bcrypt
import streamlit as st

from db import get_or_create_user


def _expected_admin_password_hash() -> bytes | None:
    """Return the admin's bcrypt hash bytes, or None if not configured."""
    h = os.environ.get("STREAMLIT_ADMIN_PASSWORD_HASH", "").strip()
    if h:
        return h.encode("utf-8")
    return None


def _expected_admin_password() -> str | None:
    """Return the admin's plain-text password (v1.0 fallback only)."""
    p = os.environ.get("STREAMLIT_ADMIN_PASSWORD", "").strip()
    return p or None


def _admin_username() -> str:
    return os.environ.get("STREAMLIT_ADMIN_USERNAME", "admin")


def _warn_if_plaintext_password() -> None:
    """Emit a single warning at startup if only _PASSWORD (not _HASH) is set."""
    if _expected_admin_password_hash() is None and _expected_admin_password():
        warnings.warn(
            "STREAMLIT_ADMIN_PASSWORD is set but STREAMLIT_ADMIN_PASSWORD_HASH "
            "is not. v1.0 private deployment allows this, but for production "
            "set STREAMLIT_ADMIN_PASSWORD_HASH to a bcrypt hash "
            "(e.g. `python -c \"import bcrypt; print(bcrypt.hashpw(b'YOUR_PW', bcrypt.gensalt()).decode())\"`).",
            stacklevel=2,
        )


def _verify_password(submitted: str) -> bool:
    """Return True if the submitted password matches the admin's expected value.

    Order of preference:
      1. STREAMLIT_ADMIN_PASSWORD_HASH (bcrypt) — production path.
      2. STREAMLIT_ADMIN_PASSWORD (plain) — v1.0 fallback.
    """
    h = _expected_admin_password_hash()
    if h:
        try:
            return bcrypt.checkpw(submitted.encode("utf-8"), h)
        except ValueError:
            # Malformed hash; fall through to plain-text check so we don't
            # lock the operator out if they typo'd the env var.
            pass
    p = _expected_admin_password()
    if p:
        # Constant-time-ish: bcrypt the candidate too (cheap). Avoids leaking
        # the match length through naive str equality.
        return bcrypt.checkpw(
            submitted.encode("utf-8"),
            bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()),
        ) and submitted == p
    return False


def render_login_form() -> bool:
    """Render the login form and return True if user just authenticated.

    Sets st.session_state['authenticated'] = True and
    st.session_state['user'] = <username> on success.
    """
    _warn_if_plaintext_password()

    with st.form("login", clear_on_submit=False):
        st.subheader(f"Sign in to AIAMSBS ({_admin_username()})")
        username = st.text_input("Username", value=_admin_username())
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if not submitted:
        return False

    if username != _admin_username():
        st.error("Invalid credentials.")
        return False
    if not _verify_password(password):
        st.error("Invalid credentials.")
        return False

    # Successful login: create the user row (idempotent), set session state.
    user_id = get_or_create_user(username, password_hash=None)
    st.session_state["authenticated"] = True
    st.session_state["user"] = username
    st.session_state["user_id"] = user_id
    return True


def require_auth() -> bool:
    """Render login form if not authenticated. Return True if authenticated.

    Every page calls this at the top. Returns False if the form was just
    shown (caller should st.stop() to avoid rendering the page body).
    """
    if st.session_state.get("authenticated", False):
        return True
    render_login_form()
    return False


def render_logout_button() -> None:
    """Sidebar logout button. Clears session_state and reruns."""
    with st.sidebar:
        if st.button("Log out", key=f"logout_{id(st.session_state)}"):
            # Log the logout event before clearing session state.
            try:
                from loki_logger import log_event
                log_event("streamlit", {
                    "event": "streamlit_logout",
                    "user_id": st.session_state.get("user_id"),
                    "username": st.session_state.get("user"),
                })
            except Exception:
                pass  # never block logout on logging failure
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
