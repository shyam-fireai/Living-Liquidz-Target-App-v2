"""Entry point: page setup, login, table selection and routing. Screens live in views/."""

import logging

import streamlit as st

from config import TABLES, validate_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Living Liquid Dashboard", layout="wide", initial_sidebar_state="auto"
)  # auto: open on desktop, collapsed on phones

# Fail fast with a clear message if the deployment is missing configuration.
_problems = validate_settings()
if _problems:
    for p in _problems:
        logger.error("Configuration problem: %s", p)
    st.error("**The application is not configured correctly.** Ask the administrator to fix:")
    st.markdown("\n".join(f"- {p}" for p in _problems))
    st.stop()

from auth import require_login  # noqa: E402 - must follow st.set_page_config
from ui.theme import inject_minimalist_theme  # noqa: E402

if not require_login():
    st.stop()

inject_minimalist_theme()

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
    st.sidebar.title("📂 Tables")
    # Generated tables (e.g. Date & Branch Wise Target) cannot be edited/uploaded directly.
    table_keys = [t for t, cfg in TABLES.items() if page == "dashboard" or cfg.editable]
    labels = [TABLES[t].display_name for t in table_keys]
    current = st.session_state.current_table
    index = table_keys.index(current) if current in table_keys else 0

    selected_label = st.sidebar.radio("Select Table", labels, index=index)
    cfg = TABLES[table_keys[labels.index(selected_label)]]

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
from ui.components import render_user_card  # noqa: E402

render_user_card()
