"""History: who uploaded / edited what and when (from the audit log), times in IST."""

import logging
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from config import DISPLAY_TZ, TABLES
from db.audit import HISTORY_LIMIT, fetch_entry_states, fetch_history, history_users
from services.history import (
    ACTION_LABELS,
    DEFAULT_ACTIONS,
    describe,
    format_ist,
    ist_day_bounds,
    state_diff,
    table_label,
)
from ui.components import go_to, render_header, show_error
from ui.formatting import DIFF_NEW_STYLE, DIFF_OLD_STYLE, format_column, format_indian_number

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 30


def _filters() -> tuple[tuple[int, int], list[str], list[str], list[str]]:
    today = datetime.now(DISPLAY_TZ).date()
    c_date, c_action, c_user, c_table = st.columns([1.7, 1.7, 1.5, 1.5])
    picked = c_date.date_input(
        "Date range (IST)", value=(today - timedelta(days=DEFAULT_DAYS - 1), today), max_value=today, key="hist_dates"
    )
    picked = list(picked) if isinstance(picked, (list, tuple)) else [picked]
    if not picked:  # cleared by the user -> default range
        picked = [today - timedelta(days=DEFAULT_DAYS - 1), today]
    actions = c_action.multiselect(
        "Action", list(ACTION_LABELS), default=list(DEFAULT_ACTIONS), format_func=ACTION_LABELS.get, key="hist_actions"
    )
    try:
        user_options = history_users()
    except Exception:
        logger.exception("Could not load History users")
        user_options = []
    users = c_user.multiselect("User", user_options, placeholder="All users", key="hist_users")
    tables = c_table.multiselect(
        "Table", list(TABLES), format_func=table_label, placeholder="All tables", key="hist_tables"
    )
    return ist_day_bounds(picked[0], picked[-1]), actions, users, tables


def _show_details(entry: pd.Series) -> None:
    st.markdown(
        f"**{ACTION_LABELS.get(entry['action_type'], entry['action_type'])}** · {entry['When (IST)']} · "
        f"{entry['user_email']} · {table_label(entry['target_table'])}"
    )
    if entry["action_type"] != "EDIT":
        st.caption(entry["Details"] or "No further details recorded for this entry.")
        return
    try:
        before, after = fetch_entry_states(entry["log_id"])
    except Exception as e:
        show_error("Could not load the details of this entry.", e)
        return
    cfg = TABLES.get(entry["target_table"])
    changes = state_diff(before, after, cfg.key_cols if cfg else ())
    if not changes:
        st.caption(entry["Details"] or "No cell-level details recorded for this entry.")
        return

    def fmt(col, value):
        if value is None:
            return ""
        if cfg and col in cfg.value_cols:
            return format_indian_number(value, show_rupee=cfg.currency and "value" in col)
        if cfg and col == cfg.date_col:
            return str(value)[:10]
        return str(value)

    view = pd.DataFrame(
        {
            "Row": [c["Row"] for c in changes],
            "Column": [format_column(c["Column"]) for c in changes],
            "Old": [fmt(c["Column"], c["Old"]) for c in changes],
            "New": [fmt(c["Column"], c["New"]) for c in changes],
        }
    )
    styled = view.style.map(lambda _: DIFF_OLD_STYLE, subset=["Old"]).map(lambda _: DIFF_NEW_STYLE, subset=["New"])
    st.dataframe(styled, width="stretch", hide_index=True)


def history_screen() -> None:
    (col_back,) = render_header(title="History", buttons=1, crumb="Audit log")
    col_back.button("Back", icon=":material/arrow_back:", width="stretch", on_click=go_to, args=("dashboard",))

    (start_ts, end_ts), actions, users, tables = _filters()
    try:
        log, total = fetch_history(start_ts, end_ts, actions, users, tables)
    except Exception as e:
        show_error("Could not load the history. Please try again in a moment.", e)
        return
    if log.empty:
        st.info(
            "**No activity matches these filters.** Try a wider date range or fewer filters.",
            icon=":material/search_off:",
        )
        return

    log["When (IST)"] = log["ts"].map(format_ist)
    log["Details"] = [
        describe(a, m, e) for a, m, e in zip(log["action_type"], log["metadata"], log["error_message"], strict=True)
    ]
    view = pd.DataFrame(
        {
            "When (IST)": log["When (IST)"],
            "User": log["user_email"],
            "Action": log["action_type"].map(lambda a: ACTION_LABELS.get(a, a)),
            "Table": log["target_table"].map(lambda t: table_label(t) if t else "—"),
            "Rows": log["record_count"].map(lambda n: f"{int(n):,}" if n else ""),
            "Details": log["Details"],
        }
    )

    more = f" (the newest {HISTORY_LIMIT:,})" if total > len(log) else ""
    st.caption(f"Showing **{len(log):,}** of **{total:,}** entries{more} · newest first · click a row for details")
    event = st.dataframe(
        view, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row", key="hist_table"
    )

    selected = event.selection.rows if event and event.selection else []
    if selected:
        st.divider()
        _show_details(log.iloc[selected[0]])
