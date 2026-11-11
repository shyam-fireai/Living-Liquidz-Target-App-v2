"""Dashboard: summary cards, a paged table (paging done by ClickHouse), and CSV/Excel export."""

import html
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

ROW_CHOICES = {"200": 200, "500": 500, "1,000": 1_000, "5,000": 5_000, "All": MAX_EXPORT_ROWS}


def _go(page: str) -> None:
    st.session_state.page = page
    st.rerun()


def _header(cfg: TableConfig) -> None:
    if not cfg.editable:  # generated tables: no Edit / Upload
        (col_history,) = render_header(title=cfg.display_name, buttons=1)
    else:
        col_edit, col_upload, col_history = render_header(title=cfg.display_name, buttons=3)
        if col_edit.button("📝 Edit", width="stretch"):
            _go("edit")
        if col_upload.button("📤 Upload", width="stretch"):
            _go("upload")
    if col_history.button("🕒 History", width="stretch"):
        _go("history")


KPI_CSS = """
<style>
.kpi-row { display: flex; flex-wrap: wrap; gap: 12px; margin: 4px 0 12px; }
.kpi-card {
    flex: 1 1 130px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 14px 18px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}
.kpi-value {
    font-size: 1.75rem; font-weight: 700; color: #0f172a; line-height: 1.2;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.kpi-label {
    font-size: 0.85rem; font-weight: 500; color: #64748b; margin-top: 4px;
}
@media (max-width: 640px) {
    .kpi-card { padding: 10px 14px; }
    .kpi-value { font-size: 1.35rem; }
}
</style>
"""


def _kpi_cards_html(cards: list[tuple[str, str, str | None]]) -> str:
    """Big value on top, small label below. Hovering a card shows the exact total."""
    items = []
    for label, value, exact in cards:
        tip = f' title="Exact total: {html.escape(exact)}"' if exact else ""
        items.append(
            f'<div class="kpi-card"{tip}>'
            f'<div class="kpi-value">{html.escape(value)}</div>'
            f'<div class="kpi-label">{html.escape(label)}</div>'
            "</div>"
        )
    return KPI_CSS + f'<div class="kpi-row">{"".join(items)}</div>'


def _summary_cards(cfg: TableConfig, totals: dict) -> None:
    """Rows, branches, and Target/Incentive 1 totals (other levels are not summarised)."""
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
    st.markdown(_kpi_cards_html(cards), unsafe_allow_html=True)


def _filter_chips(cfg: TableConfig, filters: dict) -> None:
    labels = describe_filters(cfg, filters)
    if not labels:
        return
    chips, clear = st.columns([6, 1], vertical_alignment="center")
    chips.markdown(" ".join(f":blue-badge[{label}]" for label in labels))
    if clear.button("✕ Clear filters", width="stretch", key="dash_clear_filters"):
        clear_filters(cfg, "sb")
        st.rerun()


def page_window(total_rows: int, page_size: int, page: int) -> tuple[int, int, int]:
    """(page clamped to 1..pages, number of pages, row offset) for 1-based `page`."""
    pages = max(1, -(-total_rows // page_size))
    page = min(max(1, page), pages)
    return page, pages, (page - 1) * page_size


def _current_page(cfg: TableConfig, filters: dict, page_size: int) -> int:
    """Page number for this table; back to page 1 whenever the filters or page size change."""
    key = f"dash_page_{cfg.name}"
    signature = repr((sorted((k, list(map(str, v))) for k, v in filters.items()), page_size))
    if st.session_state.get(f"{key}_sig") != signature:
        st.session_state[f"{key}_sig"] = signature
        st.session_state[key] = 1
    return st.session_state[key]


def _set_page(cfg: TableConfig, page: int) -> None:
    st.session_state[f"dash_page_{cfg.name}"] = page


def _pager(cfg: TableConfig, page: int, pages: int) -> None:
    if pages <= 1:
        return
    _, prev, label, nxt = st.columns([4, 1.1, 1.4, 1.1], vertical_alignment="center")
    prev.button(
        "◀ Previous", width="stretch", disabled=page <= 1, key="dash_prev", on_click=_set_page, args=(cfg, page - 1)
    )
    label.markdown(
        f"<div style='text-align:center'>Page <b>{page:,}</b> of <b>{pages:,}</b></div>", unsafe_allow_html=True
    )
    nxt.button(
        "Next ▶", width="stretch", disabled=page >= pages, key="dash_next", on_click=_set_page, args=(cfg, page + 1)
    )


def _download_menu(cfg: TableConfig, filters: dict, total_rows: int) -> None:
    """One "Download" button; the menu offers CSV or Excel of *all* matching rows (not just this page)."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = f"{cfg.name}_{stamp}"
    count = min(total_rows, MAX_EXPORT_ROWS)
    with st.popover("⬇️ Download", width="stretch"):
        st.caption(
            f"All **{count:,}** matching rows"
            + (f" (first {MAX_EXPORT_ROWS:,})" if total_rows > MAX_EXPORT_ROWS else "")
            + ", with the current filters."
        )
        # Files are built only when clicked (callable data).
        st.download_button(
            "📄 CSV (.csv)",
            data=lambda: to_csv_bytes(cfg, fetch_for_export(cfg.name, filters)),
            file_name=f"{base}.csv",
            mime="text/csv",
            width="stretch",
            on_click="ignore",
        )
        st.download_button(
            "📊 Excel (.xlsx)",
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
    page_size = ROW_CHOICES[show_label]
    page, pages, offset = page_window(totals["rows"], page_size, _current_page(cfg, filters, page_size))
    with st.spinner(f"Loading {cfg.display_name}..."):
        try:
            df = fetch_data(cfg.name, filters=filters or None, limit=page_size, offset=offset)
        except Exception as e:
            show_error("Could not load rows from the database. Please try again in a moment.", e)
            return

    # Table toolbar: row count on the left; page size and download on the right.
    info, picker, download = st.columns([4, 1.4, 1.4], vertical_alignment="bottom")
    first, last = (offset + 1, offset + len(df)) if len(df) else (0, 0)
    info.caption(f"Showing **{first:,}–{last:,}** of **{totals['rows']:,}** rows · newest first")
    picker.selectbox("Rows to show", list(ROW_CHOICES), key=f"dash_rows_{cfg.name}")
    with download:
        _download_menu(cfg, filters, totals["rows"])
    # Room for the table's own hover toolbar, which floats just above the table and would
    # otherwise cover the Download button.
    st.markdown("<div style='height: 1.75rem'></div>", unsafe_allow_html=True)

    df = df.drop(columns=list(SYSTEM_COLUMNS), errors="ignore")
    df = remove_zero_columns(df)
    if cfg.date_col in df.columns:
        df[cfg.date_col] = pd.to_datetime(df[cfg.date_col]).dt.date
    df = apply_currency_format(df)
    df.columns = [format_column(c) for c in df.columns]
    st.dataframe(df, width="stretch", hide_index=True)

    _pager(cfg, page, pages)
