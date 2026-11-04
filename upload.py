import streamlit as st
import pandas as pd
import io
from db import TABLE_SCHEMAS, insert_dataframe, get_client, format_column, remove_zero_columns, apply_currency_format, log_audit_action
from style_utils import inject_minimalist_theme, render_header
import logging

logger = logging.getLogger(__name__)

# -------------------------------
# REQUIRED SCHEMA (REPLACED BY db.TABLE_SCHEMAS)
# -------------------------------
REQUIRED_COLUMNS = TABLE_SCHEMAS


# -------------------------------
# DYNAMIC DAILY TARGET GENERATOR
# -------------------------------
def robust_read_csv(uploaded_file):
    """
    Robust CSV reader that handles:
    - Multiple encodings (utf-8, utf-8-sig, cp1252, latin1, iso-8859-1)
    - Non-breaking spaces (\xa0) and rogue characters
    - Variable delimiters (comma, semicolon, tab)
    - Inconsistent line terminators
    """
    raw_bytes = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    
    # Common encodings encountered in Excel exports and CSVs
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1", "iso-8859-1"]
    
    last_err = None
    for enc in encodings:
        try:
            text = raw_bytes.decode(enc)
            # Replace non-breaking spaces (\xa0) and unicode spaces with standard space
            text = text.replace('\xa0', ' ')
            
            # Read via StringIO using Python engine with sep=None to sniff delimiter
            return pd.read_csv(io.StringIO(text), sep=None, engine='python')
        except Exception as e:
            last_err = e
            continue
            
    # Fallback with replacement of un-decodable bytes
    try:
        text = raw_bytes.decode('utf-8', errors='replace').replace('\xa0', ' ')
        return pd.read_csv(io.StringIO(text), sep=None, engine='python')
    except Exception:
        raise last_err if last_err else Exception("Unable to parse CSV file.")


# -------------------------------
# DYNAMIC DAILY TARGET GENERATOR
# -------------------------------
def generate_daily_targets_from_monthly(df_monthly):
    """
    Distributes monthly target values across days of the month dynamically:
      - Weekdays (Mon - Thu): Weight 3.0
      - Weekends (Fri - Sun): Weight 5.0
      - Remainder added to last day to guarantee 0.00 exact balance.
      - Targets distributed: target_value1 to target_value5.
      - Incentive values set to None (incentive not used in date branch wise target).
    """
    def distribute_target(monthly_val, ratios, n_days):
        if monthly_val is None or pd.isna(monthly_val) or monthly_val == 0:
            return [None] * n_days
        daily_vals = []
        accumulated = 0.0
        for i in range(n_days - 1):
            val = round(monthly_val * ratios[i], 2)
            daily_vals.append(val)
            accumulated += val
        last_val = round(monthly_val - accumulated, 2)
        daily_vals.append(last_val)
        return daily_vals

    target_cols = ["target_value1", "target_value2", "target_value3", "target_value4", "target_value5"]
    df_copy = df_monthly.copy()
    for col in target_cols:
        if col in df_copy.columns:
            df_copy[col] = pd.to_numeric(df_copy[col], errors="coerce")
        else:
            df_copy[col] = None

    daily_records = []

    # Process grouped by month so multiple months in a single upload are supported
    for month_val, group in df_copy.groupby(df_copy["month"].dt.strftime("%Y-%m")):
        start_date = pd.to_datetime(f"{month_val}-01")
        days_in_month = pd.Period(f"{month_val}-01").days_in_month
        dates = pd.date_range(start_date, periods=days_in_month)

        weights = [5.0 if d.weekday() in [4, 5, 6] else 3.0 for d in dates]
        total_weight = sum(weights)
        ratios = [w / total_weight for w in weights]
        n_days = len(dates)
        date_strs = [d.strftime("%Y-%m-%d") for d in dates]

        for _, m_row in group.iterrows():
            b_name = m_row.get("branch_name", "")
            s_group = m_row.get("series_group", "")

            m_t1 = m_row["target_value1"] if pd.notna(m_row["target_value1"]) and m_row["target_value1"] != 0 else None
            m_t2 = m_row["target_value2"] if pd.notna(m_row["target_value2"]) and m_row["target_value2"] != 0 else None
            m_t3 = m_row["target_value3"] if pd.notna(m_row["target_value3"]) and m_row["target_value3"] != 0 else None
            m_t4 = m_row["target_value4"] if pd.notna(m_row["target_value4"]) and m_row["target_value4"] != 0 else None
            m_t5 = m_row["target_value5"] if pd.notna(m_row["target_value5"]) and m_row["target_value5"] != 0 else None

            daily_t1 = distribute_target(m_t1, ratios, n_days)
            daily_t2 = distribute_target(m_t2, ratios, n_days)
            daily_t3 = distribute_target(m_t3, ratios, n_days)
            daily_t4 = distribute_target(m_t4, ratios, n_days)
            daily_t5 = distribute_target(m_t5, ratios, n_days)

            for i in range(n_days):
                daily_records.append({
                    "date": date_strs[i],
                    "branch_name": b_name,
                    "series_group": s_group,
                    "target_value1": daily_t1[i] if daily_t1[i] is not None else 0.0,
                    "incentive_value1": 0.0,
                    "target_value2": daily_t2[i] if daily_t2[i] is not None else 0.0,
                    "incentive_value2": 0.0,
                    "target_value3": daily_t3[i] if daily_t3[i] is not None else 0.0,
                    "incentive_value3": 0.0,
                    "target_value4": daily_t4[i] if daily_t4[i] is not None else 0.0,
                    "incentive_value4": 0.0,
                    "target_value5": daily_t5[i] if daily_t5[i] is not None else 0.0,
                    "incentive_value5": 0.0,
                })

    df_daily = pd.DataFrame(daily_records)
    if not df_daily.empty:
        df_daily["date"] = pd.to_datetime(df_daily["date"])
    return df_daily


# -------------------------------
# UPLOAD SCREEN
# -------------------------------
def upload_screen(selected_table):
    
    # -------------------------------
    # UI THEME & HEADER
    # -------------------------------
    inject_minimalist_theme()
    display_name = selected_table.replace("_", " ").title()
    col_edit, col_upload = render_header(title=f"Uploading: {display_name}", hide_upload=True)
    
    with col_edit:
        if st.button("⬅️ Back", width="stretch"):
            st.session_state.page = "dashboard"
            st.rerun()
            
    st.divider()

    # -------------------------------
    # SAMPLE DOWNLOAD
    # -------------------------------
    expected_filename = f"{selected_table}_sample.csv"

    sample_df = pd.DataFrame(columns=REQUIRED_COLUMNS[selected_table])

    st.download_button(
        "📥 Download Sample CSV",
        sample_df.to_csv(index=False),
        file_name=expected_filename
    )

    if selected_table == "date_branch_wise_target":
        st.info("""
-  **Format Hint:** The 'date' column must use the standard format (e.g., **2026-04-17**).
""")
    else:
        st.info("""
-  **Format Hint:** The 'month' column must always be the **1st day** of the month (e.g., **2026-03-01**).
""")

    # -------------------------------
    # FILE UPLOAD
    # -------------------------------
    uploaded_file = st.file_uploader("Upload CSV", type=["csv"], key=f"uploader_{selected_table}")

    if uploaded_file is not None:
        logger.info(f"File uploaded: {uploaded_file.name} for table: {selected_table}")

        try:
            df = robust_read_csv(uploaded_file)
            df.columns = [str(c).strip().replace('\xa0', ' ').lower() for c in df.columns]

            required_cols = REQUIRED_COLUMNS[selected_table]

            logger.info("Verifying column schema...")
            missing = [col for col in required_cols if col not in df.columns]
            if missing:
                logger.error(f"Validation Failed: Missing columns {missing}")
                st.error(f"❌ Missing columns: {missing}")
                return
            logger.info("Column validation successful.")

            # -------------------------------
            # DATE CONVERSION
            # -------------------------------
            if "month" in df.columns:
                try:
                    df["month"] = pd.to_datetime(df["month"])
                except Exception:
                    st.error("❌ **Invalid Month Format:** Some dates in the 'month' column are not recognized. Please use the format **YYYY-MM-DD** (e.g., **2026-03-01**).")
                    return
                
                # Strict Validation: Must be 1st of the month
                invalid_rows = df[df["month"].dt.day != 1]
                if not invalid_rows.empty:
                    # Row numbers are 2-indexed (+2) because header is Row 1
                    err_row_indices = [i + 2 for i in invalid_rows.index.tolist()]
                    st.error(f"❌ **Data Format Error:** Invalid dates found in 'month' column at **Row(s): {err_row_indices}**")
                    st.warning("All records must use the 1st day of the month (e.g. 2026-03-01). Entire data must be fixed before upload.")
                    return

            if "date" in df.columns:
                try:
                    df["date"] = pd.to_datetime(df["date"])
                except Exception:
                    st.error("❌ **Invalid Date Format:** Some dates in the 'date' column are not recognized. Please use the format **YYYY-MM-DD** (e.g., **2026-04-17**).")
                    return

            # -------------------------------
            # PREVIEW (Hide zero columns, format currency, and rename headers for display)
            # -------------------------------
            preview_df = remove_zero_columns(df).head().copy()
            
            # Show only the date part in preview (remove 00:00:00)
            for col in ["month", "date"]:
                if col in preview_df.columns:
                    preview_df[col] = pd.to_datetime(preview_df[col]).dt.date

            # Apply Indian Rupee formatting for currency tables
            if selected_table in ["branch_wise_monthly_target", "date_branch_wise_target"]:
                preview_df = apply_currency_format(preview_df)
                
            preview_df = preview_df.rename(columns=format_column)
            st.dataframe(preview_df, width="stretch")

            # -------------------------------
            # SESSION STATE INIT
            # -------------------------------
            if "upload_done" not in st.session_state:
                st.session_state.upload_done = False

            # -------------------------------
            # CONFIRM UPLOAD
            # -------------------------------
            if not st.session_state.upload_done:
                if st.button("🚀 Confirm Upload"):
                    logger.info(f"Initiating database insert for {len(df)} records into {selected_table}...")
                    success, msg = insert_dataframe(selected_table, df)

                    if success:
                        logger.info(f"Upload Complete for {selected_table}: {msg}")
                        log_audit_action(
                            action_type="UPLOAD",
                            target_table=selected_table,
                            record_count=len(df),
                            metadata={"file_name": uploaded_file.name}
                        )

                        # Dual upload enhancement for branch_wise_monthly_target
                        if selected_table == "branch_wise_monthly_target":
                            try:
                                logger.info("Generating dynamic daily targets for date_branch_wise_target...")
                                df_daily = generate_daily_targets_from_monthly(df)
                                if not df_daily.empty:
                                    logger.info(f"Inserting {len(df_daily)} daily records into date_branch_wise_target...")
                                    daily_success, daily_msg = insert_dataframe("date_branch_wise_target", df_daily)
                                    if daily_success:
                                        log_audit_action(
                                            action_type="UPLOAD",
                                            target_table="date_branch_wise_target",
                                            record_count=len(df_daily),
                                            metadata={"source": "branch_wise_monthly_target_upload", "file_name": uploaded_file.name}
                                        )
                                        msg = f"{msg} | date_branch_wise_target: {len(df_daily)} daily records updated successfully"
                                        logger.info(f"Dual Upload Complete: {msg}")
                                    else:
                                        logger.error(f"date_branch_wise_target Insert Failed: {daily_msg}")
                                        msg = f"{msg} | Warning: date_branch_wise_target failed ({daily_msg})"
                            except Exception as ex:
                                logger.error(f"Error during daily target generation/upload: {ex}")
                                msg = f"{msg} | Warning: date_branch_wise_target generation failed ({ex})"

                        st.session_state.upload_done = True
                        st.session_state.upload_msg = msg
                        # Clear cache to show new data immediately
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        logger.error(f"Upload Failed: {msg}")
                        log_audit_action(action_type="ERROR", target_table=selected_table, error_message=f"DB Insert Failed: {msg}")
                        st.error(f"❌ {msg}")

            else:
                st.success(f"✅ {st.session_state.upload_msg}")

        except Exception as e:
            st.error(f"❌ Error: {e}")