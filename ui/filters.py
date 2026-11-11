"""Cascading sidebar filters shared by the dashboard and edit screens."""

import streamlit as st

from config import TableConfig
from db.repository import get_all_filter_values
from ui.formatting import format_column


def _widget_key(prefix: str, table: str, col: str) -> str:
    return f"{prefix}_filter_{col}_{table}"


def _active(selections: dict) -> dict:
    return {k: v for k, v in selections.items() if v}


def render_sidebar_filters(cfg: TableConfig, prefix: str) -> tuple[dict, bool]:
    """Render one widget per filter column. Returns (active filters, whether they changed this run)."""
    table = cfg.name
    state_key = f"{prefix}_filters"
    if st.session_state.get(f"{state_key}_table") != table:
        st.session_state[state_key] = {}
        st.session_state[f"{state_key}_table"] = table
    selections: dict = st.session_state[state_key]
    before = _active(selections)

    # Pick up what the user changed in the widgets on the previous interaction.
    for col in cfg.filter_cols:
        key = _widget_key(prefix, table, col)
        if key in st.session_state:
            selections[col] = st.session_state[key]

    options = get_all_filter_values(table, selections)

    st.sidebar.subheader("\U0001f50d Filters")
    for col in cfg.filter_cols:
        key = _widget_key(prefix, table, col)
        if col == "date":
            prev = list(selections.get(col) or [])
            st.sidebar.caption("\U0001f4c5 Select Date Range")
            selections[col] = st.sidebar.date_input(
                "Range", value=tuple(prev[:2]), key=key, label_visibility="collapsed"
            )
        else:
            values = options.get(col, [])
            selections[col] = st.sidebar.multiselect(
                format_column(col),
                values,
                key=key,
                default=[v for v in selections.get(col, []) if v in values],
            )

    if st.sidebar.button("\U0001f504 Reset Filters", width="stretch", key=f"{prefix}_reset_filters"):
        st.session_state[state_key] = {}
        for col in cfg.filter_cols:
            st.session_state.pop(_widget_key(prefix, table, col), None)
        st.rerun()

    active = _active(selections)
    return active, active != before
