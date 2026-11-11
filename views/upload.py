import logging

import pandas as pd
import streamlit as st

from config import BRANCH_MONTHLY, DATE_BRANCH, TableConfig
from db.audit import log_audit_action
from services.targets import save_targets
from services.validation import robust_read_csv
from ui.components import render_header
from ui.formatting import apply_currency_format, format_column, remove_zero_columns

logger = logging.getLogger(__name__)

DATE_HINTS = {
    "date": "The 'date' column must use the standard format (e.g., **2026-04-17**).",
    "month": "The 'month' column must always be the **1st day** of the month (e.g., **2026-03-01**).",
}


def _parse_dates(df: pd.DataFrame, date_col: str) -> str | None:
    """Convert the date column in place; return an error message (markdown) or None."""
    try:
        df[date_col] = pd.to_datetime(df[date_col])
    except (ValueError, TypeError):
        example = "2026-03-01" if date_col == "month" else "2026-04-17"
        return (
            f"❌ **Invalid {date_col.title()} Format:** Some dates in the '{date_col}' column are not recognized. "
            f"Please use the format **YYYY-MM-DD** (e.g., **{example}**)."
        )
    if date_col == "month":
        bad = df.index[df["month"].dt.day != 1]
        if len(bad):
            rows = [i + 2 for i in bad]  # +2: header is row 1, data is 1-based
            return (
                f"❌ **Data Format Error:** Invalid dates found in 'month' column at **Row(s): {rows}**  \n"
                "All records must use the 1st day of the month (e.g. 2026-03-01). "
                "Entire data must be fixed before upload."
            )
    return None


def upload_screen(cfg: TableConfig) -> None:
    table = cfg.name
    col_back, _ = render_header(title=f"Uploading: {cfg.display_name}", hide_upload=True)
    with col_back:
        if st.button("⬅️ Back", width="stretch"):
            st.session_state.page = "dashboard"
            st.rerun()

    st.divider()
    st.download_button(
        "\U0001f4e5 Download Sample CSV",
        pd.DataFrame(columns=list(cfg.columns)).to_csv(index=False),
        file_name=f"{table}_sample.csv",
    )
    st.info(f"-  **Format Hint:** {DATE_HINTS[cfg.date_col]}")

    uploaded_file = st.file_uploader("Upload CSV", type=["csv"], key=f"uploader_{table}")
    if uploaded_file is None:
        return

    logger.info("File uploaded: %s for table %s", uploaded_file.name, table)
    try:
        df = robust_read_csv(uploaded_file)
    except Exception as e:
        st.error(f"❌ Could not read the CSV file: {e}")
        return
    df.columns = [str(c).strip().replace("\xa0", " ").lower() for c in df.columns]

    missing = [c for c in cfg.columns if c not in df.columns]
    if missing:
        st.error(f"❌ Missing columns: {missing}")
        return

    error = _parse_dates(df, cfg.date_col)
    if error:
        st.error(error)
        return

    preview = remove_zero_columns(df).head().copy()
    preview[cfg.date_col] = preview[cfg.date_col].dt.date
    if cfg.currency:
        preview = apply_currency_format(preview)
    st.dataframe(preview.rename(columns=format_column), width="stretch")

    if st.session_state.get("upload_done"):
        st.success(f"✅ {st.session_state.get('upload_msg', '')}")
        return

    if not st.button("\U0001f680 Confirm Upload"):
        return

    with st.spinner("Uploading..."):
        report = save_targets(table, df)

    if report.nothing_saved:
        log_audit_action("ERROR", target_table=table, error_message=report.message)
        st.error(f"❌ {report.message}")
        return

    log_audit_action(
        "UPLOAD",
        target_table=table,
        record_count=report.saved_rows,
        metadata={"file_name": uploaded_file.name},
        error_message="; ".join(report.errors) or None,
    )
    if report.daily_rows:
        log_audit_action(
            "UPLOAD",
            target_table=DATE_BRANCH,
            record_count=report.daily_rows,
            metadata={"source": f"{BRANCH_MONTHLY}_upload", "file_name": uploaded_file.name},
        )

    st.session_state.upload_done = True
    st.session_state.upload_msg = report.message
    st.cache_data.clear()
    st.rerun()
