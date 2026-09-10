# pages/1_Settings.py — editable per-customer configuration.
#
# Each field is editable. Values are persisted to the ui_settings
# SQLite table and override env-derived defaults on read (see
# settings.py). Reset to default = empty value = falls back to env.
#
# Idempotent. Backed up by the install_hermes_api script.

from __future__ import annotations

import hmac

import bcrypt
import streamlit as st

from auth import (
    _admin_password_source,
    _expected_admin_password,
    _expected_admin_password_hash,
    require_auth,
    render_logout_button,
)
from db import (
    get_ui_settings,
    reset_all_ui_settings,
    set_ui_settings,
)
from settings import EDITABLE_FIELDS, load as load_settings
from theme import AIAMSBS_FAVICON, apply_theme, cyberpunk_title, page_header, page_link_button, section_header

st.set_page_config(page_title="Settings — AIAMSBS", page_icon=AIAMSBS_FAVICON, layout="wide")

if not require_auth():
    st.stop()

# Theme (BACKLOG #72 — Dark Cyber palette). Applied AFTER
# auth so the login form is the only place the default
# light theme bleeds through.
apply_theme()

settings = load_settings()

cyberpunk_title("Settings", "settings")
st.caption(
    "Edit URLs to point at the host IP (e.g. http://192.168.0.220:9119) "
    "instead of the docker-internal hostname. Values persist in the local "
    "SQLite database and override env-derived defaults."
)


# ---- Read the current persisted overrides ----
overrides = get_ui_settings()


def _current_value(field: dict) -> str:
    """Return the effective value for this field: override if set,
    else the env default shown in EDITABLE_FIELDS."""
    override = overrides.get(field["key"])
    if override is not None and override != "":
        return override
    return field["default"]


# ---- Editable form ----
section_header("Editable configuration")

with st.form("settings_form"):
    new_values: dict[str, str] = {}

    # Group fields by their `group` key, preserving the order in
    # EDITABLE_FIELDS. Render each group in its own sub-section,
    # but skip the Backend URLs group — those are still shown in
    # the 'Current effective values' table below but are not
    # editable (Ryland 2026-08-19 decision).
    from collections import OrderedDict
    FORM_GROUPS = ("Quick Links", "Identity")
    grouped: "OrderedDict[str, list[dict]]" = OrderedDict()
    for field in EDITABLE_FIELDS:
        g = field.get("group", "Other")
        if g not in FORM_GROUPS:
            continue
        grouped.setdefault(g, []).append(field)

    for group_name, group_fields in grouped.items():
        st.markdown(f"#### {group_name}")
        st.caption(
            "🔧 Backend URLs are used for /health probes (container-internal)."
            if group_name == "Backend URLs" else (
                "🌐 Quick Links are browser-facing URLs (host IP). Edit these "
                "to point at the host IP so the Home page buttons open in "
                "your browser."
                if group_name == "Quick Links" else ""
            )
        )
        for field in group_fields:
            key = field["key"]
            label = field["label"]
            current = _current_value(field)
            is_overridden = (
                overrides.get(key) is not None and overrides.get(key) != ""
            )

            hint = " (override)" if is_overridden else ""
            val = st.text_input(
                f"{label}{hint}",
                value=current,
                key=f"sf_{key}",
                help=field["help"],
            )
            new_values[key] = val.strip()
        st.markdown("")

    st.markdown("---")
    save_cols = st.columns(2)
    with save_cols[0]:
        save = st.form_submit_button(
            "Save", type="primary", use_container_width=True,
        )
    with save_cols[1]:
        reset = st.form_submit_button(
            "Reset", use_container_width=True,
        )

if save:
    # Only persist values that actually changed from defaults.
    to_persist: dict[str, str] = {}
    for field in EDITABLE_FIELDS:
        key = field["key"]
        new = new_values.get(key, "")
        default = field["default"]
        if new == "" or new == default:
            # Empty OR matches default -> clear the override (so the
            # env default takes effect if env ever changes).
            to_persist[key] = ""
        else:
            to_persist[key] = new
    set_ui_settings(to_persist)
    st.success(f"Saved {sum(1 for v in to_persist.values() if v != '')} override(s).")
    st.rerun()

if reset:
    reset_all_ui_settings()
    st.success("✅ All overrides cleared. Env defaults are now in effect.")
    st.rerun()


# ---- Admin Account (BACKLOG #77 — rotate admin password via UI) ----
# Stored as a bcrypt hash in ui_settings (override > env). Auth re-reads
# the hash on every login, so no `docker compose restart` is needed.
# Render order: status caption → section header + help popover → form.

_AUTH_SOURCE_LABELS = {
    "override-hash":  "🔐 Auth: bcrypt override",
    "env-hash":       "🔐 Auth: bcrypt env",
    "override-plain": "🔐 Auth: plain-text override",
    "env-plain":      "🔐 Auth: plain-text env fallback",
    "unconfigured":   "🔐 Auth: not configured",
}
st.caption(_AUTH_SOURCE_LABELS.get(_admin_password_source(), "🔐 Auth: unknown"))

_admin_header_cols = st.columns([0.85, 0.15])
with _admin_header_cols[0]:
    section_header("Admin Account")
with _admin_header_cols[1]:
    # BACKLOG #73 multi-paragraph help pattern: st.popover("?") instead of
    # help= on the widget, so the content renders with markdown breaks.
    with st.popover("?"):
        st.markdown(
            "- The new password takes effect on the **next login** — no "
            "`docker compose restart` needed.\n"
            "- All currently-active sessions stay logged in (their "
            "bcrypt-verified cookies/session-state are not invalidated "
            "by a hash change).\n"
            "- To recover if you forget the password: "
            "`docker exec streamlit-ui env | grep STREAMLIT_ADMIN` "
            "shows the env fallback; edit `docker-compose.yml` defaults "
            "+ `docker compose up -d streamlit-ui`."
        )


# Show-passwords toggle: streamlit's `type` is set at widget creation,
# so we can't toggle it after the fact. Pattern (a) from BACKLOG #77 —
# bake the flag into the widget key, so flipping the checkbox creates a
# brand-new widget with the new `type`. The old widget's value is
# discarded (clean), and the new widget is empty on each flip (the
# caller has to retype, which is fine for a password field).
_show = st.session_state.get("show_pw", False)
_pw_type = "default" if _show else "password"

with st.form("admin_password_form", clear_on_submit=True):
    new_pw = st.text_input(
        "New password",
        type=_pw_type,
        key=f"new_pw_{int(_show)}",
    )
    confirm_pw = st.text_input(
        "Confirm new password",
        type=_pw_type,
        key=f"confirm_pw_{int(_show)}",
    )
    show_pw = st.checkbox(
        "Show passwords",
        key="show_pw",
        value=_show,
    )
    # Render the Save button inside the form so Enter-submits work.
    # We compute the "disabled" look by validating eagerly and
    # only showing an error block; the button is always present.
    submit = st.form_submit_button(
        "Update password", type="primary", use_container_width=True,
    )

# Validation runs both on submit (for errors) and on every render so the
# operator sees problems as they type. The Save button stays enabled —
# clicking it just surfaces the same error message (streamlit doesn't
# support disabling a form_submit_button after construction).
_validation_errors: list[str] = []
if submit or new_pw or confirm_pw:
    if not new_pw and not confirm_pw:
        pass  # empty form, nothing to validate yet
    elif new_pw != confirm_pw:
        _validation_errors.append("Passwords do not match")
    elif len(new_pw) < 12:
        _validation_errors.append("Password must be at least 12 characters")
    else:
        # "differs from current" check: try the bcrypt hash first, fall
        # back to the plain-text env fallback via constant-time compare.
        _matches_current = False
        _cur_hash = _expected_admin_password_hash()
        if _cur_hash:
            try:
                _matches_current = bcrypt.checkpw(
                    new_pw.encode("utf-8"), _cur_hash,
                )
            except ValueError:
                _matches_current = False
        elif _expected_admin_password():
            _cur_plain = _expected_admin_password() or ""
            _matches_current = hmac.compare_digest(
                new_pw.encode("utf-8"),
                _cur_plain.encode("utf-8"),
            )
        if _matches_current:
            _validation_errors.append(
                "New password must differ from current"
            )

# Surface any validation errors.
for _err in _validation_errors:
    st.error(_err)

if submit and not _validation_errors and new_pw and confirm_pw:
    # Hash with a fresh salt. bcrypt.gensalt() default cost factor (12)
    # matches the existing Card 3 login path so timing stays consistent.
    _new_hash = bcrypt.hashpw(
        new_pw.encode("utf-8"), bcrypt.gensalt(),
    ).decode("utf-8")
    # Write the bcrypt override and clear the plain-text override (if any)
    # so the plain-text fallback can't accidentally re-activate on the
    # next login. Empty value -> row is deleted by set_ui_settings.
    set_ui_settings({
        "STREAMLIT_ADMIN_PASSWORD_HASH": _new_hash,
        "STREAMLIT_ADMIN_PASSWORD": "",
    })
    # Wipe the password inputs from session_state so the plain text
    # doesn't linger in the form after a successful save. The widget
    # keys were suffix-tagged with the current `show_pw` value; deleting
    # both possible suffixes covers whichever one is live.
    for _suffix in ("0", "1"):
        for _k in (f"new_pw_{_suffix}", f"confirm_pw_{_suffix}"):
            st.session_state.pop(_k, None)
    # Audit trail: mirror the streamlit_login / streamlit_logout pattern
    # in auth.py so password changes show up in Loki alongside the
    # existing session events.
    try:
        from loki_logger import log_event
        log_event("streamlit", {
            "event": "streamlit_password_change",
            "user_id": st.session_state.get("user_id"),
            "username": st.session_state.get("user"),
        })
    except Exception:
        pass  # logging failures must never block a successful save
    st.success(
        "Password updated. New password takes effect on the next login "
        "(no restart needed)."
    )
    st.rerun()


# ---- Read-only display of current effective values ----
section_header("Current effective values")
st.caption("What the rest of the app sees right now (override > env > default).")
for group_name in sorted({f.get("group", "Other") for f in EDITABLE_FIELDS}):
    group_fields = [
        f for f in EDITABLE_FIELDS if f.get("group", "Other") == group_name
    ]
    if not group_fields:
        continue
    st.markdown(f"##### {group_name}")
    st.table([
        {
            "key": field["label"],
            "value": _current_value(field),
            "source": "override" if (
                overrides.get(field["key"]) not in (None, "")
            ) else "env",
        }
        for field in group_fields
    ])


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


# ---- Logout (moved from sidebar to page body) ----
render_logout_button()