# pages/1_Settings.py — editable per-customer configuration.
#
# Each field is editable. Values are persisted to the ui_settings
# SQLite table and override env-derived defaults on read (see
# settings.py). Reset to default = empty value = falls back to env.
#
# Idempotent. Backed up by the install_hermes_api script.

from __future__ import annotations

import streamlit as st

from auth import require_auth, render_logout_button
from db import (
    get_ui_settings,
    reset_all_ui_settings,
    set_ui_settings,
)
from settings import EDITABLE_FIELDS, load as load_settings
from theme import AIAMSBS_FAVICON, apply_theme, cyberpunk_title, page_header, page_link_button

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
st.subheader("Editable configuration")

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
    save_cols = st.columns([1, 1, 6])
    with save_cols[0]:
        save = st.form_submit_button(
            "💾 Save", type="primary", use_container_width=True,
        )
    with save_cols[1]:
        reset = st.form_submit_button(
            "🧹 Reset all to defaults",
            use_container_width=True,
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
    st.success(f"✅ Saved {sum(1 for v in to_persist.values() if v != '')} override(s).")
    st.rerun()

if reset:
    reset_all_ui_settings()
    st.success("✅ All overrides cleared. Env defaults are now in effect.")
    st.rerun()


# ---- Read-only display of current effective values ----
st.markdown("---")
st.subheader("Current effective values")
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
st.markdown("---")
render_logout_button()