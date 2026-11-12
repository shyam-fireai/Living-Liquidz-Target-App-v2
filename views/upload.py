"""Upload screen: validate every row, preview the changes, then save only what changes."""

import logging

import pandas as pd
import streamlit as st

from config import BRANCH_MONTHLY, DATE_BRANCH, TableConfig
from db.audit import log_audit_action
from db.repository import fetch_existing, known_values
from services.changes import NEW, UNCHANGED, UPDATED, classify_changes
from services.targets import generate_daily_targets_from_monthly, save_targets
from services.validation import robust_read_csv, validate_upload
from ui.components import go_to, render_header, show_error
from ui.formatting import format_column, format_indian_number

logger = logging.getLogger(__name__)

STATUS_LABELS = {NEW: "New", UPDATED: "Updated", UNCHANGED: "Unchanged"}


def _fmt(cfg: TableConfig, col: str, value) -> str:
    return format_indian_number(value, show_rupee=cfg.currency and "value" in col)


def _state_key(table: str, name: str) -> str:
    return f"upload_{name}_{table}"


def _reset_upload(table: str) -> None:
    st.session_state.pop(_state_key(table, "result"), None)
    st.session_state[_state_key(table, "nonce")] = st.session_state.get(_state_key(table, "nonce"), 0) + 1


def _format_help(cfg: TableConfig) -> None:
    date_rule = (
        "`month` must be the **1st day** of the month, e.g. `2026-03-01` (or `01-03-2026`)."
        if cfg.date_col == "month"
        else "`date` must be a valid date, e.g. `2026-04-17` (or `17-04-2026`)."
    )
    # Always visible (not collapsible) so users see the rules every time they upload.
    st.info(
        "**File format**\n\n"
        f"- Columns: `{'`, `'.join(cfg.columns)}`\n"
        f"- {date_rule}\n"
        "- Text values are saved in UPPER CASE; blank numbers are saved as 0.\n"
        "- Numbers may contain ₹ and commas. Negative numbers are not allowed.\n"
        "- Each key (" + " + ".join(format_column(c) for c in cfg.key_cols) + ") may appear only once.",
        icon=":material/info:",
    )
    st.download_button(
        "Download sample CSV",
        pd.DataFrame(columns=list(cfg.columns)).to_csv(index=False),
        file_name=f"{cfg.name}_sample.csv",
        icon=":material/download:",
    )


def _show_done(cfg: TableConfig, result: dict) -> None:
    if result["ok"]:
        st.success(f"**Upload finished.** {result['message']}", icon=":material/check_circle:")
    else:
        st.warning(f"**Upload finished.** {result['message']}", icon=":material/warning:")
    st.caption(f"File: {result['file_name']} · {result['summary']}")
    if st.button("Upload another file", icon=":material/upload:", type="primary"):
        _reset_upload(cfg.name)
        st.rerun()


def _show_issues(check, cfg: TableConfig, file_name: str) -> bool:
    """Render problems. Returns True if the upload may continue."""
    frame = check.issues_frame()
    if check.errors:
        bad_rows = len({i.row for i in check.errors if i.row is not None})
        where = f" in {bad_rows} row(s)" if bad_rows else ""
        st.error(
            f"**{len(check.errors)} problem(s) found{where}. Nothing has been saved.** "
            "Fix them in the file and upload it again.",
            icon=":material/error:",
        )
        st.dataframe(frame, width="stretch", hide_index=True)
        st.download_button(
            "Download problem list (CSV)",
            frame.to_csv(index=False),
            file_name=f"problems_{file_name}",
            icon=":material/download:",
        )
        return False
    if check.warnings:
        st.warning(f"**{len(check.warnings)} warning(s).** Please check before saving.", icon=":material/warning:")
        st.dataframe(frame, width="stretch", hide_index=True)
    return True


def _show_changes(cfg: TableConfig, changes) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows in file", len(changes.rows))
    c2.metric("New", changes.count(NEW))
    c3.metric("Updated", changes.count(UPDATED))
    c4.metric("Unchanged", changes.count(UNCHANGED))

    updated = changes.rows[changes.rows["status"] == UPDATED]
    if not updated.empty:
        with st.expander(f"What changes in the {len(updated)} updated row(s)", expanded=True):
            detail = [
                {
                    "Row": r["_row"],
                    **{format_column(k): (r[k].date() if k == cfg.date_col else r[k]) for k in cfg.key_cols},
                    "Column": format_column(col),
                    "Old": _fmt(cfg, col, old),
                    "New": _fmt(cfg, col, new),
                }
                for _, r in updated.iterrows()
                for col, old, new in r["changes"]
            ]
            st.dataframe(pd.DataFrame(detail), width="stretch", hide_index=True)

    with st.expander("All rows in the file", expanded=False):
        view = changes.rows.copy()
        view.insert(0, "Status", view["status"].map(STATUS_LABELS))
        view[cfg.date_col] = view[cfg.date_col].dt.date
        for col in cfg.value_cols:
            view[col] = view[col].map(lambda v, c=col: _fmt(cfg, c, v))
        view = view.drop(columns=["status", "changes"]).rename(columns={"_row": "Row"})
        st.dataframe(view.rename(columns=format_column), width="stretch", hide_index=True)


def _show_daily_preview(rows: pd.DataFrame) -> None:
    if rows.empty:
        return
    with st.expander("Daily split preview (Date & Branch Wise Target)", expanded=False):
        labels = [f"{r.month:%b %Y} · {r.branch_name} · {r.series_group}" for r in rows.itertuples()]
        choice = st.selectbox("Row", range(len(labels)), format_func=lambda i: labels[i])
        daily = generate_daily_targets_from_monthly(rows.iloc[[choice]])
        targets = [c for c in daily.columns if c.startswith("target_value") and daily[c].any()]
        if not targets:
            st.info("All targets are 0 for this row.")
            return
        view = pd.DataFrame({"Date": daily["date"].dt.date, "Day": daily["date"].dt.strftime("%a")})
        for col in targets:
            view[format_column(col)] = daily[col].map(format_indian_number)
        st.dataframe(view, width="stretch", hide_index=True, height=300)
        totals = " · ".join(f"{format_column(c)} {format_indian_number(round(daily[c].sum(), 2))}" for c in targets)
        st.caption(f"{len(daily)} days (Mon–Thu weight 3, Fri–Sun weight 5). Totals: {totals} = monthly ✓")


def _save(cfg: TableConfig, changes, file_name: str) -> None:
    to_save = changes.to_save[list(cfg.columns)]
    with st.spinner(f"Saving {len(to_save)} row(s)..."):
        report = save_targets(cfg.name, to_save)

    if report.nothing_saved:
        log_audit_action("ERROR", target_table=cfg.name, error_message=report.message)
        st.error(report.message, icon=":material/error:")
        return

    meta = {"file_name": file_name, "new": changes.count(NEW), "updated": changes.count(UPDATED)}
    meta["unchanged"] = changes.count(UNCHANGED)
    log_audit_action(
        "UPLOAD",
        target_table=cfg.name,
        record_count=report.saved_rows,
        metadata=meta,
        error_message="; ".join(report.errors) or None,
    )
    if report.daily_rows:
        log_audit_action(
            "UPLOAD",
            target_table=DATE_BRANCH,
            record_count=report.daily_rows,
            metadata={"source": f"{BRANCH_MONTHLY}_upload", "file_name": file_name},
        )
    st.session_state[_state_key(cfg.name, "result")] = {
        "ok": report.ok,
        "message": report.message,
        "summary": changes.summary,
        "file_name": file_name,
    }
    st.rerun()


def upload_screen(cfg: TableConfig) -> None:
    table = cfg.name
    (col_back,) = render_header(title=f"Upload: {cfg.display_name}", buttons=1, crumb="Sales targets")
    col_back.button("Back", icon=":material/arrow_back:", width="stretch", on_click=go_to, args=("dashboard",))

    st.divider()
    result = st.session_state.get(_state_key(table, "result"))
    if result:
        _show_done(cfg, result)
        return

    _format_help(cfg)
    nonce = st.session_state.get(_state_key(table, "nonce"), 0)
    uploaded = st.file_uploader("Upload CSV", type=["csv"], key=f"uploader_{table}_{nonce}")
    if uploaded is None:
        return

    logger.info("File uploaded: %s for table %s", uploaded.name, table)
    try:
        raw = robust_read_csv(uploaded)
    except Exception as e:
        show_error("Could not read the file. Is it a CSV export?", e)
        return

    try:
        known = known_values(table)
    except Exception:
        logger.exception("Could not load known values for %s", table)
        known = {}
    check = validate_upload(raw, cfg, known)
    if not _show_issues(check, cfg, uploaded.name):
        return

    rows = check.rows
    try:
        changes = classify_changes(rows, fetch_existing(table, rows), cfg)
    except Exception as e:
        show_error("Could not compare the file with the database. Please try again.", e)
        return

    _show_changes(cfg, changes)
    if table == BRANCH_MONTHLY:
        _show_daily_preview(changes.to_save)

    if changes.to_save.empty:
        st.info("Nothing to save: every row in the file already matches the database.", icon=":material/info:")
        return

    confirmed = True
    if check.warnings:
        confirmed = st.checkbox("I have checked the warnings above and want to save anyway")
    n = len(changes.to_save)
    label = f"Save {n} row(s)" + (" (unchanged rows are skipped)" if changes.count(UNCHANGED) else "")
    if st.button(label, icon=":material/save:", type="primary", disabled=not confirmed):
        _save(cfg, changes, uploaded.name)
