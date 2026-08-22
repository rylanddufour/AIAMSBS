"""
theme.py — AIAMSBS Streamlit custom CSS / design tokens (BACKLOG #72).

Single source of truth for every visual customisation that goes BEYOND
what `.streamlit/config.toml` can express. config.toml handles the
4 core tokens (background, panel, primary, text); theme.py handles
everything else: status badges, card elevation, mono fonts on IDs,
zebra tables, hover states, focus rings.

Design tokens live in CSS custom properties on `:root` so swapping
the palette = edit one block, no per-page drift. To swap palettes:
1. Update the 4 base colors in `.streamlit/config.toml`
2. Update the matching :root vars in _CSS below (keep them in sync)
3. That's it — no page code references raw colors.

Usage:
    from theme import apply_theme
    apply_theme()         # call once per page, near the top, after
                          # st.set_page_config + auth gate
"""

from __future__ import annotations

import streamlit as st


# Status colors. Matches BACKLOG #72 acceptance criterion:
#   green = up/healthy, yellow = warn/degraded, red = down/error,
#   blue = info, gray = unknown.
_STATUS_GREEN = "#2ecc71"
_STATUS_YELLOW = "#f39c12"
_STATUS_RED = "#e74c3c"
_STATUS_BLUE = "#3498db"
_STATUS_GRAY = "#7f8c8d"


# CSS kept small + scoped to data-test attributes Streamlit ships with.
# Avoid `!important` overrides of Streamlit internals — we use higher-
# specificity selectors instead.
#
# IMPORTANT: this constant holds INNER CSS only — no <style> wrapper.
# apply_theme() injects ONE <style> block containing _CSS_INNER + _ICON_CSS
# concatenated, because Streamlit renders a SECOND <style> block as
# visible body text instead of injecting it as a style tag.
_CSS_INNER = """
/* ============================================================
   AIAMSBS Dark Cyber — design tokens (BACKLOG #72)
   Edit this block to swap palettes. Keep in sync with config.toml.
   ============================================================ */
/* Material Symbols Outlined font (MIT, Google Fonts CDN) — loaded
   via @import so the entire injection is one <style> block. Style
   matches the BACKLOG #72 follow-up reference: thin strokes, no
   fill, ~24px, glows on hover. FALLBACK-FRIENDLY: if the CDN is
   unreachable, the literal name still renders inside <span class="ms">
   so layout doesn't collapse. */
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,300,0,0&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;800&display=swap');
:root {
    --aiamsbs-bg:           #0b1220;
    --aiamsbs-panel:        #0f1b2e;
    --aiamsbs-panel-hover:  #14253d;
    --aiamsbs-border:       #1f3a5c;
    --aiamsbs-accent:       #00d4ff;
    --aiamsbs-accent-dim:   #008db3;
    --aiamsbs-magenta:      #ff00ff;
    --aiamsbs-magenta-dim:  #b300b3;
    --aiamsbs-text:         #e6edf3;
    --aiamsbs-text-muted:   #8b9bb4;
    --aiamsbs-mono:         "JetBrains Mono", "Fira Code", "SF Mono",
                            Menlo, Consolas, monospace;
    --status-up:            #2ecc71;
    --status-warn:          #f39c12;
    --status-down:          #e74c3c;
    --status-info:          #3498db;
    --status-unknown:       #7f8c8d;
    --shadow-card:          0 1px 3px rgba(0, 0, 0, 0.45),
                            0 1px 2px rgba(0, 0, 0, 0.30);
}

/* ============================================================
   App-wide: kill the default white background that bleeds through
   from non-themed widgets. Streamlit's own theme is set in config.toml
   but a few widget surfaces (file uploader, code blocks pre-mount)
   fall back to light. Force dark surfaces here.
   ============================================================ */
[data-testid="stAppViewContainer"] {
    background-color: var(--aiamsbs-bg);
}
[data-testid="stHeader"] {
    background-color: var(--aiamsbs-bg);
    border-bottom: 1px solid var(--aiamsbs-border);
}

/* ============================================================
   Sidebar: deeper panel, subtle separator from main content.
   ============================================================ */
[data-testid="stSidebar"] {
    background-color: var(--aiamsbs-panel);
    border-right: 1px solid var(--aiamsbs-border);
}
[data-testid="stSidebar"] * {
    color: var(--aiamsbs-text);
}
[data-testid="stSidebar"] hr {
    border-color: var(--aiamsbs-border);
    margin: 0.5rem 0;
}

/* ============================================================
   Cards: subtle elevation + rounded corners on container blocks.
   Any page can wrap content in st.container(border=True) — that
   gets our card treatment automatically.
   ============================================================ */
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stContainer"][data-testid*="border"],
.stMarkdown div[data-testid="stMarkdownContainer"] > div {
    /* keep selector narrow so we don't break prose */
}
[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: var(--aiamsbs-panel);
    border: 1px solid var(--aiamsbs-border);
    border-radius: 8px;
    padding: 1rem 1.25rem;
    box-shadow: var(--shadow-card);
}

/* ============================================================
   Headings: consistent scale + accent for primary h1.
   ============================================================ */
h1, h2, h3, h4, h5, h6 {
    color: var(--aiamsbs-text);
    font-weight: 600;
    letter-spacing: -0.01em;
}
h1 {
    border-bottom: 2px solid var(--aiamsbs-accent);
    padding-bottom: 0.4rem;
    margin-bottom: 1rem;
}

/* ============================================================
   Body / caption text.
   ============================================================ */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {
    color: var(--aiamsbs-text);
}
.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--aiamsbs-text-muted) !important;
}

/* ============================================================
   Buttons: accent on primary, panel for secondary.
   ============================================================ */
.stButton > button,
.stLinkButton a,
.stDownloadButton > button {
    background-color: var(--aiamsbs-panel);
    color: var(--aiamsbs-text);
    border: 1px solid var(--aiamsbs-border);
    border-radius: 6px;
    transition: background-color 120ms ease, border-color 120ms ease;
}
.stButton > button:hover,
.stDownloadButton > button:hover {
    background-color: var(--aiamsbs-panel-hover);
    border-color: var(--aiamsbs-accent-dim);
}
.stButton > button:focus,
.stLinkButton a:focus,
.stDownloadButton > button:focus {
    outline: 2px solid var(--aiamsbs-accent);
    outline-offset: 1px;
}
.stButton > button[kind="primary"],
.stFormSubmitButton > button {
    /* Tone the primary button down — was full accent fill (screaming
       cyan). Now: low-saturation cyan-tinted panel + accent border +
       accent text. Reads as "primary action" without competing with
       the page title. The accent ring only appears on hover/focus. */
    background-color: #0a2a3d;
    color: var(--aiamsbs-accent);
    border: 1px solid var(--aiamsbs-accent-dim);
    font-weight: 600;
}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button:hover {
    background-color: #0f3a52;
    border-color: var(--aiamsbs-accent);
    box-shadow: 0 0 0 1px rgba(0, 212, 255, 0.30);
}
.stButton > button[kind="primary"]:focus,
.stFormSubmitButton > button:focus {
    outline: 2px solid var(--aiamsbs-accent);
    outline-offset: 1px;
}
.stButton > button:disabled,
.stFormSubmitButton > button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
}

/* ============================================================
   Inputs: panel background, accent focus ring.
   ============================================================ */
.stTextInput input,
.stTextArea textarea,
.stNumberInput input,
.stSelectbox div[data-baseweb="select"] > div,
.stMultiSelect div[data-baseweb="select"] > div,
.stChatInput textarea {
    background-color: var(--aiamsbs-panel) !important;
    color: var(--aiamsbs-text) !important;
    border: 1px solid var(--aiamsbs-border) !important;
    border-radius: 6px !important;
}
.stTextInput input:focus,
.stTextArea textarea:focus,
.stNumberInput input:focus,
.stChatInput textarea:focus {
    border-color: var(--aiamsbs-accent) !important;
    box-shadow: 0 0 0 2px rgba(0, 212, 255, 0.25) !important;
}

/* Slider track + thumb */
.stSlider [data-baseweb="slider"] > div > div {
    background-color: var(--aiamsbs-accent-dim) !important;
}

/* Checkbox + radio accent */
.stCheckbox label span[data-checked="true"],
.stRadio label span[data-checked="true"] {
    background-color: var(--aiamsbs-accent) !important;
    border-color: var(--aiamsbs-accent) !important;
}

/* ============================================================
   Tables / dataframes: zebra rows, sticky header, mono numeric.
   ============================================================ */
.stDataFrame {
    border: 1px solid var(--aiamsbs-border);
    border-radius: 6px;
    overflow: hidden;
}
[data-testid="stTable"] table {
    border-collapse: collapse;
    width: 100%;
}
[data-testid="stTable"] thead th {
    background-color: var(--aiamsbs-panel);
    color: var(--aiamsbs-text);
    border-bottom: 1px solid var(--aiamsbs-border);
    font-weight: 600;
    text-align: left;
    padding: 0.5rem 0.75rem;
    position: sticky;
    top: 0;
}
[data-testid="stTable"] tbody tr:nth-child(even) td {
    background-color: rgba(255, 255, 255, 0.02);
}
[data-testid="stTable"] tbody tr:hover td {
    background-color: var(--aiamsbs-panel-hover);
}
[data-testid="stTable"] td {
    color: var(--aiamsbs-text);
    padding: 0.4rem 0.75rem;
    border-bottom: 1px solid rgba(31, 58, 92, 0.5);
}

/* ============================================================
   Status pills: colored shape + label (color > text).
   Use st.markdown(status_pill(...), unsafe_allow_html=True).
   ============================================================ */
.aiamsbs-pill {
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 600;
    font-family: var(--aiamsbs-mono);
    color: #001520;
    line-height: 1.4;
}
.aiamsbs-pill-up      { background-color: var(--status-up); }
.aiamsbs-pill-warn    { background-color: var(--status-warn); }
.aiamsbs-pill-down    { background-color: var(--status-down); }
.aiamsbs-pill-info    { background-color: var(--status-info); }
.aiamsbs-pill-unknown { background-color: var(--status-unknown); color: #fff; }

/* ============================================================
   Inline code / code blocks: monospace + panel background.
   ============================================================ */
code, pre, kbd {
    font-family: var(--aiamsbs-mono) !important;
}
[data-testid="stMarkdownContainer"] code {
    background-color: var(--aiamsbs-panel) !important;
    color: var(--aiamsbs-accent) !important;
    padding: 0.1rem 0.35rem !important;
    border-radius: 4px !important;
    border: 1px solid var(--aiamsbs-border) !important;
}
pre, [data-testid="stCodeBlock"] {
    background-color: var(--aiamsbs-panel) !important;
    border: 1px solid var(--aiamsbs-border) !important;
    border-radius: 6px !important;
}

/* ============================================================
   Info / success / warning / error boxes: keep Streamlit's intent
   but harmonize with the dark theme (default light-mode colors
   clash with our palette).
   ============================================================ */
.stAlert {
    border-radius: 6px;
    border-width: 1px;
    border-style: solid;
}
[data-testid="stAlert"][data-baseweb-kind="info"] {
    background-color: rgba(52, 152, 219, 0.10);
    border-color: var(--status-info);
    color: var(--aiamsbs-text);
}
[data-testid="stAlert"][data-baseweb-kind="success"] {
    background-color: rgba(46, 204, 113, 0.10);
    border-color: var(--status-up);
    color: var(--aiamsbs-text);
}
[data-testid="stAlert"][data-baseweb-kind="warning"] {
    background-color: rgba(243, 156, 18, 0.10);
    border-color: var(--status-warn);
    color: var(--aiamsbs-text);
}
[data-testid="stAlert"][data-baseweb-kind="error"] {
    background-color: rgba(231, 76, 60, 0.10);
    border-color: var(--status-down);
    color: var(--aiamsbs-text);
}

/* ============================================================
   Tabs: accent underline on the active tab.
   ============================================================ */
.stTabs [data-baseweb="tab-list"] {
    gap: 0.5rem;
    border-bottom: 1px solid var(--aiamsbs-border);
}
.stTabs [data-baseweb="tab"] {
    background-color: transparent;
    color: var(--aiamsbs-text-muted);
    border-radius: 6px 6px 0 0;
    padding: 0.5rem 1rem;
}
.stTabs [aria-selected="true"] {
    color: var(--aiamsbs-accent);
    border-bottom: 2px solid var(--aiamsbs-accent);
}

/* ============================================================
   Chat messages: distinct user / assistant surfaces.
   ============================================================ */
[data-testid="stChatMessage"] {
    background-color: var(--aiamsbs-panel);
    border: 1px solid var(--aiamsbs-border);
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
}

/* ============================================================
   Spinner / progress: accent color.
   ============================================================ */
.stSpinner > div {
    border-top-color: var(--aiamsbs-accent) !important;
}
"""


def apply_theme() -> None:
    """Inject the AIAMSBS custom CSS into the current page.

    Call once per page after st.set_page_config + auth. Idempotent.

    Note: Streamlit handles the FIRST <style> block well but tends
    to render subsequent <style> blocks as visible body text. So we
    combine _CSS + _ICON_CSS into ONE <style> block and call
    st.markdown ONCE.
    """
    combined = f"<style>{_CSS_INNER}{_ICON_CSS}</style>"
    st.markdown(combined, unsafe_allow_html=True)


# ============================================================
# AIAMSBS page-icon registry
# ============================================================
# Single source of truth for which Material Symbols name maps to
# which page / element. Edit here when adding a new page; no
# per-page hardcoded glyph names. Names are the standard Material
# Symbols icon names (https://fonts.google.com/icons).
_PAGE_ICONS: dict[str, str] = {
    "home":            "dashboard",          # central system status
    "settings":        "settings",           # gear
    "agent_chat":      "forum",              # speech bubble (single convo)
    "chat_sessions":   "forum",              # speech bubble (sessions list)
    "run_playbook":    "play_circle",        # play triangle, outlined
    "run_history":     "history",            # clock-with-arrow
    "run_detail":      "manage_search",      # search/inspect
    "kb_search":       "lightbulb",          # knowledge (NOT a stack of books)
    "inventory_search": "deployed_code",      # hexagon grid of devices
}

# Inline glyph helper. Returns the HTML for a Material Symbols
# icon; render with st.markdown(..., unsafe_allow_html=True).
def icon(name: str, size: str = "", status: str = "") -> str:
    """Render a Material Symbols icon as HTML.

    Args:
        name:   icon name (e.g. "home", "settings", "lightbulb").
        size:   optional size variant — "" (24px default), "sm" (16),
                "lg" (32), or "xl" (48).
        status: optional status tint — "", "up", "warn", "down",
                "info", or "unknown".

    Usage:
        st.markdown(icon("home"), unsafe_allow_html=True)
        st.markdown(icon("home", size="lg", status="up"), unsafe_allow_html=True)
    """
    classes = ["ms"]
    if size:
        classes.append(f"ms-{size}")
    if status:
        classes.append(f"ms-{status}")
    glyph = _PAGE_ICONS.get(name, name)
    return f'<span class="{" ".join(classes)}">{glyph}</span>'


def page_header(title: str, icon_name: str) -> None:
    """Render a page-header row (icon + title + accent underline).

    Use this INSTEAD of st.title() for consistency with the theme.
    Drop-in replacement — same call shape as st.title().

    Usage:
        page_header("Agent Chat", "agent_chat")
    """
    glyph = _PAGE_ICONS.get(icon_name, icon_name)
    st.markdown(
        f'<div class="aiamsbs-page-header">'
        f'<span class="ms">{glyph}</span>'
        f'<h1>{title}</h1>'
        f'</div>',
        unsafe_allow_html=True,
    )


def page_link_button(
    page_path: str,
    label: str,
    icon_name: str,
    *,
    use_container_width: bool = False,
) -> None:
    """Render a Material-Symbol icon + label as a styled nav button.

    Drop-in replacement for st.page_link when you want a Material
    Symbol glyph instead of an emoji. Streamlit's native page_link
    escapes the `icon=` argument so HTML can't pass through it; this
    helper builds the same look manually via st.markdown.

    Args:
        page_path: Streamlit page path relative to the app root,
                   e.g. "pages/4_Run_History.py" or just the page
                   title like "Run_History".
        label:     Link text.
        icon_name: Either a key from _PAGE_ICONS (e.g. "run_history")
                   or a raw Material Symbols name (e.g. "history").
        use_container_width: Match st.page_link's kwarg (currently
                   informational; CSS handles width via parent block).

    Usage:
        page_link_button("pages/4_Run_History.py", "Back to Run History", "run_history")
    """
    glyph = _PAGE_ICONS.get(icon_name, icon_name)
    # Streamlit routes by the page name, not the .py path. The /<name>
    # URL is what set_page_config uses for the title. We accept either
    # the .py file path OR the bare page name and normalize.
    if page_path.startswith("pages/") and page_path.endswith(".py"):
        href = "/" + page_path[len("pages/"):-len(".py")]
    elif "/" in page_path:
        href = "/" + page_path
    else:
        href = "/" + page_path
    st.markdown(
        f'<a href="{href}" class="aiamsbs-icon-button">'
        f'<span class="ms">{glyph}</span>'
        f'<span>{label}</span>'
        f'</a>',
        unsafe_allow_html=True,
    )


def cyberpunk_title(title: str, icon_name: str = "", size: str = "") -> None:
    """Render a page title in cyberpunk neon style.

    Drop-in replacement for page_header() when you want the synthwave/
    cyberpunk HUD look from the BACKLOG #72 follow-up design reference:
    outlined letterforms with a cyan -> magenta gradient stroke and a
    multi-layer glow + outer bloom.

    Args:
        title:     The title text.
        icon_name: Optional Material Symbols icon name (key into
                   _PAGE_ICONS or a raw name). Empty string = no icon.
        size:      "" (default 2.2rem) or "sm" (1.4rem) for subheadings.

    Usage:
        cyberpunk_title("Agent Chat", "agent_chat")
        cyberpunk_title("Recent playbook runs", size="sm")
    """
    glyph_html = ""
    if icon_name:
        glyph = _PAGE_ICONS.get(icon_name, icon_name)
        glyph_html = f'<span class="ms">{glyph}</span>'
    size_class = " aiamsbs-cyberpunk-sm" if size == "sm" else ""
    st.markdown(
        f'<div class="aiamsbs-cyberpunk-row">'
        f'{glyph_html}'
        f'<span class="aiamsbs-cyberpunk{size_class}">{title}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def section_header(title: str) -> None:
    """Render an in-page section heading (subheader).

    Same Orbitron font family as cyberpunk_title() so the typography
    stays consistent, but solid cyan fill, no glow, no gradient
    stroke — reads as "data" rather than "title". Use for in-page
    subheadings like "Quick links", "Stage 1 — Select playbook",
    "Recent playbook runs".

    Drop-in replacement for st.subheader(). The .aiamsbs-section-header
    class also works as a fallback — if you must use raw st.markdown
    or st.subheader, add the class to the rendered HTML.

    Usage:
        section_header("Stage 1 — Select playbook")
    """
    st.markdown(
        f'<div class="aiamsbs-section-header">{title}</div>',
        unsafe_allow_html=True,
    )


# AIAMSBS favicon. Inline SVG (data: URL) so the browser tab +
# bookmarks show the same glyph on every page. Drop-in for
# st.set_page_config(page_icon=AIAMSBS_FAVICON).
# Glyph: stylized "A" inside a shield — matches the dark-cyber
# palette. Rendered as 32x32 SVG, base64-encoded.
import base64 as _base64
_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<defs>'
    '<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0%" stop-color="#00d4ff"/>'
    '<stop offset="100%" stop-color="#008db3"/>'
    '</linearGradient>'
    '</defs>'
    '<path d="M16 2 L29 7 V16 C29 23 22 28 16 30 C10 28 3 23 3 16 V7 Z" '
    'fill="#0b1220" stroke="url(#g)" stroke-width="2"/>'
    '<path d="M9 23 L16 8 L23 23 M12 19 H20" '
    'stroke="#00d4ff" stroke-width="2.5" fill="none" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
AIAMSBS_FAVICON = (
    "data:image/svg+xml;base64,"
    + _base64.b64encode(_FAVICON_SVG.encode()).decode()
)


def status_pill(status: str, label: str | None = None) -> str:
    """Render an inline status badge as HTML.

    Args:
        status: One of "up", "warn", "down", "info", "unknown".
        label:  Visible text. Defaults to the status itself.

    Usage:
        st.markdown(status_pill("up", "Grafana · 12 ms"), unsafe_allow_html=True)

    The shape (colored pill) follows the BACKLOG #72 acceptance:
    status is communicated by color + shape, not by text alone. The
    label is for the human to read; the color is for instant scan.
    """
    s = status.lower()
    css_class = {
        "up": "aiamsbs-pill-up",
        "warn": "aiamsbs-pill-warn",
        "degraded": "aiamsbs-pill-warn",
        "down": "aiamsbs-pill-down",
        "error": "aiamsbs-pill-down",
        "info": "aiamsbs-pill-info",
        "unknown": "aiamsbs-pill-unknown",
    }.get(s, "aiamsbs-pill-unknown")
    text = label if label is not None else status.upper()
    return f'<span class="aiamsbs-pill {css_class}">{text}</span>'


# Friendly alias so pages don't need to import st.markdown separately.
def render_pill(status: str, label: str | None = None) -> None:
    """Convenience: call as render_pill("up", "Grafana · 12 ms")."""
    st.markdown(status_pill(status, label), unsafe_allow_html=True)


# ============================================================
# Icon system (BACKLOG #72 follow-up)
# ============================================================
# Replaces the emoji set on every page (🛡️⚙️💬📚📜🔎▶️) with Material
# Symbols Outlined — the same outlined-icon font the design reference
# uses. Style: thin strokes, no fill, 24px default, subtle cyan glow
# on hover. License: MIT (Google Fonts).
#
# Usage (inline):
#     st.markdown(icon("home"), unsafe_allow_html=True)   # renders the home glyph
#     page_header("Agent Chat", "chat")                    # title row with icon + glow
#
# Usage (page_config): drop the emoji from set_page_config.page_icon
# entirely — Streamlit's own favicon handling works fine without one,
# and the browser tab will fall back to a generic Streamlit logo if
# you pass an empty string. The inline glyphs are what users see in
# the page body / sidebar.

# CSS for the icon font. We keep the actual style content in
# _ICON_CSS (no <style> wrapper) and wrap it at injection time —
# see apply_theme() below. Combining with _CSS into one <style>
# block keeps Streamlit happy: a SECOND st.markdown(..., style ...)
# call after the first tends to render its content as visible body
# text instead of injecting a style tag, so we concatenate.
_ICON_CSS = """
/* ============================================================
   Material Symbols — outlined glyphs (BACKLOG #72 follow-up).
   Replaces the emoji icon set with a uniform outlined-icon font
   that matches the design reference. Material Symbols renders
   the literal text between <span class="ms">...</span> as a
   glyph (font ligature). Fallback: if the CDN didn't load, the
   literal name still shows — layout doesn't collapse.
   ============================================================ */
.material-symbols-outlined,
.ms {
    font-family: 'Material Symbols Outlined';
    font-weight: 300;        /* match design reference: thin strokes */
    font-style: normal;
    line-height: 1;
    text-transform: none;
    letter-spacing: normal;
    white-space: nowrap;
    word-wrap: normal;
    direction: ltr;
    font-feature-settings: 'liga';
    -webkit-font-smoothing: antialiased;
    /* Default appearance: cyan-tinted, 24px, vertical-aligned to text */
    color: var(--aiamsbs-accent);
    font-size: 24px;
    vertical-align: middle;
    transition: text-shadow 120ms ease, color 120ms ease;
}
.ms:hover {
    color: #66e3ff;
    text-shadow: 0 0 8px rgba(0, 212, 255, 0.55);
}

/* Icon-size variants. Use ms-lg, ms-sm, ms-xl to scale. */
.ms-sm { font-size: 16px; }
.ms-lg { font-size: 32px; }
.ms-xl { font-size: 48px; }

/* Status-tinted icons: color the glyph instead of the surrounding
   pill. Useful when an icon IS the indicator (e.g. status glyph
   next to a backend name on the Home health snapshot). */
.ms-up      { color: var(--status-up); }
.ms-warn    { color: var(--status-warn); }
.ms-down    { color: var(--status-down); }
.ms-info    { color: var(--status-info); }
.ms-unknown { color: var(--status-unknown); }

/* Page-header row: icon + title inline, with a subtle glow on the
   icon. Pages call page_header() to get this layout for free. */
.aiamsbs-page-header {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin: 0 0 1rem 0;
    padding-bottom: 0.4rem;
    border-bottom: 2px solid var(--aiamsbs-accent);
}
.aiamsbs-page-header .ms {
    font-size: 32px;
    text-shadow: 0 0 10px rgba(0, 212, 255, 0.45);
}
.aiamsbs-page-header h1 {
    margin: 0;
    padding: 0;
    border: none;       /* the row already has the accent underline */
    font-size: 1.6rem;
    font-weight: 600;
}

/* Sidebar nav icons (rendered next to st.page_link entries). Smaller
   size so they sit inline with the link text. */
[data-testid="stSidebarNavLink"] .ms,
[data-testid="stSidebarNav"] .ms {
    font-size: 18px;
    margin-right: 0.4rem;
    vertical-align: -3px;
}

/* The browser-tab favicon doesn't get our CSS — it's set via
   set_page_config(page_icon=...). We ship a small inline SVG as a
   consistent favicon across all pages so the browser tab always
   shows the AIAMSBS glyph (a stylized "A" shield). */

/* ============================================================
   Icon button (drop-in replacement for st.page_link when the icon
   argument must be a Material Symbol, not an emoji). Streamlit's
   page_link escapes the icon arg so we can't pass HTML through it;
   page_link_button() below renders the same look manually via
   st.markdown(unsafe_allow_html=True). The href uses Streamlit's
   internal page URL routing so navigation still works.
   ============================================================ */
a.aiamsbs-icon-button {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.9rem;
    background-color: var(--aiamsbs-panel);
    color: var(--aiamsbs-text);
    border: 1px solid var(--aiamsbs-border);
    border-radius: 6px;
    text-decoration: none;
    font-weight: 500;
    transition: background-color 120ms ease, border-color 120ms ease,
                box-shadow 120ms ease;
    vertical-align: middle;
}
a.aiamsbs-icon-button:hover {
    background-color: var(--aiamsbs-panel-hover);
    border-color: var(--aiamsbs-accent-dim);
    box-shadow: 0 0 0 1px rgba(0, 212, 255, 0.30);
    text-decoration: none;
}
a.aiamsbs-icon-button:focus {
    outline: 2px solid var(--aiamsbs-accent);
    outline-offset: 1px;
}
a.aiamsbs-icon-button .ms {
    font-size: 18px;
    vertical-align: -3px;
    color: var(--aiamsbs-accent);
}

/* ============================================================
   Cyberpunk neon title — BACKLOG #72 follow-up.
   Outlined letterforms with a cyan -> magenta gradient stroke
   and a multi-layer glow + outer bloom. Matches the design
   reference (synthwave/cyberpunk HUD style).

   Technique:
     - `-webkit-text-stroke` paints the gradient stroke on each
       glyph. The stroke color uses the cyan + magenta tokens via
       a linear-gradient applied as `background` and clipped to
       the text via `-webkit-background-clip: text`.
     - `color: transparent` makes the glyph fill invisible so the
       gradient shows through.
     - `text-shadow` stack = inner glow (sharp, colored) + outer
       bloom (wider, fading) for the neon halo.
     - Fallback for older browsers without `-webkit-text-stroke`:
       `.cyberpunk-fallback` class uses a solid cyan stroke instead.

   Usage: cyberpunk_title("Agent Chat", "agent_chat")
   ============================================================ */
.aiamsbs-cyberpunk {
    display: inline-block;
    font-family: 'Orbitron', 'Rajdhani', 'Audiowide', system-ui,
                 -apple-system, BlinkMacSystemFont, sans-serif;
    font-weight: 700;
    font-size: 2.2rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    /* Tight line-height + zero padding so the bounding box matches
       the visible glyph height. Combined with align-items: center
       on the row, this puts the icon and title on the same baseline.
       (Previously line-height: 1.1 added 10% extra space below the
       glyphs, which dropped the visual center.) */
    line-height: 1;
    padding: 0;
    /* Outline effect: gradient stroke + transparent fill */
    color: transparent;
    -webkit-text-fill-color: transparent;
    background: linear-gradient(
        90deg,
        var(--aiamsbs-accent) 0%,
        #c800ff 50%,
        var(--aiamsbs-magenta) 100%
    );
    -webkit-background-clip: text;
    background-clip: text;
    /* The actual stroke — modern WebKit / Blink render this; the
       fallback path in older browsers shows a solid cyan outline. */
    -webkit-text-stroke: 1.5px var(--aiamsbs-accent);
    /* Multi-layer text-shadow = inner glow + outer bloom.
       Stack order: tight inner cyan glow -> wider outer bloom
       fading to transparent. The exact reference has BOTH a
       sharp inner magenta tint AND a soft outer magenta bloom. */
    text-shadow:
        0 0 4px rgba(0, 212, 255, 0.85),
        0 0 8px rgba(0, 212, 255, 0.55),
        0 0 18px rgba(200, 0, 255, 0.45),
        0 0 36px rgba(255, 0, 255, 0.30),
        0 0 60px rgba(255, 0, 255, 0.18);
    /* Padding so the bloom doesn't get clipped by the row bounds */
    padding: 0.3rem 0;
    margin: 0 0 1rem 0;
}
.aiamsbs-cyberpunk-row {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding-bottom: 0.4rem;
    border-bottom: 2px solid var(--aiamsbs-accent);
    margin-bottom: 1rem;
}
.aiamsbs-cyberpunk-row .ms {
    /* Match the cyberpunk title's apparent visual height (~2.2rem
       = 35px baseline + glow + stroke). 44px lands visually balanced
       with the outlined title's letterforms without dwarfing it. */
    font-size: 44px;
    line-height: 1;
    color: var(--aiamsbs-accent);
    text-shadow:
        0 0 8px rgba(0, 212, 255, 0.65),
        0 0 16px rgba(200, 0, 255, 0.40);
    /* Material Symbols has a built-in descender buffer that pushes
       the glyph DOWN relative to the em-square center (visible as
       the icon sitting lower than the title's cap-line). Lift the
       icon UP ~5px so its visual center aligns with the title.
       Tried: 4px down — too low. 1px down — still too low. Baseline
       alignment — too low. 0px — too low. Negative is the right
       direction. */
    transform: translateY(-5px);
}
/* Smaller variant: when the title uses size='sm' (1.4rem = ~22px),
   the icon should also shrink proportionally to keep balance.
   Note: cyberpunk_title() emits icon-then-title in the row, so we
   use :has() to detect the sm-title class on a child element and
   shrink the icon. */
.aiamsbs-cyberpunk-row:has(.aiamsbs-cyberpunk-sm) .ms {
    font-size: 28px;
}
/* Solid-cyan fallback for browsers without -webkit-text-stroke.
   Still neon-ish, just less gradient. */
.aiamsbs-cyberpunk-fallback {
    color: var(--aiamsbs-accent);
    -webkit-text-fill-color: var(--aiamsbs-accent);
    background: none;
    -webkit-text-stroke: 0;
    font-weight: 800;
    text-shadow:
        0 0 6px rgba(0, 212, 255, 0.85),
        0 0 14px rgba(255, 0, 255, 0.45);
}

/* Smaller variant for subheadings / inline labels (e.g. the
   "Recent playbook runs" rows on Home). */
.aiamsbs-cyberpunk-sm {
    font-size: 1.4rem;
}

/* ============================================================
   Section header — for in-page subheadings ("Quick links",
   "Stage 1 — Select playbook", etc). Same Orbitron font family
   as the cyberpunk title so the typography line stays consistent,
   but solid cyan fill (no gradient stroke), no glow, no bloom.
   This reads as "data" rather than "title" — the page title
   does the heavy neon lifting and section headers stay readable.
   ============================================================ */
.aiamsbs-section-header {
    font-family: 'Orbitron', 'Rajdhani', system-ui, -apple-system,
                 BlinkMacSystemFont, sans-serif;
    font-weight: 600;
    font-size: 1.15rem;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--aiamsbs-accent);
    /* Solid fill — no gradient, no stroke, no glow. The accent
       underline border gives visual continuity with the cyberpunk
       title's bordered row above. */
    -webkit-text-fill-color: var(--aiamsbs-accent);
    background: none;
    -webkit-text-stroke: 0;
    text-shadow: none;
    margin: 1.25rem 0 0.6rem 0;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid var(--aiamsbs-accent-dim);
}

/* Override Streamlit's native h2 / h3 styling so any remaining
   st.subheader() or st.markdown("## ...") calls also pick up the
   theme. Less aggressive than .aiamsbs-section-header (no border)
   so it doesn't add noise where the developer chose not to use
   section_header(). */
h2, h3,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    font-family: 'Orbitron', 'Rajdhani', system-ui, -apple-system,
                 BlinkMacSystemFont, sans-serif !important;
    color: var(--aiamsbs-accent) !important;
    -webkit-text-fill-color: var(--aiamsbs-accent) !important;
    text-shadow: none !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    text-transform: uppercase !important;
}
h2 { font-size: 1.15rem !important; }
h3 { font-size: 1.0rem !important; }
"""
