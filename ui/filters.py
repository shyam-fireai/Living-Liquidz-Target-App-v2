"""Cascading sidebar filters shared by the dashboard and edit screens."""

import streamlit as st

from config import TableConfig
from db.repository import get_all_filter_values
from ui.formatting import format_column


def _widget_key(prefix: str, table: str, col: str, version: int) -> str:
    # The version changes on "Reset Filters": the browser keeps a widget's last value for as long as
    # its key stays the same, so clearing session_state alone does not empty the widgets on screen.
    return f"{prefix}_filter_{col}_{table}_v{version}"


def _active(selections: dict) -> dict:
    return {k: v for k, v in selections.items() if v}


def clear_filters(cfg: TableConfig, prefix: str) -> None:
    """Empty every filter (new widget keys so the browser drops its copies too). Caller reruns."""
    state_key = f"{prefix}_filters"
    version = st.session_state.get(f"{state_key}_version", 0)
    st.session_state[state_key] = {}
    for col in cfg.filter_cols:
        st.session_state.pop(_widget_key(prefix, cfg.name, col, version), None)
    st.session_state[f"{state_key}_version"] = version + 1


def describe_filters(cfg: TableConfig, filters: dict, max_values: int = 3) -> list[str]:
    """Short human labels for the active filters, e.g. 'Branch Name: A, B +2 more'."""
    labels = []
    for col in cfg.filter_cols:
        values = filters.get(col)
        if not values:
            continue
        if col == "date":
            values = list(values)
            text = f"{values[0]} → {values[-1]}" if len(values) > 1 else str(values[0])
        else:
            shown = [v.strftime("%b %Y") if col == "month" and hasattr(v, "strftime") else str(v) for v in values]
            text = ", ".join(shown[:max_values]) + (
                f" +{len(shown) - max_values} more" if len(shown) > max_values else ""
            )
        labels.append(f"{format_column(col)}: {text}")
    return labels


def render_sidebar_filters(cfg: TableConfig, prefix: str) -> tuple[dict, bool]:
    """Render one widget per filter column. Returns (active filters, whether they changed this run)."""
    table = cfg.name
    state_key = f"{prefix}_filters"
    if st.session_state.get(f"{state_key}_table") != table:
        st.session_state[state_key] = {}
        st.session_state[f"{state_key}_table"] = table
    selections: dict = st.session_state[state_key]
    before = _active(selections)
    version = st.session_state.setdefault(f"{state_key}_version", 0)

    # Pick up what the user changed in the widgets on the previous interaction.
    for col in cfg.filter_cols:
        key = _widget_key(prefix, table, col, version)
        if key in st.session_state:
            selections[col] = st.session_state[key]

    options = get_all_filter_values(table, selections)

    st.sidebar.subheader("\U0001f50d Filters")
    for col in cfg.filter_cols:
        key = _widget_key(prefix, table, col, version)
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
        clear_filters(cfg, prefix)
        st.rerun()

    active = _active(selections)
    return active, active != before
