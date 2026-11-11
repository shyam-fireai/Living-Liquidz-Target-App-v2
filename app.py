import logging
import time

import pandas as pd
import streamlit as st

from db import (
    TABLE_SCHEMAS,
    apply_currency_format,
    fetch_data,
    format_column,
    get_all_filter_values,
    remove_zero_columns,
)
from style_utils import inject_minimalist_theme, render_header

# Initialize logger for app.py
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------
# UI SETTINGS (MINIMALIST THEME)
# -------------------------------
st.set_page_config(
    page_title="Living Liquid Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

from auth import require_login  # noqa: E402 - must follow st.set_page_config

if not require_login():
    st.stop()

inject_minimalist_theme()

# -------------------------------
# SESSION STATE
# -------------------------------
if "page" not in st.session_state:
    st.session_state.page = "dashboard"

if "upload_done" not in st.session_state:
    st.session_state.upload_done = False

if "applied_filters" not in st.session_state:
    st.session_state.applied_filters = {}

if "temp_filters" not in st.session_state:
    st.session_state.temp_filters = {}

if "current_table" not in st.session_state:
    st.session_state.current_table = None
# -------------------------------
# TABLE CONFIG
# -------------------------------
TABLE_CONFIG = {
    "branch_wise_monthly_target": {
        "name": "Branch Wise Monthly Target",
        "filters": ["month", "branch_name", "series_group"],
        "currency": True
    },
    "brand_wise_monthly_target": {
        "name": "Brand Wise Monthly Target",
        "filters": ["month", "branch_name", "series_group", "item_code", "item_name", "pack_name"],
        "currency": False
    },
    "date_branch_wise_target": {
        "name": "Date & Branch Wise Target",
        "filters": ["date", "branch_name", "series_group"],
        "currency": True
    }
}

# -------------------------------
# REQUIRED COLUMNS (REPLACED BY db.TABLE_SCHEMAS)
# -------------------------------
REQUIRED_COLUMNS = TABLE_SCHEMAS

# -------------------------------
# ₹ FORMAT
# (apply_currency_format moved to db.py)
# -------------------------------
# REMOVE ZERO COLUMNS
# -------------------------------
# SIDEBAR TABLE SELECT
# -------------------------------
# SIDEBAR TABLE SELECT
# -------------------------------
st.sidebar.title("📂 Tables")

# On Edit and Upload screens, hide 'Date & Branch Wise Target'
if st.session_state.page in ["edit", "upload"]:
    table_keys = [t for t in TABLE_CONFIG.keys() if t != "date_branch_wise_target"]
else:
    table_keys = list(TABLE_CONFIG.keys())

table_display = [TABLE_CONFIG[t]["name"] for t in table_keys]

# Ensure currently selected table is in the list
current_index = 0
if "current_table" in st.session_state and st.session_state.current_table in table_keys:
    current_index = table_keys.index(st.session_state.current_table)

selected_display = st.sidebar.radio("Select Table", table_display, index=current_index)
selected_table = table_keys[table_display.index(selected_display)]

# RESET FILTERS ON TABLE SWITCH (OR INITIAL COLD START)
if st.session_state.current_table != selected_table:
    logger.info(f"Synchronizing table state: {st.session_state.current_table} -> {selected_table}")
    st.session_state.applied_filters = {}
    st.session_state.temp_filters = {} # Explicitly reset to ensure cold start is clean
    st.session_state.upload_done = False
    st.session_state.upload_msg = ""
    st.session_state.current_table = selected_table

# -------------------------------
# EDIT PAGE
# -------------------------------
if st.session_state.page == "edit":
    if selected_table == "date_branch_wise_target":
        st.warning("⚠️ Editing 'Date & Branch Wise Target' directly is disabled. Please edit via 'Branch Wise Monthly Target'.")
        if st.button("⬅️ Back to Dashboard"):
            st.session_state.page = "dashboard"
            st.rerun()
        st.stop()
    from edit import edit_screen
    edit_screen(selected_table)
    st.stop()

# -------------------------------
# UPLOAD PAGE
# -------------------------------
if st.session_state.page == "upload":
    if selected_table == "date_branch_wise_target":
        st.warning("⚠️ Direct upload for 'Date & Branch Wise Target' is disabled. Please upload via 'Branch Wise Monthly Target'.")
        if st.button("⬅️ Back to Dashboard"):
            st.session_state.page = "dashboard"
            st.rerun()
        st.stop()
    from upload import upload_screen
    upload_screen(selected_table)
    st.stop()

# -------------------------------
# HEADER & NAVIGATION (SINGLE ROW)
# -------------------------------
display_name = TABLE_CONFIG[selected_table]["name"]
is_date_branch_target = (selected_table == "date_branch_wise_target")

# For Date & Branch Wise Target, hide Edit and Upload buttons from header
if is_date_branch_target:
    render_header(title=display_name, hide_upload=True)
else:
    col_edit, col_upload = render_header(title=display_name)
    with col_edit:
        if st.button("📝 Edit", use_container_width=True):
            st.session_state.page = "edit"
            st.rerun()

    with col_upload:
        if st.button("📤 Upload", use_container_width=True):
            st.session_state.page = "upload"
            st.rerun()

# -------------------------------
# UI INITIALIZATION (SIDEBAR & FILTERS)
# -------------------------------
# ✅ SYNC LIVE STATE
# On any frame, we ensure the dashboard is starting cleanly.
# The auth state is now handled synchronously in require_login().

# Pull latest widget choices into temp_filters
filters_config = TABLE_CONFIG[selected_table]["filters"]
for col in filters_config:
    w_key = f"sb_filter_{col}_{selected_table}"
    if w_key in st.session_state:
        st.session_state.temp_filters[col] = st.session_state[w_key]

# 1. Fetch filter options (cached in db.py)
all_filters = get_all_filter_values(selected_table, st.session_state.temp_filters)

# 2. Render Sidebar Filters
st.sidebar.subheader("🔍 Filters")

for col in filters_config:
    values = all_filters.get(col, [])

    if col == "date":
        # Compact Date Range Picker
        prev_dates = st.session_state.temp_filters.get(col, [])
        d1_val = prev_dates[0] if isinstance(prev_dates, (list, tuple)) and len(prev_dates) >= 1 else None
        d2_val = prev_dates[1] if isinstance(prev_dates, (list, tuple)) and len(prev_dates) >= 2 else None

        st.sidebar.caption("📅 Select Date Range")
        selected = st.sidebar.date_input(
            "Range",
            value=(d1_val, d2_val) if d1_val and d2_val else (d1_val,) if d1_val else [],
            key=f"sb_filter_{col}_{selected_table}",
            label_visibility="collapsed"
        )
    else:
        selected = st.sidebar.multiselect(
            format_column(col),
            values,
            key=f"sb_filter_{col}_{selected_table}",
            default=[v for v in st.session_state.temp_filters.get(col, []) if v in values]
        )

    # Update temp state immediately for cascading effect next rerun
    st.session_state.temp_filters[col] = selected

# 3. Sidebar Reset
if st.sidebar.button("🔄 Reset Filters", use_container_width=True):
    st.session_state.applied_filters = {}
    st.session_state.temp_filters = {}
    st.rerun()

# -------------------------------
# DATA FETCHING (ISOLATED SPINNER)
# -------------------------------
with st.spinner(f"Loading {TABLE_CONFIG[selected_table]['name']}..."):
    _dash_start = time.perf_counter()

    # Only use filters if they actually contain selections
    active_filters = {k: v for k, v in st.session_state.temp_filters.items() if v}

    if active_filters:
        logger.info(f"Fetching filtered data for {selected_table}: {active_filters}")
        df = fetch_data(selected_table, filters=active_filters, limit=200)
    else:
        logger.info(f"Fetching default data for {selected_table}")
        df = fetch_data(selected_table, limit=200)

    _dash_end = time.perf_counter()
    logger.info(f"Data load took {_dash_end - _dash_start:.4f} seconds")

# (Month derivation removed as requested)

# -------------------------------
# CLEAN DATA
# -------------------------------
# Drop system columns
df = df.drop(columns=['version', 'updated_at', 'is_active'], errors='ignore')

# Remove zero/empty columns
df = remove_zero_columns(df)

# Apply Indian Comma formatting (Lakhs/Crores)
# Handles both Currency (Values) and Quantities (Qty)
df = apply_currency_format(df)

# Standardize Headers
df.columns = [format_column(c) for c in df.columns]

# Format Date/Month columns to show only the date (remove 00:00:00)
for col in ["Date", "Month"]:
    if col in df.columns:
        try:
            df[col] = pd.to_datetime(df[col]).dt.date
        except Exception:
            pass

# -------------------------------
# DISPLAY (FLEXIBLE DATAFRAME)
# -------------------------------
# Use native formatting ONLY for columns that are still numeric
numeric_cols = [
    c for c in df.columns
    if any(x in c for x in ["Qty", "Value"]) and pd.api.types.is_numeric_dtype(df[c])
]
config = {c: st.column_config.NumberColumn(format="%.2f") for c in numeric_cols}

# Apply Pandas styling to force bold and black headers while keeping the table interactive
styled_df = df.style.set_table_styles(
    [{'selector': 'th', 'props': [('font-weight', 'bold !important'), ('color', 'black !important')]}]
)

st.dataframe(styled_df, column_config=config, use_container_width=True, hide_index=True)
