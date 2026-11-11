import functools
import json
import logging
import time
from datetime import datetime

import clickhouse_connect
import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)


# -------------------------------
# LOGGING DECORATOR
# -------------------------------
def log_execution_time(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        duration = end_time - start_time
        print(f"[LOG] {func.__name__} executed in {duration:.4f} seconds")
        return result

    return wrapper


# -------------------------------
# SQL VALUE FORMATTER
# -------------------------------
def format_sql_values(values):
    if not values:
        return ""

    formatted = []
    for v in values:
        if isinstance(v, (int, float)):
            formatted.append(str(v))
        else:
            # Wrap strings and dates in quotes
            formatted.append(f"'{v}'")

    return ", ".join(formatted)


# -------------------------------
# TABLE SCHEMAS
# -------------------------------
TABLE_SCHEMAS = {
    "branch_wise_monthly_target": [
        "month",
        "branch_name",
        "series_group",
        "target_value1",
        "incentive_value1",
        "target_value2",
        "incentive_value2",
        "target_value3",
        "incentive_value3",
        "target_value4",
        "incentive_value4",
        "target_value5",
        "incentive_value5",
    ],
    "date_branch_wise_target": [
        "date",
        "branch_name",
        "series_group",
        "target_value1",
        "incentive_value1",
        "target_value2",
        "incentive_value2",
        "target_value3",
        "incentive_value3",
        "target_value4",
        "incentive_value4",
        "target_value5",
        "incentive_value5",
    ],
    "brand_wise_monthly_target": [
        "month",
        "branch_name",
        "series_group",
        "item_code",
        "item_name",
        "pack_name",
        "target_qty1",
        "incentive_value1",
        "target_qty2",
        "incentive_value2",
        "target_qty3",
        "incentive_value3",
        "target_qty4",
        "incentive_value4",
        "target_qty5",
        "incentive_value5",
    ],
}


# -------------------------------
# CONNECT CLIENT
# -------------------------------
@log_execution_time
@st.cache_resource
def get_client():
    logger.info("Initializing ClickHouse client...")
    try:
        with open("secrets.json") as f:
            creds = json.load(f)
        conf = creds["data_clickhouse"]
        client = clickhouse_connect.get_client(
            host=conf["host"],
            port=conf["port"],
            username=conf["username"],
            password=conf["password"],
            database=conf["database"],
            # Local Docker: "secure": false in secrets.json; live server: "secure": true
            secure=bool(conf.get("secure", False)),
            connect_timeout=30,
            send_receive_timeout=60,
        )
        logger.info(f"ClickHouse client connected successfully to {conf['host']}")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize ClickHouse client: {e}")
        raise e


# -------------------------------
# FETCH DATA
# -------------------------------
@log_execution_time
@st.cache_data(ttl=60, show_spinner=False)
def fetch_data(table, filters=None, limit=200):
    client = get_client()

    query = f"SELECT * FROM {table} FINAL"
    conditions = ["is_active = 1"]

    if filters:
        for col, values in filters.items():
            if values:
                # Check if this is a date range tuple (start, end)
                if isinstance(values, (list, tuple)) and len(values) == 2 and col in ["date", "month"]:
                    conditions.append(f"{col} BETWEEN '{values[0]}' AND '{values[1]}'")
                else:
                    values_str = format_sql_values(values)
                    conditions.append(f"{col} IN ({values_str})")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += f" LIMIT {limit}"
    query += " SETTINGS max_execution_time=60"

    try:
        logger.info(f"Fetching data from table: {table} (Limit: {limit})")
        result = client.query(query)
        df_result = pd.DataFrame(result.result_rows, columns=result.column_names)
        logger.info(f"Successfully fetched {len(df_result)} rows from {table}")
        return df_result
    except Exception as e:
        logger.error(f"Error fetching data from {table}: {e}")
        return pd.DataFrame()


# -------------------------------
# FILTER VALUES (CACHED)
# -------------------------------
@log_execution_time
@st.cache_data(ttl=300, show_spinner=False)
def get_filter_index(table):
    """Fetches a unique combination of all filter columns to allow fast cascading filtering in memory."""
    client = get_client()

    if table == "brand_wise_monthly_target":
        cols = ["month", "branch_name", "series_group", "item_code", "item_name", "pack_name"]
    elif table == "date_branch_wise_target":
        cols = ["date", "branch_name", "series_group"]
    else:
        cols = ["month", "branch_name", "series_group"]

    query = f"""
        SELECT DISTINCT {", ".join(cols)}
        FROM {table} FINAL
        WHERE is_active = 1
    """
    try:
        logger.info(f"Fetching filter index for table: {table} (Columns: {cols})")
        result = client.query(query)
        df_index = pd.DataFrame(result.result_rows, columns=result.column_names)
        logger.info(f"Filter index loaded: {len(df_index)} unique combinations for {table}")
        return df_index
    except Exception as e:
        logger.error(f"Error fetching filter index for {table}: {e}")
        return pd.DataFrame()


def get_all_filter_values(table, current_selections=None):
    """Returns available options for every filter, constrained by the selections in other filters."""
    index_df = get_filter_index(table)
    if index_df.empty:
        return {}

    cols = index_df.columns.tolist()
    result_dict = {}

    logger.info(f"Calculating cascading filter values for {table}...")
    for target_col in cols:
        # Build mask for ALL OTHER columns
        mask = pd.Series(True, index=index_df.index)

        if current_selections:
            for col, vals in current_selections.items():
                if col != target_col and vals:
                    # Handle Date Range
                    if isinstance(vals, (list, tuple)) and col in ["date", "month"]:
                        # Convert to same timezone-naive datetime for robust comparison
                        series_dt = pd.to_datetime(index_df[col]).dt.tz_localize(None)
                        if len(vals) == 2:
                            start = pd.to_datetime(vals[0]).tz_localize(None)
                            end = pd.to_datetime(vals[1]).tz_localize(None)
                            mask &= (series_dt >= start) & (series_dt <= end)
                        elif len(vals) == 1:
                            # Partial range: match start date exactly for now
                            start = pd.to_datetime(vals[0]).tz_localize(None)
                            mask &= series_dt == start
                    # Handle Multiselect
                    elif isinstance(vals, (list, tuple)):
                        mask &= index_df[col].astype(str).isin([str(v) for v in vals])

        # Extract unique values from masked dataframe
        unique_vals = index_df.loc[mask, target_col].unique().tolist()
        result_dict[target_col] = sorted([v for v in unique_vals if v is not None])

    logger.info(f"Filters calculated successfully for {table}")
    return result_dict


def clean_dataframe_for_db(df):
    df = df.copy()
    # Identify columns that should be strings to avoid numpy numeric type issues
    string_cols = ["branch_name", "series_group", "item_code", "item_name", "pack_name", "series"]

    for col in df.columns:
        if col in string_cols:
            # Force to string, uppercase, and fill nulls with empty string
            df[col] = df[col].fillna("").astype(str).str.strip().str.upper()
            df[col] = df[col].replace(["NONE", "NAN", "<NA>", "NULL"], "")
        elif any(x in col.lower() for x in ["target", "incentive", "qty"]):
            # Ensure targets, incentives and quantities are numeric
            # Clean any ₹ or , symbols if they exist (allows us to save from formatted editor)
            df[col] = (
                df[col].astype(str).str.replace("₹", "", regex=False).str.replace(",", "", regex=False).str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)
        elif df[col].dtype == "object":
            # For other object types, fill with empty string
            df[col] = df[col].fillna("").astype(str).str.strip()
            df[col] = df[col].replace(["NONE", "NAN", "<NA>", "NULL"], "")
        else:
            # For integers and others
            df[col] = df[col].fillna(0)
    return df


# -------------------------------
# INSERT DATAFRAME
# -------------------------------
@log_execution_time
def insert_dataframe(table, df):
    logger.info(f"Starting dataframe insertion/update for table: {table} ({len(df)} records)")
    try:
        client = get_client()

        # DYNAMIC COLUMN DETECTION & TYPE ENFORCEMENT
        desc = client.query(f"DESCRIBE {table}").result_rows
        db_cols_meta = {row[0]: row[1] for row in desc}

        # Apply robust cleaning
        df = clean_dataframe_for_db(df)

        # Explicitly enforce types expected by ClickHouse to prevent serialization failures
        for col, ch_type in db_cols_meta.items():
            if col in ["version", "updated_at", "is_active"] or col not in df.columns:
                continue
            if "String" in ch_type:
                df[col] = df[col].fillna("").astype(str).str.strip()
                df[col] = df[col].replace(["NONE", "NAN", "<NA>", "NULL", "none", "nan", "null"], "")
            elif any(t in ch_type for t in ["Decimal", "Float", "Int"]):
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)
            elif "Date" in ch_type:
                df[col] = pd.to_datetime(df[col]).dt.date

        # Add system columns and ensure they exist
        df["version"] = int(time.time() + 1)
        df["updated_at"] = datetime.now()
        df["is_active"] = 1

        # Keep only columns that exist in BOTH the dataframe and the database
        final_cols = [c for c in db_cols_meta.keys() if c in df.columns]
        df = df[final_cols]

        logger.info(f"Inserting into {table} with columns: {final_cols}")
        client.insert_df(table, df)

        logger.info(f"Successfully inserted {len(df)} records into {table}")
        return True, f"{len(df)} records updated successfully"

    except Exception as e:
        logger.error(f"Failed to insert dataframe into {table}: {e}")
        return False, str(e)


# -------------------------------
# EXECUTE QUERY
# -------------------------------
def execute_query(query):
    client = get_client()
    client.command(query)


# -------------------------------
# UI FORMATTING HELPERS
# -------------------------------
def format_column(col):
    if col == "series_group":
        return "Series"
    return col.replace("_", " ").title()


def remove_zero_columns(df):
    # Columns that should ALWAYS be shown regardless of being zero
    protected_cols = ["month", "date", "branch_name", "series_group", "series", "item_code", "item_name", "pack_name"]

    # Identify non-protected columns
    other_cols = [c for c in df.columns if c not in protected_cols]
    if not other_cols:
        return df

    # Check which of these columns have at least one non-zero value
    num_df = df[other_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    non_zero_cols = set(num_df.columns[(num_df != 0).any()].tolist())

    # Build final column list
    cols_to_keep = [c for c in df.columns if c in protected_cols or c in non_zero_cols]

    return df[cols_to_keep]


def format_indian_number(x, show_rupee=True):
    try:
        if pd.isna(x) or x == "":
            return "0.00"

        # Clean any existing formatting first to avoid double formatting
        val = str(x).replace("₹", "").replace(",", "")
        x_float = float(val)

        sign = "-" if x_float < 0 else ""
        s = f"{abs(x_float):.2f}"
        parts = s.split(".")
        num = parts[0]
        dec = parts[1]

        if len(num) > 3:
            last3 = num[-3:]
            rest = num[:-3]
            rest = ",".join([rest[max(i - 2, 0) : i] for i in range(len(rest), 0, -2)][::-1])
            num = rest + "," + last3

        prefix = "₹" if show_rupee else ""
        return f"{prefix}{sign}{num}.{dec}"
    except Exception:
        return x


def apply_currency_format(df):
    df = df.copy()
    for col in df.columns:
        if "value" in col.lower():
            df[col] = df[col].apply(lambda x: format_indian_number(x, show_rupee=True))
        elif "qty" in col.lower():
            df[col] = df[col].apply(lambda x: format_indian_number(x, show_rupee=False))
    return df


# -------------------------------
# AUDIT LOGGING
# -------------------------------
def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    from datetime import date, datetime

    import pandas as pd

    if isinstance(obj, (datetime, date, pd.Timestamp)):
        return obj.isoformat()
    return str(obj)


def log_audit_action(
    action_type,
    target_table=None,
    record_count=0,
    before_state=None,
    after_state=None,
    error_message=None,
    metadata=None,
    user_email=None,
):
    logger.info(f"Recording Audit Action: {action_type} for {target_table or 'Global'}")
    try:
        client = get_client()

        # Assign persistent session ID
        if "audit_session_id" not in st.session_state:
            st.session_state.audit_session_id = "Session_" + str(int(time.time() * 1000))

        # Resolve user email: passed argument > session_state > cookies > fallback
        if not user_email:
            user_email = st.session_state.get("user_email")
        if not user_email:
            try:
                import urllib.parse

                raw_u = getattr(st.context, "cookies", {}).get("auth_user")
                if raw_u:
                    user_email = urllib.parse.unquote(raw_u)
            except Exception:
                pass
        if not user_email:
            user_email = "Anonymous"

        data = {
            "session_id": st.session_state.audit_session_id,
            "user_email": user_email,
            "action_type": action_type,
            "target_table": target_table or "",
            "record_count": int(record_count) if record_count else 0,
            "before_state": json.dumps(before_state, default=json_serial) if before_state else "",
            "after_state": json.dumps(after_state, default=json_serial) if after_state else "",
            "device_info": "",
            "ip_address": "",
            "error_message": error_message or "",
            "metadata": json.dumps(metadata, default=json_serial) if metadata else "",
        }

        query = """
            INSERT INTO target_system_audit_logs
            (session_id, user_email, action_type, target_table, record_count, before_state, after_state, device_info, ip_address, error_message, metadata)
            VALUES
            ({session_id:String}, {user_email:String}, {action_type:String}, {target_table:String}, {record_count:Int32}, {before_state:String}, {after_state:String}, {device_info:String}, {ip_address:String}, {error_message:String}, {metadata:String})
        """
        # clickhouse-connect parameterization syntax
        client.command(query, parameters=data)
        logger.info(f"Audit log entry created for {action_type}")

    except Exception as e:
        logger.error(f"AUDIT LOG FAILED: {str(e)}")
