"""Dashboard: summary cards, filtered table with a visible row count, and CSV/Excel export."""

import logging
from datetime import datetime

import pandas as pd
import streamlit as st

from config import SYSTEM_COLUMNS, TableConfig
from db.repository import MAX_EXPORT_ROWS, fetch_data, fetch_for_export, summarize
from services.export import to_csv_bytes, to_excel_bytes
from ui.components import render_header, show_error
from ui.filters import clear_filters, describe_filters, render_sidebar_filters
from ui.formatting import (
    apply_currency_format,
    format_column,
    format_indian_compact,
    format_indian_number,
    remove_zero_columns,
)

logger = logging.getLogger(__name__)

ROW_CHOICES = {"200": 200, "1,000": 1_000, "5,000": 5_000, "All": MAX_EXPORT_ROWS}


def _header(cfg: TableConfig) -> None:
    if not cfg.editable:
        render_header(title=cfg.display_name, hide_upload=True)
        return
    col_edit, col_upload = render_header(title=cfg.display_name)
    with col_edit:
        if st.button("\U0001f4dd Edit", width="stretch"):
            st.session_state.page = "edit"
            st.rerun()
    with col_upload:
        if st.button("\U0001f4e4 Upload", width="stretch"):
            st.session_state.page = "upload"
            st.rerun()


def _summary_cards(cfg: TableConfig, totals: dict) -> None:
    """Rows, branches, and Target/Incentive 1 totals; other non-zero levels as a caption."""
    first_target = cfg.value_cols[0]  # target_value1 / target_qty1
    money = cfg.currency
    # (label, short value, exact value for the tooltip)
    cards = [
        ("Rows", f"{totals['rows']:,}", None),
        ("Branches", f"{totals['branches']:,}", None),
        (
            format_column(first_target),
            format_indian_compact(totals[first_target], show_rupee=money),
            format_indian_number(totals[first_target], show_rupee=money),
        ),
    ]
    if totals["incentive_value1"]:  # daily targets carry no incentives
        cards.append(
            (
                "Incentive Value1",
                format_indian_compact(totals["incentive_value1"]),
                format_indian_number(totals["incentive_value1"]),
            )
        )
    for col, (label, value, exact) in zip(st.columns(len(cards)), cards, strict=True):
        col.metric(label, value, help=f"Exact total: {exact}" if exact else None)

    extra = [
        f"{format_column(c)} {format_indian_number(totals[c], show_rupee=money or 'incentive' in c)}"
        for c in cfg.value_cols[2:]
        if totals.get(c)
    ]
    if extra:
        st.caption("Other totals: " + " · ".join(extra))


def _filter_chips(cfg: TableConfig, filters: dict) -> None:
    labels = describe_filters(cfg, filters)
    if not labels:
        return
    chips, clear = st.columns([6, 1], vertical_alignment="center")
    chips.markdown(" ".join(f":blue-badge[{label}]" for label in labels))
    if clear.button("✕ Clear filters", width="stretch", key="dash_clear_filters"):
        clear_filters(cfg, "sb")
        st.rerun()


def _downloads(cfg: TableConfig, filters: dict, total_rows: int) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = f"{cfg.name}_{stamp}"
    note = f" (first {MAX_EXPORT_ROWS:,})" if total_rows > MAX_EXPORT_ROWS else ""
    c1, c2, _ = st.columns([1.3, 1.3, 4])
    # Files are built only when clicked (callable data), from *all* matching rows.
    c1.download_button(
        f"⬇️ CSV{note}",
        data=lambda: to_csv_bytes(cfg, fetch_for_export(cfg.name, filters)),
        file_name=f"{base}.csv",
        mime="text/csv",
        width="stretch",
        on_click="ignore",
    )
    c2.download_button(
        f"⬇️ Excel{note}",
        data=lambda: to_excel_bytes(cfg, fetch_for_export(cfg.name, filters)),
        file_name=f"{base}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        on_click="ignore",
    )


def dashboard_screen(cfg: TableConfig) -> None:
    _header(cfg)
    filters, _ = render_sidebar_filters(cfg, prefix="sb")

    try:
        totals = summarize(cfg.name, filters or None)
    except Exception as e:
        show_error("Could not load data from the database. Please try again in a moment.", e)
        return

    _filter_chips(cfg, filters)
    if totals["rows"] == 0:
        st.info(
            "\U0001f50e **No rows match these filters.** Try removing a filter"
            + (" or use ✕ Clear filters above." if filters else ".")
        )
        return

    _summary_cards(cfg, totals)

    show_label = st.session_state.get(f"dash_rows_{cfg.name}", "200")
    limit = ROW_CHOICES[show_label]
    with st.spinner(f"Loading {cfg.display_name}..."):
        try:
            df = fetch_data(cfg.name, filters=filters or None, limit=limit)
        except Exception as e:
            show_error("Could not load rows from the database. Please try again in a moment.", e)
            return

    info, picker = st.columns([4, 1.4], vertical_alignment="bottom")
    info.caption(f"Showing **{len(df):,}** of **{totals['rows']:,}** rows · newest first")
    picker.selectbox("Rows to show", list(ROW_CHOICES), key=f"dash_rows_{cfg.name}")

    df = df.drop(columns=list(SYSTEM_COLUMNS), errors="ignore")
    df = remove_zero_columns(df)
    if cfg.date_col in df.columns:
        df[cfg.date_col] = pd.to_datetime(df[cfg.date_col]).dt.date
    df = apply_currency_format(df)
    df.columns = [format_column(c) for c in df.columns]
    st.dataframe(df, width="stretch", hide_index=True)

    _downloads(cfg, filters, totals["rows"])
