"""Custom CSS on top of the native theme in .streamlit/config.toml (palette: ui/branding.py)."""

import logging

import streamlit as st

from ui.branding import BORDER, CARD_BG, MUTED, MUTED_ON_DARK, NAVY_ACTIVE, PAGE_BG, PRIMARY_LIGHT, TEXT

logger = logging.getLogger(__name__)

_CSS = f"""
<style>
    /* 1. PAGE: light grey ground, white cards and inputs */
    [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
        background-color: {PAGE_BG} !important;
    }}
    header[data-testid="stHeader"] {{
        background-color: rgba(255, 255, 255, 0) !important;
    }}
    [data-testid="stDecoration"] {{
        display: none !important;
    }}
    /* Eliminate the large default gap above the content */
    .block-container {{
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        max-width: 98% !important;
        margin-top: -1.5rem !important;
    }}
    [data-testid="stMain"] [data-baseweb="select"] > div,
    [data-testid="stMain"] [data-baseweb="input"],
    [data-testid="stMain"] [data-baseweb="base-input"],
    [data-testid="stMain"] [data-testid="stExpander"] details,
    [data-testid="stMain"] [data-testid="stFileUploaderDropzone"] {{
        background-color: {CARD_BG} !important;
    }}

    /* 2. HEADER TOOLBAR (ui.components.render_header): pinned to the top of the page */
    .st-key-ll_header {{
        position: sticky !important;
        top: 0 !important;
        z-index: 1000 !important;
        background-color: {PAGE_BG} !important;
        padding: 0.75rem 0 0.75rem !important;
        margin-bottom: 0.5rem !important;
    }}
    .ll-crumb {{
        font-size: 0.78rem;
        color: {MUTED};
        line-height: 1.3;
    }}
    .ll-title {{
        font-size: 1.5rem;
        font-weight: 600;
        letter-spacing: -0.01em;
        color: {TEXT};
        line-height: 1.25;
    }}

    /* 3. BUTTONS: colours come from the theme; only size and weight are set here */
    div.stButton > button,
    div.stDownloadButton > button,
    div.stFormSubmitButton > button,
    [data-testid="stPopover"] button {{
        min-height: 42px !important;
        font-weight: 600 !important;
    }}
    div.stButton > button p,
    div.stDownloadButton > button p {{
        white-space: nowrap !important;
        font-weight: 600 !important;
    }}

    /* 4. SIDEBAR: brand, section labels, table list styled as navigation, user card */
    .ll-brand {{
        margin: 0 0 0.75rem;
    }}
    .ll-side-label {{
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: {MUTED_ON_DARK};
        margin: 0.75rem 0 0.1rem;
    }}
    .ll-user-email {{
        font-size: 0.85rem;
        color: #C9CDD4;
        overflow-wrap: anywhere;
    }}
    /* links on the navy sidebar need a light blue to stay readable */
    [data-testid="stSidebar"] a {{
        color: #9CC2FF !important;
    }}
    .ll-powered {{
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.75rem;
        color: {MUTED_ON_DARK};
        margin-top: 0.5rem;
    }}
    [data-testid="stSidebar"] [role="radiogroup"] {{
        gap: 4px !important;
        width: 100%;
    }}
    [data-testid="stSidebar"] [role="radiogroup"] > label {{
        width: 100%;
        min-height: 44px;
        margin: 0 !important;
        padding: 8px 12px !important;
        border-radius: 10px;
        align-items: center;
        cursor: pointer;
    }}
    /* hide the radio dot: the highlighted row shows the selection */
    [data-testid="stSidebar"] [role="radiogroup"] > label > div:first-child {{
        display: none !important;
    }}
    [data-testid="stSidebar"] [role="radiogroup"] > label:hover {{
        background-color: rgba(255, 255, 255, 0.06);
    }}
    [data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {{
        background-color: {NAVY_ACTIVE};
        box-shadow: inset 3px 0 0 {PRIMARY_LIGHT};
    }}
    [data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) p {{
        font-weight: 600;
        color: #FFFFFF;
    }}

    /* 5. KPI CARDS (views.dashboard) */
    .kpi-row {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 4px 0 12px; }}
    .kpi-card {{
        flex: 1 1 160px; background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 12px;
        padding: 16px 20px;
    }}
    .kpi-label {{
        font-size: 0.72rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: {MUTED};
    }}
    .kpi-value {{
        font-size: 1.85rem; font-weight: 600; color: {TEXT}; line-height: 1.25; margin-top: 4px;
        font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}

    /* 6. RESPONSIVE */
    @media (max-width: 1024px) {{
        .block-container {{
            padding-left: 2rem !important;
            padding-right: 2rem !important;
        }}
    }}
    @media (max-width: 768px) {{
        [data-testid="stSidebar"] {{
            width: 100% !important;
        }}
        .ll-title {{
            font-size: 1.15rem;
        }}
        /* Larger touch targets */
        div.stButton > button {{
            width: 100% !important;
            min-height: 48px !important;
        }}
        .kpi-card {{ padding: 10px 14px; }}
        .kpi-value {{ font-size: 1.35rem; }}
    }}

    footer {{ visibility: hidden !important; }}

    /* The cookie components (auth.py) are invisible iframes; don't let them take up space. */
    [data-testid="stElementContainer"]:has(iframe[title*="CookieManager"]) {{ display: none; }}
</style>
"""


def inject_theme() -> None:
    """Inject the app-wide CSS. Call once per run, after login."""
    st.markdown(_CSS, unsafe_allow_html=True)
