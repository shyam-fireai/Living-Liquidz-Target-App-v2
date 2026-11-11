import logging

import pandas as pd
import streamlit as st

from config import SYSTEM_COLUMNS, TableConfig
from db.repository import fetch_data
from ui.components import render_header
from ui.filters import render_sidebar_filters
from ui.formatting import apply_currency_format, format_column, remove_zero_columns

logger = logging.getLogger(__name__)


def dashboard_screen(cfg: TableConfig) -> None:
    if cfg.editable:
        col_edit, col_upload = render_header(title=cfg.display_name)
        with col_edit:
            if st.button("\U0001f4dd Edit", width="stretch"):
                st.session_state.page = "edit"
                st.rerun()
        with col_upload:
            if st.button("\U0001f4e4 Upload", width="stretch"):
                st.session_state.page = "upload"
                st.rerun()
    else:
        render_header(title=cfg.display_name, hide_upload=True)

    filters, _ = render_sidebar_filters(cfg, prefix="sb")

    with st.spinner(f"Loading {cfg.display_name}..."):
        df = fetch_data(cfg.name, filters=filters or None)

    df = df.drop(columns=list(SYSTEM_COLUMNS), errors="ignore")
    df = remove_zero_columns(df)
    if cfg.date_col in df.columns:
        df[cfg.date_col] = pd.to_datetime(df[cfg.date_col]).dt.date
    df = apply_currency_format(df)
    df.columns = [format_column(c) for c in df.columns]

    styled = df.style.set_table_styles(
        [{"selector": "th", "props": [("font-weight", "bold !important"), ("color", "black !important")]}]
    )
    st.dataframe(styled, width="stretch", hide_index=True)
