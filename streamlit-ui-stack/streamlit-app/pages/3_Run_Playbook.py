# pages/3_Run_Playbook.py — AIAMSBS v1.0 customer Run Playbook flow.
#
# Card 4 of BACKLOG #64 (now Card 8's inline-inventory variant). The
# headline v1.0 feature: a 5-stage Streamlit flow that lets an
# authenticated operator pick a playbook + hosts + mode + credentials,
# REQUIRES a confirmation click, then calls the aiamsbs-ansible-runner
# HTTP API with an HMAC-signed body. Every run is recorded in the local
# SQLite (Card 3 schema) and emits Loki events for the audit trail.
#
# Card 8 (BACKLOG #64 v1.0-private): hosts are sourced live from
# inventory-mcp via MCP Streamable-HTTP and joined into a SINGLE inline
# inventory string of the form
#   "host01 ansible_host=10.0.0.1 ansible_user=opc ansible_connection=ssh,host02 ..."
# which is passed as the `-i` arg to ansible-playbook. There are NO
# inventory files on disk and NO file picker in the UI. The /ansible
# bind mount of `inventory/` remains for the empty localhost file (harmless).
#
# SAFETY:
#   * The Confirmation screen is THE safety boundary. There is no
#     "auto-confirm" flag, no programmatic skip, no agent chat shortcut
#     (Card 5 lives in a separate page with a separate entry path).
#   * raw credential values never land in the DB — see
#     hermes_client.redact_secrets and the `redact_for_event` helper
#     here.
#   * apply mode shows an extra warning panel. The Confirm button is
#     still red and is the only way to actually start the run.
#
# AUTH: every page calls require_auth() at the top; sidebar carries the
# logout button.

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import streamlit as st
import yaml

from auth import require_auth, render_logout_button
from db import db
from hermes_client import (
    log_run_event,
    new_run_id,
    payload_is_clean,
    redact_secrets,
    short_run_id,
)
from mcp_client import (
    MCPFormatError,
    MCPUnavailableError,
    MCPToolError,
    inventory_list,
)
from settings import load as load_settings
from theme import AIAMSBS_FAVICON, apply_theme, cyberpunk_title, page_header, page_link_button, section_header

st.set_page_config(page_title="Run Playbook — AIAMSBS", page_icon=AIAMSBS_FAVICON, layout="wide")

if not require_auth():
    st.stop()

# Theme (BACKLOG #72 — Dark Cyber palette). Applied AFTER
# auth so the login form is the only place the default
# light theme bleeds through.
apply_theme()

settings = load_settings()

with st.sidebar:
    render_logout_button()

cyberpunk_title("Run Playbook", "run_playbook")
st.caption(
    "Pick a playbook, choose target inventory, confirm credentials, "
    "then **review and confirm** before the runner executes."
)

# ---------------------------------------------------------------------------
# Filesystem roots (Card 4 RO bind mounts of aiamsbs-ansible's directories).
# ---------------------------------------------------------------------------
PLAYBOOK_ROOT = Path("/ansible/playbooks")

# Card 8 (BACKLOG #64 v1.0-private): inventory is sourced LIVE from
# inventory-mcp via MCP Streamable-HTTP (POST http://inventory-mcp:8000/mcp
# JSON-RPC tools/call list_devices). The empty inventory/static/localhost
# file remains on disk for backwards compat but is never selected by the UI.

# Cache device universe for 30s so repeated page loads don't hammer MCP.
@st.cache_data(ttl=30, show_spinner=False)
def _device_universe() -> tuple[list[dict], str | None]:
    """Fetch all devices from inventory-mcp. Returns (rows, error_msg).

    Live data only — there are no inventory files to read. We tolerate
    MCP being unavailable and surface the error as a string instead of
    raising so the page renders an actionable banner.
    """
    try:
        rows = inventory_list(query=None)
        # Defensive filter: the multiselect only needs hostname + ip.
        rows = [r for r in rows if (r.get("hostname") or r.get("device_id"))]
        return rows, None
    except MCPUnavailableError as e:
        return [], f"Inventory service unavailable: {e}"
    except MCPFormatError as e:
        return [], f"non-MCP response: {str(e)[:300]}"
    except MCPToolError as e:
        return [], f"Inventory tool error: {e}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"

# Where the runner writes NDJSON (Card 2 mount). The streamlit shell has
# /home/ansible/.hermes/logs/aiamsbs-streamlit set as LOKI_LOG_DIR — log
# events here land in alloy's file tailer and arrive in Loki.

# ---------------------------------------------------------------------------
# Session state — stages 1..5 + a "run_in_progress" lock to prevent double
# submission if the user clicks Confirm twice.
# ---------------------------------------------------------------------------
_SS = st.session_state


def _ss_init() -> None:
    defaults = {
        "stage": 1,
        # Runner-relative path: what the aiamsbs-ansible-runner needs in its
        # POST body. The runner `docker exec`s into the ansible container
        # with workdir=/ansible, so it expects paths like
        # "playbooks/generated/hello.yml" — NOT picker-relative
        # "generated/hello.yml" (BACKLOG #67 fix).
        "playbook_path": None,
        "playbook_display": None,  # picker-relative ("generated/hello.yml") for UI
        "playbook_meta": None,  # {name, description}
        # Card 8: hosts come from inventory-mcp, not files. We keep a list
        # of selected device dicts (each with hostname/ip_address) so the
        # inline inventory string can be regenerated at Confirm time.
        "selected_devices": [],   # list[dict] from inventory-mcp
        "mode": "check",         # "check" | "apply"
        "creds": {               # collected but never persisted
            "ssh_user": "",
            "ssh_key_path": "",
            "ssh_password": "",
            "become_password": "",
        },
        "extra_vars": {},        # list of {key, value} for UI; converted to dict on confirm
        "run_id": None,
        "confirm_started": False,
        "run_error": None,       # str | None — surfaced as banner
        "events_count": 0,
        "final_exit_code": None,
        "auth_failed": False,
    }
    for k, v in defaults.items():
        _SS.setdefault(k, v)


_ss_init()


def _reset_flow() -> None:
    """Clear run state and return to Stage 1. Called by Cancel button
    and after a successful cancel/complete."""
    for k in list(_SS.keys()):
        if k.startswith("__") or k in {
            "authenticated", "user", "user_id",
            "stage", "playbook_path", "playbook_meta",
            "selected_devices",
            "mode", "creds", "extra_vars",
            "run_id", "confirm_started", "run_error",
            "events_count", "final_exit_code", "auth_failed",
        }:
            del _SS[k]
    _ss_init()
    _SS["stage"] = 1


# ---------------------------------------------------------------------------
# Filesystem listing helpers
# ---------------------------------------------------------------------------

def _list_playbooks() -> list[dict]:
    """Return [{path: "customer/foo.yml", rel: "customer/foo.yml",
    abs_path: "...", name, description}] sorted by rel path."""
    out: list[dict] = []
    if not PLAYBOOK_ROOT.exists():
        return out
    for sub in ("customer", "generated"):
        base = PLAYBOOK_ROOT / sub
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in (".yml", ".yaml"):
                rel = f"{sub}/{p.relative_to(base)}"
                out.append({
                    "rel": rel,
                    "abs_path": str(p),
                    "name": None,
                    "description": None,
                })
    return out


def _parse_playbook_meta(path: Path) -> dict:
    """Read the first top-level list item's `name:` and `description:`."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except Exception:
        return {"name": None, "description": None}
    if isinstance(doc, list) and doc:
        first = doc[0] if isinstance(doc[0], dict) else {}
        return {
            "name": first.get("name") if isinstance(first, dict) else None,
            "description": first.get("description") if isinstance(first, dict) else None,
        }
    if isinstance(doc, dict):
        return {"name": doc.get("name"), "description": doc.get("description")}
    return {"name": None, "description": None}


# ---------------------------------------------------------------------------
# Stage 1: Playbook selection
# ---------------------------------------------------------------------------

def _stage1() -> None:
    section_header("Stage 1 — Select playbook")
    playbooks = _list_playbooks()
    if not playbooks:
        st.error(
            "No playbooks found under `/ansible/playbooks/{customer,generated}/`. "
            "The streamlit-ui container must have read access to the playbook "
            "directory mounted by the aiamsbs-ansible-stack."
        )
        st.stop()

    path_filter = st.radio(
        "Show playbooks from",
        options=["all", "customer", "generated"],
        index=0,
        horizontal=True,
        key="pb_filter",
    )
    filtered = [p for p in playbooks if path_filter == "all" or p["rel"].startswith(path_filter + "/")]

    # Parse metadata lazily so the page stays responsive with many playbooks.
    options = []
    meta_cache: dict[str, dict] = {}
    for p in filtered:
        meta = _parse_playbook_meta(Path(p["abs_path"]))
        meta_cache[p["rel"]] = meta
        label = f"{meta.get('name') or p['rel']}  ({p['rel']})"
        options.append(label)

    if not filtered:
        st.info(f"No playbooks match filter '{path_filter}'.")
        return

    choice = st.selectbox("Playbook", options=options, key="pb_choice")
    sel = filtered[options.index(choice)]
    meta = meta_cache[sel["rel"]]
    if meta.get("name"):
        st.caption(f"**name:** {meta['name']}")
    if meta.get("description"):
        st.caption(f"**description:** {meta['description']}")

    cols = st.columns([1, 4])
    with cols[0]:
        if st.button("Next →", key="pb_next", type="primary"):
            # BACKLOG #67: prefix with "playbooks/" so the runner's
            # workdir=/ansible resolves the file correctly. The previous
            # version stored the picker-relative path (e.g. "generated/foo.yml")
            # which made the runner's `ansible-playbook generated/foo.yml`
            # fail with "the file was not found".
            _SS["playbook_path"] = f"playbooks/{sel['rel']}"
            _SS["playbook_display"] = sel["rel"]
            _SS["playbook_meta"] = meta
            log_run_event("playbook_selected", run_id=_SS["run_id"] or "(none-yet)",
                          playbook=sel["rel"], name=meta.get("name"))
            _SS["stage"] = 2
            st.rerun()


# ---------------------------------------------------------------------------
# Stage 2: Select hosts (live from inventory-mcp, no inventory file)
# ---------------------------------------------------------------------------

def _build_inline_inventory(devices: list[dict], ssh_user: str = "") -> str:
    """Build the inline `-i` string for ansible-playbook.

    Per Card 8 (BACKLOG #64 v1.0-private): no inventory files on disk.
    The pattern is the one Ryland verified 2026-08-19:
        ansible-playbook -i "host1,host2,host3," playbook.yml \\
          -e "ansible_user=... ansible_password=*** ansible_connection=ssh"
    Each selected device becomes a BARE hostname. No `ansible_host=`,
    no `ansible_user=`, no `ansible_connection=` in the inline string —
    vars ALL ride on `--extra-vars` (handled by the runner from
    Stage 3 credentials + the extra-vars form).

    The trailing comma is mandatory: it tells ansible's host_list plugin
    "this is a host list, not a filename". Without it (`host1,host2`),
    ansible tries to open the string as a file path and reports
    "Unable to parse /ansible/host1,host2 as an inventory source".

    The `ssh_user` argument is kept for signature compatibility but is
    IGNORED — per-host vars now flow through extra_vars. See
    `_extra_vars_with_creds()` (Stage 3 credentials → runner body).

    Verified 2026-08-19 by Ryland's pattern test (3 candidates: single host,
    two hosts, IP-only — all parsed correctly by ansible).

    Returns "" if devices is empty. Caller is responsible for refusing to
    POST when the result is empty.
    """
    if not devices:
        return ""
    fragments: list[str] = []
    for d in devices:
        # Prefer hostname if present. Fall back to ip_address only if
        # hostname is missing — no native ansible_host support via -e
        # (it would apply globally, not per-host). When hostname is empty
        # but ip is present, the operator can run with `--check` only or
        # edit the inventory row to add a hostname.
        hostname = (d.get("hostname") or "").strip()
        if not hostname:
            ip = (d.get("ip_address") or "").strip()
            if not ip:
                continue
            hostname = ip
        fragments.append(hostname)
    if not fragments:
        return ""
    # Bare hostnames, comma-separated, mandatory trailing comma.
    return ",".join(fragments) + ","


def _stage2() -> None:
    section_header("Stage 2 — Select hosts")
    st.write(
        f"**Playbook:** `{_SS['playbook_display'] or _SS['playbook_path']}`  —  "
        f"name=`{(_SS['playbook_meta'] or {}).get('name') or '?'}`"
    )
    if st.button("← Back", key="inv_back"):
        _SS["stage"] = 1
        st.rerun()

    devices, err_msg = _device_universe()
    if err_msg:
        st.error(err_msg)
        if st.button("Retry inventory fetch", key="inv_retry"):
            st.cache_data.clear()
            st.rerun()
        return

    if not devices:
        st.warning("Inventory returned no devices.")
        return

    # Build the display label: "hostname (ip)" — hostnames are unique
    # because the inventory schema enforces that on insert. We index by
    # hostname so a multiselect can return just the names; we then look
    # up the matching dict at Confirm time.
    device_by_host: dict[str, dict] = {}
    labels: list[str] = []
    for d in devices:
        hn = d.get("hostname") or d.get("device_id")
        if not hn:
            continue
        ip = d.get("ip_address") or "?"
        label = f"{hn} ({ip})"
        device_by_host[str(hn)] = d
        labels.append(label)

    st.caption(
        f"**{len(devices)} device(s)** fetched from inventory-mcp "
        f"(cached 30s). Pick one or more to run this playbook against."
    )

    selected = st.multiselect(
        "Target hosts",
        options=sorted(labels),
        default=[],
        key="inv_multiselect",
        help="Each selected host becomes a fragment in the inline -i inventory.",
    )

    # Translate the label list back to hostname strings and resolve to
    # the original device dicts.
    selected_hosts = [s.split(" (")[0] for s in selected]
    _SS["selected_devices"] = [device_by_host[h] for h in selected_hosts if h in device_by_host]

    cols = st.columns([1, 1, 4])
    with cols[0]:
        if st.button("← Back", key="inv_back2"):
            _SS["stage"] = 1
            st.rerun()
    with cols[1]:
        # Next is disabled until at least one host is selected.
        next_disabled = not _SS["selected_devices"]
        if st.button(
            "Next →",
            key="inv_next",
            type="primary",
            disabled=next_disabled,
            help="Select at least one host to continue." if next_disabled else None,
        ):
            log_run_event(
                "inventory_selected",
                run_id=_SS["run_id"] or "(none-yet)",
                host_count=len(_SS["selected_devices"]),
                hosts=sorted(selected_hosts),
            )
            _SS["stage"] = 3
            st.rerun()


# ---------------------------------------------------------------------------
# Stage 3: Mode + credentials
# ---------------------------------------------------------------------------

def _stage3() -> None:
    section_header("Stage 3 — Mode + credentials")
    selected = _SS["selected_devices"]
    selected_hosts = sorted(
        d.get("hostname") or d.get("device_id") or "?"
        for d in selected
    )
    st.write(
        f"**Targets:** {len(selected)} host(s) — "
        + (", ".join(f"`{h}`" for h in selected_hosts)
           if selected_hosts else "_none selected_")
    )
    if st.button("← Back", key="cred_back"):
        _SS["stage"] = 2
        st.rerun()

    # Mode
    mode_choice = st.radio(
        "Mode",
        options=["check", "apply"],
        index=0 if _SS["mode"] == "check" else 1,
        format_func=lambda x: "--check (dry run, recommended)" if x == "check" else "--apply (modifies target system)",
        key="mode_choice",
        horizontal=True,
    )
    _SS["mode"] = mode_choice
    if mode_choice == "apply":
        st.warning(
            "⚠️ **Apply mode will modify the target system.** Past runs have "
            "caused irreversible changes on customer hardware. Confirm you "
            "have a backup and rollback plan."
        )
        if len(selected) > 10:
            st.error(
                f"This will affect **{len(selected)} hosts** in "
                "production. Verify the multiselect above is intentional."
            )

    st.markdown("**Credentials (for the inventory target)**")
    cols = st.columns(2)
    with cols[0]:
        _SS["creds"]["ssh_user"] = st.text_input(
            "SSH user", value=_SS["creds"].get("ssh_user", ""), key="cred_user"
        )
        _SS["creds"]["ssh_key_path"] = st.text_input(
            "SSH key file path (e.g. /ansible/keys/id_ed25519)",
            value=_SS["creds"].get("ssh_key_path", ""),
            key="cred_key",
        )
    with cols[1]:
        _SS["creds"]["ssh_password"] = st.text_input(
            "SSH password (never persisted)", value="", type="password", key="cred_pw"
        )
        _SS["creds"]["become_password"] = st.text_input(
            "Become (sudo) password", value="", type="password", key="cred_become"
        )
    st.caption(
        "Credentials are passed to ansible via `--extra-vars ansible_ssh_pass / "
        "ansible_become_pass` for the live POST only and are NEVER written to "
        "playbook_run_events.payload."
    )

    # Extra vars
    st.markdown("**--extra-vars**")
    n_extra = st.number_input(
        "Number of extra vars", min_value=0, max_value=20, value=len(_SS["extra_vars"]),
        key="n_extra",
    )
    n_extra = int(n_extra)
    extra_pairs: list[tuple[str, str]] = []
    for i in range(n_extra):
        c1, c2 = st.columns(2)
        with c1:
            k = st.text_input(f"key #{i+1}", key=f"evk_{i}")
        with c2:
            v = st.text_input(f"value #{i+1}", key=f"evv_{i}", type="default")
        if k:
            extra_pairs.append((k, v))
    _SS["extra_vars"] = dict(extra_pairs)

    cols = st.columns([1, 1, 4])
    with cols[0]:
        if st.button("← Back", key="cred_back2"):
            _SS["stage"] = 2
            st.rerun()
    with cols[1]:
        if st.button("Next →", key="cred_next", type="primary"):
            log_run_event(
                "credentials_collected",
                run_id=_SS["run_id"] or "(none-yet)",
                mode=_SS["mode"],
                ssh_user_set=bool(_SS["creds"]["ssh_user"]),
                ssh_password_set=bool(_SS["creds"]["ssh_password"]),
                become_password_set=bool(_SS["creds"]["become_password"]),
                ssh_key_set=bool(_SS["creds"]["ssh_key_path"]),
                extra_var_count=len(_SS["extra_vars"]),
            )
            _SS["stage"] = 4
            st.rerun()


# ---------------------------------------------------------------------------
# Stage 4: Confirmation (THE safety boundary)
# ---------------------------------------------------------------------------

def _render_summary_card() -> None:
    pb = _SS["playbook_path"]
    selected = _SS["selected_devices"]
    selected_hosts = sorted(
        d.get("hostname") or d.get("device_id") or "?"
        for d in selected
    )
    mode = _SS["mode"]

    section_header("Review & confirm")
    with st.container(border=True):
        st.markdown(f"**Playbook:** `{_SS.get('playbook_display') or pb}`")
        meta = _SS.get("playbook_meta") or {}
        if meta.get("name"):
            st.markdown(f"&nbsp;&nbsp;name: `{meta['name']}`")
        if meta.get("description"):
            st.markdown(f"&nbsp;&nbsp;description: _{meta['description']}_")
        st.markdown(f"**Inventory source:** `inventory-mcp` (live, MCP Streamable-HTTP)")
        st.markdown(f"**Hosts selected:** {len(selected)}")
        if selected_hosts:
            st.markdown(
                "&nbsp;&nbsp;" + ", ".join(f"`{h}`" for h in selected_hosts)
            )
        # Inline inventory preview — what will actually be passed as -i.
        inline_preview = _build_inline_inventory(
            selected, _SS["creds"].get("ssh_user", "")
        )
        if inline_preview:
            with st.expander("Inline inventory preview (-i argument)", expanded=False):
                st.code(inline_preview, language="text")
        st.markdown(f"**Mode:** `{mode}`" + ("  ⚠️ APPLY" if mode == "apply" else ""))
        if _SS["extra_vars"]:
            st.markdown("**--extra-vars:**")
            for k, v in _SS["extra_vars"].items():
                st.markdown(f"&nbsp;&nbsp;`{k}` = `{v}`")
        st.markdown(
            "**Credentials** *(sent over the wire only; never persisted)*: "
            "ssh_user=" + ("yes" if _SS["creds"]["ssh_user"] else "no")
            + " · ssh_key=" + ("yes" if _SS["creds"]["ssh_key_path"] else "no")
            + " · ssh_password=" + ("yes" if _SS["creds"]["ssh_password"] else "no")
            + " · become_password=" + ("yes" if _SS["creds"]["become_password"] else "no")
        )


def _stage4() -> None:
    section_header("Stage 4 — Confirmation")
    if st.button("← Back", key="conf_back"):
        _SS["stage"] = 3
        st.rerun()

    _render_summary_card()

    # Card 8: Run button is disabled when no hosts are selected. The label
    # is also context-dependent so the operator sees what to do next.
    has_hosts = bool(_SS["selected_devices"])
    run_label = "Run Playbook" if has_hosts else "Select hosts to run"

    cols = st.columns([1, 1, 5])
    with cols[0]:
        # Cancel: explicit primary (blue), DEFAULT focus.
        if st.button("Cancel", key="conf_cancel", type="primary", use_container_width=True):
            _reset_flow()
            st.rerun()
    with cols[1]:
        # Run Playbook / Select hosts to run — disabled when empty.
        # Requires a real click — streamlit's default focus is the first
        # widget (Cancel) so the operator must consciously start the run.
        if st.button(
            run_label,
            key="conf_confirm",
            type="secondary",
            use_container_width=True,
            disabled=not has_hosts,
            help="Select at least one host in Stage 2 to enable."
            if not has_hosts else None,
        ):
            if _SS["confirm_started"]:
                st.warning("Run already in progress — wait for it to finish.")
            else:
                _SS["confirm_started"] = True
                _SS["stage"] = 5
                st.rerun()


# ---------------------------------------------------------------------------
# Stage 5: Run live + result
# ---------------------------------------------------------------------------

def _extra_vars_with_creds() -> dict:
    """Merge user-supplied extra-vars with ansible_* credential keys.

    Anything in `creds` that the user filled in lands under
    ansible_ssh_user / ansible_ssh_pass / ansible_ssh_private_key_file /
    ansible_become_pass. Empty string → omit.

    Always sets `ansible_connection=ssh` because the inline inventory
    (Ryland's pattern, see _build_inline_inventory) is bare hostnames —
    no per-host connection type is encoded. The runner passes this whole
    dict via `--extra-vars '{...}'`. Without ansible_connection, ansible
    defaults to `smart` which probes for Python on the target and fails
    badly on network gear.
    """
    out: dict[str, object] = {"ansible_connection": "ssh"}
    creds = _SS["creds"]
    if creds.get("ssh_user"):
        out["ansible_user"] = creds["ssh_user"]
    if creds.get("ssh_password"):
        out["ansible_ssh_pass"] = creds["ssh_password"]
    if creds.get("ssh_key_path"):
        out["ansible_ssh_private_key_file"] = creds["ssh_key_path"]
    if creds.get("become_password"):
        out["ansible_become_pass"] = creds["become_password"]
    out.update(_SS["extra_vars"])
    return out


def _insert_status_event(run_id: str, event_type: str, payload: dict) -> int:
    """Write a playbook_run_events row with the given payload (REDACTED
    before insert). Returns the new event id."""
    safe = redact_secrets(payload)
    raw = json.dumps(safe, default=str)
    # Defense in depth — refuse to insert anything that still has secrets.
    assert payload_is_clean(raw), f"secret leak detected in {raw[:200]}"
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO playbook_run_events (run_id, event_type, payload) "
            "VALUES (?, ?, ?)",
            (run_id, event_type, raw),
        )
        conn.commit()
        return cur.lastrowid


def _update_run_status(run_id: str, **fields) -> None:
    """Update the playbook_runs row identified by run_id."""
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [run_id]
    with db() as conn:
        conn.execute(f"UPDATE playbook_runs SET {cols} WHERE id=?", vals)
        conn.commit()


def _run_in_progress() -> None:
    """Owns the actual POST + DB write loop. On entry, _SS has run_id,
    confirm_started=True, stage=5."""
    section_header("Stage 5 — Running")
    run_id = _SS["run_id"]

    # Persist the queued status_change event (run row already queued from Confirm click).
    pb = _SS["playbook_path"]
    selected = _SS["selected_devices"]
    selected_hosts = sorted(
        d.get("hostname") or d.get("device_id") or "?"
        for d in selected
    )
    # Card 8: build the inline inventory string now so it's logged in
    # the queued event. ssh_user comes from stage 3 credentials.
    inline_inventory = _build_inline_inventory(
        selected, _SS["creds"].get("ssh_user", "")
    )
    runner_payload = {
        "inventory_source": "inventory-mcp",
        "hosts": selected_hosts,
        "playbook": pb,
        "mode": _SS["mode"],
        "extra_vars": _extra_vars_with_creds(),
        "queued_at": time.time(),
    }
    _insert_status_event(run_id, "status_change", {"status": "queued", **runner_payload})
    _SS["events_count"] = _SS.get("events_count", 0) + 1

    extra_vars = _extra_vars_with_creds()
    # Card 8: the runner consumes `inline_inventory` (REPLACES the old
    # `inventory` field which used to be a file path on disk).
    runner_body = {
        "inline_inventory": inline_inventory,
        "playbook": pb,
        "extra_vars": extra_vars,
        "check": _SS["mode"] == "check",
    }

    progress = st.progress(0.0, text="Connecting to runner…")
    status_box = st.empty()
    stdout_box = st.empty()
    status_box.info(f"Run id `{short_run_id(run_id)}` queued.")

    # Mark running in DB + emit running status_change
    _update_run_status(run_id, status="running", started_at=_now_iso())
    _insert_status_event(run_id, "status_change", {"status": "running"})

    log_run_event(
        "run_started",
        run_id=run_id,
        playbook=pb,
        hosts=selected_hosts,
        mode=_SS["mode"],
    )

    # Stream from the runner, writing each NDJSON event to the DB.
    try:
        from hermes_client import post_signed
        resp = post_signed(f"{settings.ansible_runner_url}/run", runner_body, timeout=600.0)
    except Exception as exc:
        _SS["run_error"] = f"Could not reach runner: {exc}"
        _update_run_status(run_id, status="failed", finished_at=_now_iso(),
                           exit_code=None)
        _insert_status_event(run_id, "status_change",
                             {"status": "failed", "reason": "runner_unreachable",
                              "error": str(exc)})
        log_run_event("run_failed", run_id=run_id, reason="runner_unreachable",
                      error=str(exc))
        _SS["confirm_started"] = False
        status_box.error(_SS["run_error"])
        return

    if resp.status_code == 401:
        # HMAC mismatch — never persist anything; mark the run failed.
        _SS["auth_failed"] = True
        _SS["run_error"] = (
            "Authentication failed — check RUNNER_HMAC_SECRET on both "
            "streamlit-ui and aiamsbs-ansible-runner containers. The "
            "shared secret must match exactly."
        )
        _update_run_status(run_id, status="failed", finished_at=_now_iso(),
                           exit_code=None)
        _insert_status_event(run_id, "status_change",
                             {"status": "failed", "reason": "auth_failed",
                              "http": 401})
        log_run_event("run_auth_failed", run_id=run_id,
                      reason="auth_failed", http=401)
        _SS["confirm_started"] = False
        status_box.error(_SS["run_error"])
        return

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    final_exit_code: int | None = None
    n_lines = 0

    try:
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                obj = {"stream": "exec", "line": raw_line}

            stream = obj.get("stream")
            line = obj.get("line", "")
            if stream == "exec_stdout":
                stdout_lines.append(line)
                _insert_status_event(run_id, "exec_stdout", {"line": line})
                n_lines += 1
                # Refresh UI every 10 lines to keep reruns manageable.
                if n_lines % 10 == 0:
                    progress.progress(min(0.99, n_lines / 200.0),
                                      text=f"Running… {n_lines} lines")
                    stdout_box.code("\n".join(stdout_lines[-40:]))
            elif stream == "exec_stderr":
                stderr_lines.append(line)
                _insert_status_event(run_id, "exec_stderr", {"line": line})
                n_lines += 1
            elif obj.get("event") == "exit":
                final_exit_code = int(obj.get("exit_code", 1))
                _SS["final_exit_code"] = final_exit_code
            elif obj.get("event") == "stream_error":
                _insert_status_event(run_id, "status_change",
                                     {"status": "stream_error",
                                      "error": obj.get("error")})
    except Exception as exc:
        _SS["run_error"] = f"Stream interrupted: {exc}"
        _insert_status_event(run_id, "status_change",
                             {"status": "stream_error", "error": str(exc)})

    finished_iso = _now_iso()
    status = "completed" if (final_exit_code == 0) else "failed"
    _update_run_status(run_id,
                       status=status,
                       finished_at=finished_iso,
                       exit_code=final_exit_code)
    _insert_status_event(run_id, "status_change", {
        "status": status,
        "exit_code": final_exit_code,
        "stdout_lines": len(stdout_lines),
        "stderr_lines": len(stderr_lines),
    })

    log_run_event(
        f"run_{status}", run_id=run_id,
        exit_code=final_exit_code,
        stdout_lines=len(stdout_lines),
        stderr_lines=len(stderr_lines),
    )

    progress.progress(1.0, text="Done.")
    if status == "completed":
        status_box.success(
            f"✅ Run `{short_run_id(run_id)}` completed (exit_code=0). "
            f"Captured {len(stdout_lines)} stdout lines, "
            f"{len(stderr_lines)} stderr lines."
        )
    else:
        status_box.error(
            f"❌ Run `{short_run_id(run_id)}` failed (exit_code={final_exit_code}). "
            f"See stderr below or the Run Detail page for the full output."
        )

    with st.expander("stdout (tail)", expanded=True):
        st.code("\n".join(stdout_lines[-80:]) or "(empty)")
    if stderr_lines:
        with st.expander("stderr (tail)", expanded=False):
            st.code("\n".join(stderr_lines[-80:]))

    cols = st.columns([1, 1, 5])
    with cols[0]:
        if st.button("New run", key="post_new", type="primary"):
            _reset_flow()
            st.rerun()
    with cols[1]:
        page_link_button("pages/4_Run_History.py", "View run history →", "run_history", use_container_width=True)

    # Re-enable the form for another attempt on this same playbook (but
    # we leave the runs in place). Setting confirm_started=False would
    # risk the user clicking Confirm twice on the same form — guarded by
    # the `if _SS["confirm_started"]: st.warning(...)` in stage 4.
    _SS["confirm_started"] = False


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


# ---------------------------------------------------------------------------
# Stage dispatch + transition glue
# ---------------------------------------------------------------------------

def _stage5_dispatch() -> None:
    if _SS["confirm_started"] and _SS.get("run_id"):
        _run_in_progress()
        return
    # Reached stage 5 without a started run (e.g., after a rerun that
    # lost session_state in a refresh).  Send the user back to stage 4.
    _SS["stage"] = 4
    st.rerun()


def _prepare_run_row_on_confirm() -> str:
    """Insert the queued playbook_runs row. Called BEFORE we transition
    from stage 4 → stage 5, so the run exists with status=queued even
    before the actual POST. `cancel` would just update status to
    `cancelled` later.

    Card 8: the legacy `inventory` column (NOT NULL in the schema) now
    stores a compact "inventory-mcp:<host1>,<host2>,..." label so
    Run History / Run Detail pages still show something meaningful
    instead of an old file path.
    """
    run_id = new_run_id()
    user_id = st.session_state.get("user_id")
    selected_hosts = sorted(
        d.get("hostname") or d.get("device_id") or "?"
        for d in _SS["selected_devices"]
    )
    inv_label = "inventory-mcp:" + ",".join(selected_hosts)
    target_str = f"host={','.join(selected_hosts)}" if selected_hosts else "all"
    with db() as conn:
        conn.execute(
            "INSERT INTO playbook_runs "
            "(id, user_id, playbook, inventory, target, mode, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'queued')",
            (run_id, user_id, _SS["playbook_path"], inv_label,
             target_str, _SS["mode"]),
        )
        conn.commit()
    return run_id


# Confirm-click handler. We split this from stage4() so the actual
# `_prepare_run_row_on_confirm` happens BEFORE stage 5 starts, but
# stage 5 still owns the POST + stream. This is what makes the "Cancel
# from queued stage doesn't get a row" rule work: clicking Cancel in
# stage 4 returns to stage 1 with NO row created (stage 5 hasn't run
# yet). That matches the spec.
if _SS["stage"] == 5 and not _SS["confirm_started"]:
    # The "Run Playbook" button set stage=5 + confirm_started=True. If
    # confirm_started is False we landed here some other way; just send
    # the user back.
    _SS["stage"] = 4
    st.rerun()

if _SS["stage"] == 4 and _SS["confirm_started"] is True and not _SS.get("run_id"):
    # First time we entered stage=5; insert the queued row.
    try:
        new_id = _prepare_run_row_on_confirm()
    except Exception as exc:
        st.error(f"Failed to queue the run: {exc}")
        _SS["confirm_started"] = False
        st.stop()
    _SS["run_id"] = new_id
    _SS["stage"] = 5
    log_run_event(
        "run_queued",
        run_id=new_id,
        playbook=_SS["playbook_path"],
        hosts=sorted(
            d.get("hostname") or d.get("device_id") or "?"
            for d in _SS["selected_devices"]
        ),
        mode=_SS["mode"],
    )
    st.rerun()

# ---- Render current stage ----
if _SS["stage"] == 1:
    _stage1()
elif _SS["stage"] == 2:
    _stage2()
elif _SS["stage"] == 3:
    _stage3()
elif _SS["stage"] == 4:
    _stage4()
elif _SS["stage"] == 5:
    _stage5_dispatch()
