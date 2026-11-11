import logging

import pandas as pd
import streamlit as st

from config import BRANCH_MONTHLY, DATE_BRANCH, SYSTEM_COLUMNS, TableConfig
from db.audit import log_audit_action
from db.repository import fetch_data
from services.targets import save_targets
from services.validation import clean_dataframe_for_db
from ui.components import render_header
from ui.filters import render_sidebar_filters
from ui.formatting import apply_currency_format, format_column

logger = logging.getLogger(__name__)


def _reset_edit_state(table: str) -> None:
    st.session_state.edit_original_df = None
    st.session_state.edit_last_table = table
    st.session_state.setdefault("editor_version", 0)


def _changed_mask(original: pd.DataFrame, edited: pd.DataFrame) -> pd.Series:
    """Rows whose values differ, ignoring display formatting (rupee signs, commas, case)."""
    norm_orig = clean_dataframe_for_db(original).astype(str).reset_index(drop=True)
    norm_edit = clean_dataframe_for_db(edited).astype(str).reset_index(drop=True)
    mask = (norm_orig.values != norm_edit.values).any(axis=1)
    return pd.Series(mask, index=original.index)


def _replaced_keys(cfg: TableConfig, original_rows: pd.DataFrame, new_rows: pd.DataFrame) -> list[dict]:
    """Old key values of rows whose key columns were edited."""
    norm_old = clean_dataframe_for_db(original_rows[list(cfg.key_cols)]).astype(str)
    norm_new = clean_dataframe_for_db(new_rows[list(cfg.key_cols)]).astype(str)
    changed = (norm_old != norm_new).any(axis=1)
    return original_rows.loc[changed, list(cfg.key_cols)].to_dict(orient="records")


def edit_screen(cfg: TableConfig) -> None:
    table = cfg.name
    if st.session_state.get("edit_last_table") != table:
        _reset_edit_state(table)

    col_back, _ = render_header(title=f"Editing: {cfg.display_name}", hide_upload=True)
    with col_back:
        if st.button("⬅️ Back", width="stretch"):
            st.session_state.page = "dashboard"
            st.rerun()

    flash = st.session_state.pop("edit_flash", None)
    if flash:
        (st.success if flash["ok"] else st.warning)(flash["message"])

    filters, changed = render_sidebar_filters(cfg, prefix="ed")
    if changed:
        st.session_state.edit_original_df = None  # new baseline for the new selection

    with st.spinner("Loading records..."):
        df = fetch_data(table, filters=filters or None)

    if df.empty:
        st.warning("No data available")
        return

    display_df = apply_currency_format(df.drop(columns=list(SYSTEM_COLUMNS), errors="ignore"))
    baseline = st.session_state.edit_original_df
    if baseline is None or baseline.shape != display_df.shape or not baseline.index.equals(display_df.index):
        st.session_state.edit_original_df = display_df.copy()
    original_df = st.session_state.edit_original_df

    hint = "\U0001f4a1 **To save data**, first edit any cell in the table below."
    st.info(("ℹ️ **Showing first 200 records.** Use filters to narrow down. | " if not filters else "") + hint)

    edited_df = st.data_editor(
        display_df,
        width="stretch",
        num_rows="fixed",
        column_config={c: st.column_config.Column(label=format_column(c)) for c in display_df.columns},
        hide_index=False,
        key=f"editor_{table}_{st.session_state.editor_version}",
    )
    edited_df.index = original_df.index
    edited_df.columns = original_df.columns

    changed_mask = _changed_mask(original_df, edited_df)
    if not changed_mask.any():
        return

    rows_to_update = edited_df[changed_mask]
    original_rows = original_df[changed_mask]

    st.warning("⚠️ Pending Changes Detected. Review summary below to Save.")
    st.divider()
    st.subheader("\U0001f50d Changes Summary")
    st.markdown("### \U0001f7e5 Before")
    st.dataframe(original_rows.rename(columns=format_column), width="stretch")
    st.markdown("### \U0001f7e9 After")
    st.dataframe(rows_to_update.rename(columns=format_column), width="stretch")
    st.info("\U0001f449 Review your changes above and click Final Save below.")

    if not st.button("\U0001f4be Final Save", width="stretch", type="primary"):
        return

    try:
        replaced = _replaced_keys(cfg, original_rows, rows_to_update)
        with st.spinner("Saving..."):
            report = save_targets(table, rows_to_update, replaced_keys=replaced)

        if report.nothing_saved:
            log_audit_action("ERROR", target_table=table, error_message=report.message)
            st.error(report.message)
            return

        log_audit_action(
            "EDIT",
            target_table=table,
            record_count=report.saved_rows,
            # stored as clean values (numbers, not "₹1,00,000.00") so the audit log is queryable
            before_state=clean_dataframe_for_db(original_rows).to_dict(orient="records"),
            after_state=clean_dataframe_for_db(rows_to_update).to_dict(orient="records"),
            error_message="; ".join(report.errors) or None,
        )
        if report.daily_rows:
            log_audit_action(
                "EDIT",
                target_table=DATE_BRANCH,
                record_count=report.daily_rows,
                metadata={"source": f"{BRANCH_MONTHLY}_edit_sync"},
            )

        st.session_state.edit_flash = {"ok": report.ok, "message": f"✅ {report.message}"}
        st.session_state.edit_original_df = None
        st.session_state.editor_version += 1
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        logger.exception("Edit save failed for %s", table)
        log_audit_action("ERROR", target_table=table, error_message=f"Edit UI Crash: {e}")
        st.error(f"❌ Error: {e}")
