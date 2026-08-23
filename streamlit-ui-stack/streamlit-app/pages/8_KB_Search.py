# pages/8_KB_Search.py — AIAMSBS v1.0 customer KB Search.
#
# Card 6 of BACKLOG #64. Read + add view over the kb-mcp backend.
# All KB access goes through `mcp_client` (MCP HTTP transport). No
# direct SQLite / shared FS access from this page.
#
# Privacy: search/add events log to Loki as METADATA ONLY. The query
# body NEVER lands in Loki — see the `_log` helper below. mcp_client
# itself never logs query bodies either (the rule per BACKLOG #14 /
# #30).
#
# Spec adherence:
# - Auth gate + sidebar logout (consistent with other pages).
# - Top: search input, status multi-select, trust_level multi-select,
#   result count.
# - Submit -> kb_search(query, k=20) -> results table.
# - Click title -> ?entry_id=<id> drill-down with full content.
# - "Add new KB entry" modal -> kb_add -> refresh list.
# - Loki events: {stream="kb", event="search|add", user_id, query_len,
#   result_count} (no query body).

from __future__ import annotations

import streamlit as st

from auth import require_auth, render_logout_button
from mcp_client import (
    MCPFormatError,
    MCPUnavailableError,
    MCPToolError,
    kb_add,
    kb_search,
)
from settings import load as load_settings
from theme import AIAMSBS_FAVICON, apply_theme, cyberpunk_title, page_header, page_link_button

st.set_page_config(
    page_title="KB Search — AIAMSBS",
    page_icon=AIAMSBS_FAVICON, layout="wide",
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

# ---- Loki logger (best-effort; never break the page on logging) ----
def _log(event: str, **fields) -> None:
    """Log a kb_search page event. NEVER includes the query body.

    Fields always include user_id + query_len + result_count so the
    audit trail is useful without leaking what the customer searched
    for. If `result_count` is not provided, callers should still set
    it (we'll treat absent as 0 in Loki).
    """
    try:
        from loki_logger import log_event
        log_event(
            "kb",
            {
                "event": event,
                "page": "KB_Search",
                "user_id": user_id,
                "username": username,
                **{k: v for k, v in fields.items() if v is not None},
            },
        )
    except Exception:
        pass


cyberpunk_title("KB Search", "kb_search")
st.caption(
    "Search the knowledge base. Drill into an entry to see full "
    "content. Add new entries via the **+ Add** button."
)


# ---- Filter row + search input ----
# Layout: search input spans 3 cols on row 1, then status/trust/tags
# share a second row of 3 cols. The K0-K3 trust ladder explainer
# lives in a st.popover() next to the trust-level multiselect so it
# doesn't take screen real estate unless the user clicks it.
fcol1, fcol2, fcol3 = st.columns([3, 2, 2])
with fcol1:
    query = st.text_input(
        "Search",
        value=st.session_state.get("kb_search_query", ""),
        placeholder="e.g. restart streamlit  (or 'cisc' for prefix-match, \"exact phrase\", OR)",
        key="kb_search_query_input",
        help=(
            "FTS5 syntax (kb-mcp's flavor):\n"
            "• Plain words match anywhere. The LAST token is auto-prefix-matched "
            "(e.g. `cisc` finds `Cisco`, `Cisco switch SSH`).\n"
            "• Explicit prefix: `cisco*` matches anything starting with `cisco`.\n"
            "• Multiple prefixes: `cisco* OR juniper*`.\n"
            "• Exact phrase: `\"streamlit restart\"` (the quotes keep the words together).\n"
            "• Column restrict: `title:cisco` (matches only the title column).\n"
            "• FTS5 is PREFIX-ONLY — `*sco`, `*lit`, `*sw*` and `?isco` are NOT supported "
            "(the FTS5 engine only does `prefix*`, not suffix or substring). "
            "For suffix/substring matching, fall back to plain words "
            "(last-token auto-prefix still applies) or use multiple `prefix*` terms joined with OR."
        ),
    )
with fcol2:
    status_filter = st.multiselect(
        "Status",
        options=["pending", "approved", "rejected", "all"],
        default=["pending", "approved"],
        key="kb_status_filter",
    )
with fcol3:
    tc1, tc2 = st.columns([4, 1])
    with tc1:
        trust_filter = st.multiselect(
            "Trust level",
            options=["K0", "K1", "K2", "K3", "all"],
            default=["K0", "K1", "K2", "K3"],
            key="kb_trust_filter",
        )
    with tc2:
        # Trust ladder explainer. BACKLOG #69 (a). Shows on click,
        # not on hover (more discoverable; doesn't clutter the row).
        with st.popover("?", help="Trust ladder explained"):
            st.markdown(
                "**K0** ⚪ — *agent-written, pending review.* Default trust "
                "for any entry the Hermes agent creates. Not yet human-reviewed.\n\n"
                "**K1** 🟡 — *agent-written, lightly reviewed.* A human has "
                "skimmed it and confirmed no obvious garbage, but hasn't "
                "fully validated the content.\n\n"
                "**K2** 🔵 — *customer-written or fully-reviewed.* Authored "
                "by a human operator, OR an agent entry that's been deeply "
                "reviewed and validated against the live system.\n\n"
                "**K3** 🟢 — *customer-written and approved.* Authored by "
                "the customer themselves (not the agent) and explicitly "
                "approved. Highest trust.\n\n"
                "*Trust level is set at entry creation (`trust_level_at_creation`) "
                "and does not change on subsequent edits.*"
            )

search_clicked = st.button(
    "Search", type="primary", use_container_width=False, key="kb_search_btn"
)


# ---- Tag filter (client-side, BACKLOG #69 (c)) ----
# We compute the union of all tags from the visible result set so the
# multiselect only shows tags that actually appear. This avoids fetching
# a separate kb_list call (kb-mcp's kb_search already returns tags per
# row) and avoids listing stale tags from deleted entries. Multi-select
# uses AND semantics: an entry must have ALL selected tags to match.
# If no results yet (page just loaded), the options list is empty and
# the multiselect renders disabled — that's fine.
@st.cache_data(ttl=30, show_spinner=False)
def _all_tags_from_results(rows: list[dict]) -> list[str]:
    """Return sorted unique tag union across the given rows.

    Cached on the input rows (by id() — Streamlit's @st.cache_data
    keys on the actual list, so each call with new results recomputes).
    """
    tags: set[str] = set()
    for r in rows or []:
        for t in (r.get("tags") or []):
            if t:
                tags.add(str(t))
    return sorted(tags)


# Tag filter row. We render it BEFORE the search runs by deriving
# available tags from the previous result set (or empty on first load).
# The filter applies client-side after the search returns.
_tag_options: list[str] = []
if "results" in st.session_state and st.session_state.results:
    _tag_options = _all_tags_from_results(
        list(st.session_state.results)  # cache key stable across reruns
    )

tagcol1, tagcol2 = st.columns([3, 1])
with tagcol1:
    tag_filter = st.multiselect(
        "Tags (AND — entry must have ALL selected)",
        options=_tag_options,
        default=[],
        key="kb_tag_filter",
        help=(
            "Filter by tags assigned to entries. AND semantics — an entry "
            "must carry every selected tag. Options refresh 30s after each "
            "search; if empty, run a Search first to populate the tag list."
        ),
    )
with tagcol2:
    if _tag_options:
        st.caption(f"{len(_tag_options)} tag(s) available")


# ---- Helpers ----
_STATUS_COLORS = {
    "pending": "🟠",
    "approved": "🟢",
    "rejected": "🔴",
}

_TRUST_COLORS = {
    "K0": "⚪",  # pending, agent-written
    "K1": "🟡",
    "K2": "🔵",
    "K3": "🟢",  # customer-written, approved
}


def _trust_badge(level: int | None) -> str:
    """Render a trust-level K0..K3 badge from the int trust_level_at_creation."""
    if level is None:
        return "⚪ K?"
    k = f"K{int(level)}"
    return f"{_TRUST_COLORS.get(k, '⚪')} {k}"


def _status_badge(status: str | None) -> str:
    s = (status or "unknown").lower()
    return f"{_STATUS_COLORS.get(s, '⚪')} {s}"


def _matches_filters(
    entry: dict, statuses: list[str], trusts: list[str],
    tags: list[str] | None = None,
) -> bool:
    """Return True iff entry passes the user-selected filters.

    Tag filter is AND — entry must carry every selected tag. Empty/None
    means "no tag filter applied".
    """
    if statuses and "all" not in statuses:
        if (entry.get("status") or "").lower() not in statuses:
            return False
    if trusts and "all" not in trusts:
        k = f"K{entry.get('trust_level_at_creation', 0)}"
        if k not in trusts:
            return False
    if tags:
        entry_tags = set(t for t in (entry.get("tags") or []) if t)
        if not set(tags).issubset(entry_tags):
            return False
    return True


def _preview(content: str, n: int = 200) -> str:
    """First N chars of content with whitespace collapsed."""
    if not content:
        return ""
    flat = " ".join(content.split())
    return flat[:n] + ("…" if len(flat) > n else "")


# ---- Run the search (auto-run on first load with empty query) ----
# If the user hasn't clicked Search yet but has a query typed, also
# run automatically (treats the text_input as live). Default state:
# empty query -> empty results until user types or clicks Search.
results: list[dict] = []
err_msg: str | None = None

if query or search_clicked:
    try:
        with st.spinner("Searching KB…"):
            results = kb_search(query=query, k=20)
        # Persist for the tag-options derivation on next rerun (BACKLOG #69 (c)).
        # We store the raw result list so the multiselect's options refresh
        # from the most recent successful search.
        st.session_state["results"] = list(results)
    except MCPUnavailableError as e:
        err_msg = f"KB service unavailable: {e}"
    except MCPFormatError as e:
        # Per BACKLOG #14 — non-MCP-shaped response is a real problem.
        # Log full body to Loki, show truncated in UI, BLOCK.
        _log("kb_format_error", error=str(e)[:500])
        st.error(
            "❌ **KB MCP returned a non-MCP response.** This is a "
            "backend regression, not a UI bug. The response body has "
            "been logged to Loki under `stream=kb event=kb_format_error`. "
            f"First 300 chars: `{str(e)[:300]}`"
        )
        st.stop()
    except MCPToolError as e:
        err_msg = f"KB tool error: {e}"
    except Exception as e:
        err_msg = f"KB search failed: {type(e).__name__}: {e}"

    if err_msg:
        _log("kb_search_error", query_len=len(query), error=err_msg[:300])

    # Log the search (metadata only — never the query body).
    _log(
        "search",
        query_len=len(query),
        result_count=len(results),
        status_filter=",".join(status_filter),
        trust_filter=",".join(trust_filter),
        tag_filter=",".join(tag_filter),
    )

if err_msg and query:
    st.warning(f"⚠️ {err_msg}")


# ---- Apply client-side filters then render ----
filtered = [
    r for r in results
    if _matches_filters(r, status_filter, trust_filter, tag_filter)
]

st.caption(f"**{len(filtered)}** of {len(results)} result(s)")


# ---- Drill-down (driven by ?entry_id=<id> query param) ----
url_entry_id = st.query_params.get("entry_id", None)
drill_entry: dict | None = None
if url_entry_id:
    for r in filtered:
        if str(r.get("id")) == str(url_entry_id):
            drill_entry = r
            break

if drill_entry:
    st.markdown("---")
    st.markdown(f"### 📄 {drill_entry.get('title', '(no title)')}")
    st.markdown(
        f"{_status_badge(drill_entry.get('status'))} · "
        f"{_trust_badge(drill_entry.get('trust_level_at_creation'))} · "
        f"updated `{drill_entry.get('updated_at', '?')}`"
    )
    content_md = drill_entry.get("content", "") or ""
    st.markdown(content_md)
    # Copy-to-clipboard via streamlit components (works in a browser).
    btn_cols = st.columns([1, 6])
    with btn_cols[0]:
        st.code(content_md[:2000], language=None)
    _log("entry_viewed", entry_id=drill_entry.get("id"))
    if st.button("← Back to results", key="kb_back_to_results"):
        del st.query_params["entry_id"]
        st.rerun()


# ---- Results table ----
st.markdown("---")
if not filtered and (query or search_clicked):
    st.info("No KB entries match your search + filters.")
elif not filtered:
    st.info("Type a query above (or click Search) to look up KB entries.")

for r in filtered:
    rid = r.get("id")
    cols = st.columns([6, 1, 1, 1])
    with cols[0]:
        # Title is the drill-down link.
        if st.button(
            f"📄 {r.get('title', '(no title)')}",
            key=f"kb_title_{rid}",
            use_container_width=True,
        ):
            st.query_params["entry_id"] = str(rid)
            st.rerun()
        st.caption(_preview(r.get("content", "")))
    with cols[1]:
        st.markdown(_status_badge(r.get("status")))
    with cols[2]:
        st.markdown(_trust_badge(r.get("trust_level_at_creation")))
    with cols[3]:
        st.caption(f"`{r.get('updated_at', '?')}`")


# ---- "Add new KB entry" modal ----
st.markdown("---")
with st.expander("➕ Add new KB entry", expanded=False):
    with st.form("kb_add_form", clear_on_submit=True):
        new_title = st.text_input(
            "Title",
            key="kb_add_title",
            help="Short, scannable — this is what people search for. Required.",
        )
        new_content = st.text_area(
            "Content (markdown)",
            key="kb_add_content",
            height=200,
            help="Runbook / fact / gotcha body. Markdown is rendered on drill-down.",
        )
        new_entry_type = st.selectbox(
            "Entry type",
            options=["runbook", "fact", "gotcha"],
            key="kb_add_type",
        )
        new_tags = st.text_input(
            "Tags (comma-separated)",
            key="kb_add_tags",
            help="e.g. network, opnsense, restart",
        )
        submitted = st.form_submit_button("Add entry")
    if submitted:
        title_clean = (new_title or "").strip()
        content_clean = (new_content or "").strip()
        tag_list = [
            t.strip() for t in (new_tags or "").split(",") if t.strip()
        ]
        if not title_clean:
            st.error("Title is required.")
        elif not content_clean:
            st.error("Content is required.")
        else:
            try:
                with st.spinner("Adding entry…"):
                    row = kb_add(
                        title=title_clean,
                        content=content_clean,
                        entry_type=new_entry_type,
                        tags=tag_list,
                        created_by="customer",
                    )
                entry_id = row.get("id") if isinstance(row, dict) else None
                _log(
                    "add",
                    entry_id=entry_id,
                    entry_type=new_entry_type,
                    tag_count=len(tag_list),
                )
                st.success(
                    f"✅ Added entry **'{title_clean}'** "
                    f"(id={entry_id}). It is now in the table above."
                )
                # Rerun so the new entry shows in the list.
                st.rerun()
            except MCPUnavailableError as e:
                _log("kb_add_error", error=str(e)[:300])
                st.error(f"KB service unavailable: {e}")
            except MCPToolError as e:
                _log("kb_add_error", error=str(e)[:300])
                st.error(f"KB tool error: {e}")
            except Exception as e:
                _log("kb_add_error", error=str(e)[:300])
                st.error(
                    f"Add failed: {type(e).__name__}: {e}"
                )


# ---- Logout (moved from sidebar to page body) ----
st.markdown("---")
render_logout_button()