"""Edit screen: inline editing, a cell-level diff (old -> new), validation, then save."""

import logging

import pandas as pd
import streamlit as st

from config import BRANCH_MONTHLY, DATE_BRANCH, SYSTEM_COLUMNS, TableConfig
from db.audit import log_audit_action
from db.repository import fetch_data, fetch_existing
from services.edits import cell_changes, changed_rows_mask, check_edits
from services.targets import save_targets
from services.validation import clean_dataframe_for_db
from ui.components import render_header, show_error
from ui.filters import render_sidebar_filters
from ui.formatting import (
    DIFF_NEW_STYLE,
    DIFF_OLD_STYLE,
    apply_currency_format,
    format_column,
    format_indian_number,
)

logger = logging.getLogger(__name__)


def _reset_edit_state(table: str) -> None:
    st.session_state.edit_original_df = None
    st.session_state.edit_last_table = table
    st.session_state.setdefault("editor_version", 0)


def _discard_changes() -> None:
    st.session_state.edit_original_df = None
    st.session_state.editor_version += 1


def _show_flash() -> None:
    flash = st.session_state.pop("edit_flash", None)
    if not flash:
        return
    if flash["ok"]:
        st.toast(flash["message"], icon=":material/check_circle:")
    else:
        st.warning(flash["message"], icon=":material/warning:")


def _diff_table(cfg: TableConfig, diff: pd.DataFrame):
    def fmt(col, value):
        if col in cfg.value_cols:
            return format_indian_number(value, show_rupee=cfg.currency and "value" in col)
        return str(value)

    view = pd.DataFrame(
        {
            "Row": diff["Row"],
            "Column": diff["column"].map(format_column),
            "Old": [fmt(c, v) for c, v in zip(diff["column"], diff["Old"], strict=True)],
            "New": [fmt(c, v) for c, v in zip(diff["column"], diff["New"], strict=True)],
        }
    )
    return view.style.map(lambda _: DIFF_OLD_STYLE, subset=["Old"]).map(lambda _: DIFF_NEW_STYLE, subset=["New"])


def _save(cfg: TableConfig, check, original_rows: pd.DataFrame, n_cells: int) -> None:
    table = cfg.name
    with st.spinner("Saving..."):
        report = save_targets(table, check.rows[list(cfg.columns)], replaced_keys=check.replaced_keys)

    if report.nothing_saved:
        log_audit_action("ERROR", target_table=table, error_message=report.message)
        st.error(report.message, icon=":material/error:")
        return

    log_audit_action(
        "EDIT",
        target_table=table,
        record_count=report.saved_rows,
        # clean values (numbers, not "₹1,00,000.00") so the audit log is queryable
        before_state=clean_dataframe_for_db(original_rows[list(cfg.columns)]).to_dict(orient="records"),
        after_state=check.rows[list(cfg.columns)].to_dict(orient="records"),
        metadata={"changed_cells": n_cells, "key_changes": len(check.replaced_keys)},
        error_message="; ".join(report.errors) or None,
    )
    if report.daily_rows:
        log_audit_action(
            "EDIT",
            target_table=DATE_BRANCH,
            record_count=report.daily_rows,
            metadata={"source": f"{BRANCH_MONTHLY}_edit_sync"},
        )

    st.session_state.edit_flash = {"ok": report.ok, "message": report.message}
    _discard_changes()
    st.rerun()


def edit_screen(cfg: TableConfig) -> None:
    table = cfg.name
    if st.session_state.get("edit_last_table") != table:
        _reset_edit_state(table)

    (col_back,) = render_header(title=f"Edit: {cfg.display_name}", buttons=1, crumb="Sales targets")
    with col_back:
        if st.button("Back", icon=":material/arrow_back:", width="stretch"):
            st.session_state.page = "dashboard"
            st.rerun()
    _show_flash()

    filters, changed = render_sidebar_filters(cfg, prefix="ed")
    if changed:
        st.session_state.edit_original_df = None  # new baseline for the new selection

    with st.spinner("Loading records..."):
        try:
            df = fetch_data(table, filters=filters or None)
        except Exception as e:
            show_error("Could not load rows from the database. Please try again in a moment.", e)
            return
    if df.empty:
        st.info("No rows match the selected filters." if filters else "No data available.")
        return

    display_df = apply_currency_format(df.drop(columns=list(SYSTEM_COLUMNS), errors="ignore"))
    baseline = st.session_state.edit_original_df
    if baseline is None or baseline.shape != display_df.shape or not baseline.index.equals(display_df.index):
        st.session_state.edit_original_df = display_df.copy()
    original_df = st.session_state.edit_original_df

    tip = "Edit cells in the table, review the changes below, then save."
    st.caption(("Showing the first 200 rows; use the filters to narrow down. " if not filters else "") + tip)

    edited_df = st.data_editor(
        display_df,
        width="stretch",
        num_rows="fixed",
        column_config={c: st.column_config.Column(label=format_column(c)) for c in display_df.columns},
        hide_index=True,
        key=f"editor_{table}_{st.session_state.editor_version}",
    )
    edited_df.index = original_df.index
    edited_df.columns = original_df.columns

    mask = changed_rows_mask(cfg, original_df, edited_df)
    if not mask.any():
        return

    original_rows, edited_rows = original_df[mask], edited_df[mask]
    diff = cell_changes(cfg, original_rows, edited_rows)

    st.divider()
    st.subheader(f"Review {len(diff)} change(s) in {int(mask.sum())} row(s)")
    st.dataframe(_diff_table(cfg, diff), width="stretch", hide_index=True)

    check = check_edits(cfg, original_rows, edited_rows)
    if check.ok and check.replaced_keys:
        try:
            check = check_edits(cfg, original_rows, edited_rows, fetch_existing(table, check.rows))
        except Exception as e:
            show_error("Could not check the new keys against the database. Please try again.", e)
            return
    if check.ok and check.replaced_keys:
        keys_label = " / ".join(format_column(c) for c in cfg.key_cols)
        st.warning(
            f"{len(check.replaced_keys)} row(s) have a changed key ({keys_label}). On save the old row"
            + (" and its daily targets" if table == BRANCH_MONTHLY else "")
            + " will be replaced by the new one.",
            icon=":material/warning:",
        )
    if not check.ok:
        st.error(f"**{len(check.problems)} problem(s) must be fixed before saving:**", icon=":material/error:")
        st.dataframe(pd.DataFrame(check.problems), width="stretch", hide_index=True)

    col_save, col_discard, _ = st.columns([2, 1.2, 3])
    with col_discard:
        if st.button("Discard changes", icon=":material/undo:", width="stretch"):
            _discard_changes()
            st.rerun()
    with col_save:
        clicked = st.button(
            f"Save {len(diff)} change(s)",
            icon=":material/save:",
            type="primary",
            width="stretch",
            disabled=not check.ok,
        )
    if clicked:
        try:
            _save(cfg, check, original_rows, len(diff))
        except Exception as e:
            logger.exception("Edit save failed for %s", table)
            log_audit_action("ERROR", target_table=table, error_message=f"Edit save failed: {e}")
            show_error("Saving failed. Please reload the rows and check whether your change was applied.", e)
