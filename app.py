"""Entry point: page setup, login, table selection and routing. Screens live in views/."""

import logging

import streamlit as st

from config import TABLES, validate_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from ui.branding import APP_NAME, LIVING_LIQUIDZ_LOGO, logo_path  # noqa: E402 - needed for the page config

_icon = logo_path(LIVING_LIQUIDZ_LOGO)
st.set_page_config(
    page_title=APP_NAME,
    page_icon=str(_icon) if _icon else None,
    layout="wide",
    initial_sidebar_state="auto",  # auto: open on desktop, collapsed on phones
)

# Fail fast with a clear message if the deployment is missing configuration.
_problems = validate_settings()
if _problems:
    for p in _problems:
        logger.error("Configuration problem: %s", p)
    st.error("**The application is not configured correctly.** Ask the administrator to fix:")
    st.markdown("\n".join(f"- {p}" for p in _problems))
    st.stop()

from auth import require_login  # noqa: E402 - must follow st.set_page_config
from ui.components import render_sidebar_brand, render_user_card, sidebar_label  # noqa: E402
from ui.theme import inject_theme  # noqa: E402

if not require_login():
    st.stop()

inject_theme()
render_sidebar_brand()

st.session_state.setdefault("page", "dashboard")
st.session_state.setdefault("current_table", None)

page = st.session_state.page

if page == "history":
    # History spans all tables: it has its own filters and no table picker.
    from views.history import history_screen

    history_screen()
else:
    # -------------------------------
    # SIDEBAR TABLE SELECT
    # -------------------------------
    sidebar_label("Tables")
    # Generated tables (e.g. Date & Branch Wise Target) cannot be edited/uploaded directly.
    table_keys = [t for t, cfg in TABLES.items() if page == "dashboard" or cfg.editable]
    current = st.session_state.current_table
    # A fixed key keeps the radio the same widget across reruns. (Passing index= made Streamlit
    # rebuild it whenever the selection changed, so every other click was lost.)
    if st.session_state.get("table_picker") not in table_keys:  # first run, or back from History
        st.session_state.table_picker = current if current in table_keys else table_keys[0]
    selected = st.sidebar.radio(
        "Select Table",
        table_keys,
        format_func=lambda t: TABLES[t].display_name,
        key="table_picker",
        label_visibility="collapsed",
    )
    cfg = TABLES[selected]

    if current != cfg.name:
        logger.info("Table switched: %s -> %s", current, cfg.name)
        st.session_state.current_table = cfg.name

    # -------------------------------
    # ROUTING
    # -------------------------------
    if page == "edit":
        from views.edit import edit_screen

        edit_screen(cfg)
    elif page == "upload":
        from views.upload import upload_screen

        upload_screen(cfg)
    else:
        from views.dashboard import dashboard_screen

        dashboard_screen(cfg)

# Rendered last so it sits at the bottom of the sidebar, below the filters.
render_user_card()
