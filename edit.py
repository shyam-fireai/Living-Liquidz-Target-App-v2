import logging
from datetime import date, datetime

import pandas as pd
import streamlit as st

from db import (
    apply_currency_format,
    clean_dataframe_for_db,
    execute_query,
    fetch_data,
    format_column,
    get_all_filter_values,
    insert_dataframe,
    log_audit_action,
    log_execution_time,
)
from style_utils import inject_minimalist_theme, render_header
from upload import generate_daily_targets_from_monthly

logger = logging.getLogger(__name__)


@log_execution_time
def edit_screen(selected_table):
    # -------------------------------
    # SESSION STATE INIT
    # -------------------------------
    if "edit_applied_filters" not in st.session_state:
        st.session_state.edit_applied_filters = {}

    if "edit_temp_filters" not in st.session_state:
        st.session_state.edit_temp_filters = {}

    if "edit_last_table" not in st.session_state:
        st.session_state.edit_last_table = None

    if st.session_state.edit_last_table != selected_table:
        st.session_state.edit_temp_filters = {}
        st.session_state.edit_applied_filters = {}
        st.session_state.edit_confirmed_df = None
        st.session_state.edit_original_df = None
        st.session_state.edit_last_table = selected_table
        # Initialize a unique key for the data_editor to force a fresh start on save
        if "editor_version" not in st.session_state:
            st.session_state.editor_version = 0

    if "edit_confirmed_df" not in st.session_state:
        st.session_state.edit_confirmed_df = None

    if "edit_original_df" not in st.session_state:
        st.session_state.edit_original_df = None

    if "edit_do_confirm" not in st.session_state:
        st.session_state.edit_do_confirm = False

    # -------------------------------
    # UI THEME & HEADER
    # -------------------------------
    inject_minimalist_theme()
    display_name = selected_table.replace("_", " ").title()
    col_edit, col_upload = render_header(title=f"Editing: {display_name}", hide_upload=True)

    with col_edit:
        # Realign the Back button to the header area
        if st.button("⬅️ Back", width="stretch"):
            st.session_state.page = "dashboard"
            st.rerun()

    # -------------------------------
    # DYNAMIC CASCADING FILTERS
    # -------------------------------
    # At the start of rerun, pull latest widget choices into temp_filters
    TABLE_FILTERS = {
        "branch_wise_monthly_target": ["month", "branch_name", "series_group"],
        "date_branch_wise_target": ["date", "branch_name", "series_group"],
        "brand_wise_monthly_target": ["month", "branch_name", "series_group", "item_code", "item_name", "pack_name"],
    }
    filter_cols = TABLE_FILTERS.get(selected_table, [])

    for col in filter_cols:
        w_key = f"ed_filter_{col}_{selected_table}"
        if w_key in st.session_state:
            new_val = st.session_state[w_key]
            # If any filter changes, we must reset the baseline and any pending confirmations
            if st.session_state.edit_temp_filters.get(col) != new_val:
                logger.info(f"Edit Filter Change detected: {col} -> {new_val}")
                st.session_state.edit_temp_filters[col] = new_val
                st.session_state.edit_original_df = None
                st.session_state.edit_confirmed_df = None

    # ✅ DYNAMIC CASCADING FILTERS
    all_filters = get_all_filter_values(selected_table, st.session_state.edit_temp_filters)

    for col in filter_cols:
        try:
            values = all_filters.get(col, [])

            if col == "date":
                # Compact Date Range Picker
                prev_dates = st.session_state.edit_temp_filters.get(col, [])
                d1_val = prev_dates[0] if isinstance(prev_dates, (list, tuple)) and len(prev_dates) >= 1 else None
                d2_val = prev_dates[1] if isinstance(prev_dates, (list, tuple)) and len(prev_dates) >= 2 else None

                st.sidebar.caption("📅 Select Date Range")
                selected = st.sidebar.date_input(
                    "Range",
                    value=(d1_val, d2_val) if d1_val and d2_val else (d1_val,) if d1_val else [],
                    key=f"ed_filter_{col}_{selected_table}",
                    label_visibility="collapsed",
                )
            else:
                selected = st.sidebar.multiselect(
                    col.replace("_", " ").title(),
                    values,
                    key=f"ed_filter_{col}_{selected_table}",
                    default=[v for v in st.session_state.edit_temp_filters.get(col, []) if v in values],
                )

            if selected:
                st.session_state.edit_temp_filters[col] = selected
            else:
                st.session_state.edit_temp_filters.pop(col, None)

        except Exception as e:
            st.warning(f"{col} error: {e}")

    # -------------------------------
    # RESET
    # -------------------------------
    if st.sidebar.button("🔄 Reset Filters", width="stretch"):
        st.session_state.edit_temp_filters = {}
        st.session_state.edit_applied_filters = {}
        st.session_state.edit_confirmed_df = None
        st.rerun()
    # LOAD DATA (LIVE)
    # -------------------------------
    # The editor now updates instantly based on temp_filters
    with st.spinner("Loading records..."):
        if not st.session_state.edit_temp_filters:
            logger.info(f"Loading top 200 records for editing in {selected_table}")
            df = fetch_data(selected_table, limit=200)
        else:
            logger.info(
                f"Loading filtered records for editing in {selected_table}: {st.session_state.edit_temp_filters}"
            )
            df = fetch_data(selected_table, filters=st.session_state.edit_temp_filters, limit=200)

    # Update applied_filters for Save logic
    applied_filters = st.session_state.edit_temp_filters

    if df.empty:
        st.warning("No data available")
        return

    # -------------------------------
    # REMOVE SYSTEM COLS
    # -------------------------------
    display_df = df.drop(columns=["is_active", "version", "updated_at"], errors="ignore")

    # Apply Indian formatting for display in the editor
    display_df = apply_currency_format(display_df)

    # Store original snapshot ONLY IF it hasn't been set yet
    if st.session_state.edit_original_df is None:
        st.session_state.edit_original_df = display_df.copy()

    original_df = st.session_state.edit_original_df

    # -------------------------------
    # DATA EDITOR (With Pretty Headers)
    # -------------------------------
    if not st.session_state.edit_temp_filters:
        st.info(
            "ℹ️ **Showing first 200 records.** Use filters to narrow down. | 💡 **To save data**, first edit any cell in the table below."
        )
    else:
        st.info("💡 **To save data**, first edit any cell in the table below.")
    # We use column_config to show nice labels while keeping technical names for the code
    editor_config = {col: st.column_config.Column(label=format_column(col)) for col in display_df.columns}

    # Use a dynamic key to force the editor to reset whenever we save or change tables
    editor_key = f"editor_{selected_table}_{st.session_state.editor_version}"

    edited_df = st.data_editor(
        display_df, width="stretch", num_rows="fixed", column_config=editor_config, hide_index=False, key=editor_key
    )

    # -------------------------------
    # DEBUG LOGGING (Terminal)
    # -------------------------------
    # These help identify why 'Confirm' might not be appearing
    print(f"\n[DEBUG] --- Edit Detection Cycle for {selected_table} ---")
    # -------------------------------
    # SMART CHANGE DETECTION
    # -------------------------------
    # We clean both DFs to absolute values to ignore formatting differences
    base_orig = clean_dataframe_for_db(original_df.copy())
    base_edit = clean_dataframe_for_db(edited_df.copy())

    # Check for value differences ignoring types/formatting
    # Check for value differences ignoring types/formatting/index-labels
    has_changed_values = False
    if base_edit.shape == base_orig.shape:
        # We compare values directly to ignore index label mismatches
        has_changed_values = not (base_edit.astype(str).values == base_orig.astype(str).values).all()

        if has_changed_values:
            # DETECTIVE MODE: Find exactly which cell is triggering the button
            # We use a clean re-indexed comparison for the diff tracker
            idx_edit = base_edit.reset_index(drop=True).astype(str)
            idx_orig = base_orig.reset_index(drop=True).astype(str)
            diff = (idx_edit != idx_orig).stack()
            changed_cells = diff[diff]
            if not changed_cells.empty:
                info_msg = f"Change detected at {changed_cells.index[0]}: '{idx_orig.loc[changed_cells.index[0]]}' -> '{idx_edit.loc[changed_cells.index[0]]}'"
                logger.info(info_msg)
                print(f"[DEBUG] DETECTED DIFFERENCE: {info_msg}")
    else:
        # Row counts differ (e.g. if rows were deleted, though we disabled adding)
        logger.info(f"Record count changed: {len(base_edit)} vs {len(base_orig)}")
        has_changed_values = True

    has_changed = has_changed_values or (len(edited_df) != len(original_df))

    # Logic to handle the 'After Save' state to prevent button flickers
    if "just_saved" not in st.session_state:
        st.session_state.just_saved = False

    # IMPORTANT: We only show buttons if has_changed is True AND we haven't JUST saved.
    # HOWEVER, we reset just_saved if a NEW change is detected.
    if has_changed and st.session_state.just_saved:
        # Check if it's a REAL new change (handling both numbers and text)
        # We normalize everything cell-by-cell to stripped uppercase strings
        norm_edit = base_edit.map(lambda x: str(x).strip().upper())
        norm_orig = base_orig.map(lambda x: str(x).strip().upper())

        real_new_change = not norm_edit.equals(norm_orig)

        if real_new_change:
            st.session_state.just_saved = False
            # The code below will now execute for the new change

    if has_changed and not st.session_state.just_saved:
        # LIVE PREVIEW MODE: Show changes summary automatically if table has changed
        st.warning("⚠️ Pending Changes Detected. Review summary below to Save.")
    elif st.session_state.just_saved:
        st.success("✅ Your changes were saved successfully. Feel free to continue editing.")
    # -------------------------------
    # LIVE PREVIEW
    # -------------------------------
    if has_changed and not st.session_state.just_saved:
        # Robust diff detection using string versions
        conf_df = edited_df.copy()

        # Enforce exact label parity to prevent Pandas ValueError on strict comparisons
        # Streamlit sometimes returns slightly modified internal index types (Int64 vs RangeIndex)
        if conf_df.shape == original_df.shape:
            conf_df.index = original_df.index
            conf_df.columns = original_df.columns

        diff_mask = conf_df.astype(str) != original_df.astype(str)

        # Filter rows that have at least one change
        changed_mask = diff_mask.any(axis=1)
        changed_rows = conf_df[changed_mask]
        original_rows = original_df.loc[changed_rows.index] if not changed_rows.empty else pd.DataFrame()

        st.divider()
        st.subheader("🔍 Changes Summary")

        st.markdown("### 🟥 Before")
        st.dataframe(original_rows.rename(columns=format_column), width="stretch")

        st.markdown("### 🟩 After")
        st.dataframe(changed_rows.rename(columns=format_column), width="stretch")

        st.info("👉 Review your changes above and click Final Save below.")

    # -------------------------------
    # FINAL SAVE
    # -------------------------------
    if has_changed and not st.session_state.just_saved:
        if st.button("💾 Final Save", width="stretch", type="primary"):
            logger.info(f"Final Save clicked for {selected_table}")

            try:
                MAX_ROWS = 200

                with st.spinner("Loading data..."):
                    if applied_filters:
                        df = fetch_data(selected_table, filters=applied_filters, limit=MAX_ROWS)
                    else:
                        df = fetch_data(selected_table, limit=MAX_ROWS)
                        st.info(f"Showing first {MAX_ROWS} rows. Apply filters to refine.")

                # -------------------------------
                # IDENTIFY MODIFIED ROWS ONLY
                # -------------------------------
                # Use the live edited_df directly from the data_editor
                edited_df_full = edited_df.copy()

                # Prevent Pandas ValueError by strictly aligning the dynamically returned frame
                if edited_df_full.shape == original_df.shape:
                    edited_df_full.index = original_df.index
                    edited_df_full.columns = original_df.columns

                diff_mask = (edited_df_full.astype(str) != original_df.astype(str)).any(axis=1)
                rows_to_update = edited_df_full[diff_mask]

                if rows_to_update.empty:
                    st.info("No modifications detected.")
                    return

                # -------------------------------
                # SAVE MODIFIED ROWS (Native Versioning)
                # -------------------------------
                # Because the table engine is ReplacingMergeTree(version),
                # simply inserting a new row with a higher version timestamp
                # will automatically supersede the old record.

                # -------------------------------
                # SAVE CHANGES (Handling Identity Changes)
                # -------------------------------
                # If the user changed a "Key" column (Month, Branch, Series),
                # we must deactivate the old identity manually.

                # TABLE_FILTERS is defined at the top of the function
                key_cols_map = {
                    "branch_wise_monthly_target": ["month", "branch_name", "series_group"],
                    "date_branch_wise_target": ["date", "branch_name", "series_group"],
                    "brand_wise_monthly_target": [
                        "month",
                        "branch_name",
                        "series_group",
                        "item_code",
                        "item_name",
                        "pack_name",
                    ],
                }
                curr_keys = key_cols_map.get(selected_table, [])
                keys_to_kill = []

                for idx, row in rows_to_update.iterrows():
                    orig_row = original_df.loc[idx]

                    # Check if any key column was changed
                    key_changed = False
                    for c in curr_keys:
                        if str(row[c]).strip().upper() != str(orig_row[c]).strip().upper():
                            key_changed = True
                            break

                    if key_changed:
                        # Build a tuple of the OLD keys to deactivate
                        val_parts = []
                        for c in curr_keys:
                            v = orig_row[c]
                            if isinstance(v, (str, pd.Timestamp, datetime, date)):
                                # Ensure date objects are formatted for SQL
                                if hasattr(v, "strftime"):
                                    v = v.strftime("%Y-%m-%d")
                                v_str = str(v).replace("'", "''")
                                val_parts.append(f"'{v_str}'")
                            else:
                                val_parts.append(str(v))
                        keys_to_kill.append(f"({', '.join(val_parts)})")

                if keys_to_kill:
                    # Execute deactivation in batches if needed, but here simple for short lists
                    kill_condition = f"({', '.join(curr_keys)}) IN ({', '.join(keys_to_kill)})"
                    kill_query = f"ALTER TABLE {selected_table} UPDATE is_active = 0 WHERE {kill_condition}"
                    logger.warning(f"Identity Change Detected! Deactivating old keys: {kill_condition}")
                    execute_query(kill_query)

                # Now insert the new records (they will have new keys or same keys with higher version)
                logger.info(f"Committing {len(rows_to_update)} modified records...")
                success, msg = insert_dataframe(selected_table, rows_to_update)

                if success:
                    # AUDIT LOG: Capture the explicit before/after states
                    before_dict = original_rows.to_dict(orient="records")
                    after_dict = rows_to_update.to_dict(orient="records")
                    log_audit_action(
                        action_type="EDIT",
                        target_table=selected_table,
                        record_count=len(rows_to_update),
                        before_state=before_dict,
                        after_state=after_dict,
                    )

                    # Dual synchronization for branch_wise_monthly_target -> date_branch_wise_target
                    if selected_table == "branch_wise_monthly_target":
                        try:
                            logger.info(
                                f"Synchronizing {len(rows_to_update)} edited monthly target row(s) to date_branch_wise_target..."
                            )
                            # Clean numeric columns before generating daily targets
                            clean_monthly_rows = clean_dataframe_for_db(rows_to_update.copy())
                            clean_monthly_rows["month"] = pd.to_datetime(clean_monthly_rows["month"])

                            # Deactivate old daily targets if key columns changed
                            if keys_to_kill:
                                for idx in rows_to_update.index:
                                    orig_row = original_df.loc[idx]
                                    orig_m = pd.to_datetime(orig_row["month"])
                                    orig_b = str(orig_row["branch_name"]).replace("'", "''")
                                    orig_s = str(orig_row["series_group"]).replace("'", "''")
                                    start_d = orig_m.strftime("%Y-%m-01")
                                    days_cnt = pd.Period(start_d).days_in_month
                                    end_d = orig_m.strftime(f"%Y-%m-{days_cnt:02d}")
                                    kill_daily = f"ALTER TABLE date_branch_wise_target UPDATE is_active = 0 WHERE branch_name = '{orig_b}' AND series_group = '{orig_s}' AND date >= '{start_d}' AND date <= '{end_d}'"
                                    logger.info(f"Deactivating old daily targets for key change: {kill_daily}")
                                    execute_query(kill_daily)

                            df_daily_sync = generate_daily_targets_from_monthly(clean_monthly_rows)
                            if not df_daily_sync.empty:
                                daily_success, daily_msg = insert_dataframe("date_branch_wise_target", df_daily_sync)
                                if daily_success:
                                    log_audit_action(
                                        action_type="EDIT",
                                        target_table="date_branch_wise_target",
                                        record_count=len(df_daily_sync),
                                        metadata={"source": "branch_wise_monthly_target_edit_sync"},
                                    )
                                    msg = f"{msg} | date_branch_wise_target: {len(df_daily_sync)} daily records updated successfully"
                                    logger.info(f"Daily targets synced: {msg}")
                                else:
                                    logger.error(f"date_branch_wise_target sync failed: {daily_msg}")
                                    msg = f"{msg} | Warning: date_branch_wise_target sync failed ({daily_msg})"
                        except Exception as ex_sync:
                            logger.error(f"Error synchronizing daily targets: {ex_sync}")
                            msg = f"{msg} | Warning: date_branch_wise_target sync failed ({ex_sync})"

                    st.success(f"✅ {msg}")

                    # TOTAL STATE WIPE: This ensures the UI resets to a clean slate
                    # We clear these BEFORE the rerun to ensure the next render pulls fresh
                    st.session_state.edit_confirmed_df = None
                    st.session_state.edit_original_df = None
                    st.session_state.edit_applied_filters = {}
                    st.session_state.edit_do_confirm = False

                    # Set flag to hide buttons and update table identity
                    st.session_state.just_saved = True
                    st.session_state.editor_version += 1

                    # Force streamlit to forget all old data
                    st.cache_data.clear()

                    # Give ClickHouse a full second to ensure FINAL projection is updated
                    import time

                    time.sleep(1.0)

                    # Stay on page: No page redirect needed, just refresh the table
                    st.rerun()

                else:
                    log_audit_action("ERROR", target_table=selected_table, error_message=f"DB Update Failed: {msg}")
                    st.error(msg)

            except Exception as e:
                log_audit_action("ERROR", target_table=selected_table, error_message=f"Edit UI Crash: {str(e)}")
                st.error(f"❌ Error: {e}")

    # Enforce a bottom margin so the UI never hugs the absolute edge of the screen
    st.write("<br><br><br>", unsafe_allow_html=True)
