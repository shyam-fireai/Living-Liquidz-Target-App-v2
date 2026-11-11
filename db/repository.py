"""All reads/writes of the target tables. Every value goes through ClickHouse query parameters;
table/column identifiers are only ever taken from config.TABLES (whitelist)."""

from __future__ import annotations

import logging
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from config import BRANCH_MONTHLY, DATE_BRANCH, DEFAULT_ROW_LIMIT, SYSTEM_COLUMNS, get_table
from db.cache import _versions, data_version, invalidate  # noqa: F401 - re-exported
from db.client import get_client
from services.validation import NULL_TOKENS, clean_dataframe_for_db

logger = logging.getLogger(__name__)

# Wait for ALTER ... UPDATE mutations to finish on this replica before returning,
# so the next read (FINAL) already sees the deactivation.
_MUTATION_SETTINGS = {"mutations_sync": 1}


# -------------------------------
# WHERE-clause builder
# -------------------------------
def _param_type(table: str, col: str) -> str:
    return "Date" if col == get_table(table).date_col else "String"


def _to_param(value, ch_type: str):
    if ch_type == "Date":
        return pd.to_datetime(value).date()
    return str(value)


def build_where(table: str, filters: dict | None) -> tuple[str, dict]:
    """Return (' AND '-joined conditions, parameters) for the given UI filters.

    - Date column ("date"): a 1- or 2-tuple from a date-range picker -> exact day / BETWEEN.
    - Every other column (incl. "month"): a list of selected values -> IN.
    """
    cfg = get_table(table)
    conditions = ["is_active = 1"]
    params: dict = {}

    for i, (col, values) in enumerate((filters or {}).items()):
        if not values:
            continue
        if col not in cfg.filter_cols:
            raise ValueError(f"Column {col!r} is not filterable on {table}")
        ch_type = _param_type(table, col)

        if col == "date":
            values = list(values)
            params[f"f{i}_from"] = _to_param(values[0], "Date")
            params[f"f{i}_to"] = _to_param(values[-1], "Date")
            conditions.append(f"{col} BETWEEN {{f{i}_from:Date}} AND {{f{i}_to:Date}}")
        else:
            params[f"f{i}"] = [_to_param(v, ch_type) for v in values]
            conditions.append(f"{col} IN {{f{i}:Array({ch_type})}}")

    return " AND ".join(conditions), params


# -------------------------------
# READS
# -------------------------------
def _order_by(table: str) -> str:
    """Deterministic order (newest period first) so "the first N rows" is always the same set."""
    cfg = get_table(table)
    return ", ".join([f"{cfg.date_col} DESC", *[c for c in cfg.key_cols if c != cfg.date_col]])


def fetch_data(
    table: str, filters: dict | None = None, limit: int = DEFAULT_ROW_LIMIT, offset: int = 0
) -> pd.DataFrame:
    """One page of rows for display (paging is done by ClickHouse). Raises on database errors."""
    get_table(table)
    return _fetch_data(table, filters, int(limit), int(offset), data_version(table))


@st.cache_data(ttl=60, max_entries=500, show_spinner=False)
def _fetch_data(table: str, filters: dict | None, limit: int, offset: int, version: int) -> pd.DataFrame:
    where, params = build_where(table, filters)
    params.update(limit=limit, offset=offset)
    query = (
        f"SELECT * FROM {table} FINAL WHERE {where} ORDER BY {_order_by(table)} "
        "LIMIT {limit:UInt32} OFFSET {offset:UInt32} SETTINGS max_execution_time=60"
    )
    result = get_client().query(query, parameters=params)
    df = pd.DataFrame(result.result_rows, columns=result.column_names)
    logger.info("Fetched %d rows from %s (offset %d)", len(df), table, offset)
    return df


MAX_EXPORT_ROWS = 200_000


def summarize(table: str, filters: dict | None = None) -> dict:
    """Totals over *all* rows matching the filters (not just the rows on screen)."""
    get_table(table)
    return _summarize(table, filters, data_version(table))


@st.cache_data(ttl=60, max_entries=500, show_spinner=False)
def _summarize(table: str, filters: dict | None, version: int) -> dict:
    cfg = get_table(table)
    where, params = build_where(table, filters)
    sums = ", ".join(f"sum({c}) AS {c}" for c in cfg.value_cols)
    query = f"SELECT count() AS rows, uniqExact(branch_name) AS branches, {sums} FROM {table} FINAL WHERE {where}"
    result = get_client().query(query, parameters=params)
    row = dict(zip(result.column_names, result.result_rows[0], strict=True))
    return {k: (float(v) if k in cfg.value_cols else int(v)) for k, v in row.items()}


def fetch_for_export(table: str, filters: dict | None = None) -> pd.DataFrame:
    """All matching rows (up to MAX_EXPORT_ROWS), uncached, raising on failure."""
    cfg = get_table(table)
    where, params = build_where(table, filters)
    params["limit"] = MAX_EXPORT_ROWS
    query = (
        f"SELECT {', '.join(cfg.columns)} FROM {table} FINAL WHERE {where} "
        f"ORDER BY {_order_by(table)} LIMIT {{limit:UInt32}}"
    )
    result = get_client().query(query, parameters=params)
    return pd.DataFrame(result.result_rows, columns=result.column_names)


def fetch_existing(table: str, rows: pd.DataFrame) -> pd.DataFrame:
    """Active stored rows that could match `rows` (same dates and branches). Uncached and raises on
    failure, because an upload preview must never claim "all new" just because the read failed."""
    cfg = get_table(table)
    filters = {
        cfg.date_col: sorted({pd.Timestamp(d).date() for d in rows[cfg.date_col].dropna()}),
        "branch_name": sorted(set(rows["branch_name"].dropna().astype(str))),
    }
    if not filters[cfg.date_col] or not filters["branch_name"]:
        return pd.DataFrame(columns=list(cfg.columns))
    params = {"d": filters[cfg.date_col], "b": filters["branch_name"]}
    query = (
        f"SELECT {', '.join(cfg.columns)} FROM {table} FINAL "
        f"WHERE is_active = 1 AND {cfg.date_col} IN {{d:Array(Date)}} AND branch_name IN {{b:Array(String)}}"
    )
    result = get_client().query(query, parameters=params)
    return pd.DataFrame(result.result_rows, columns=result.column_names)


def known_values(table: str, cols: tuple[str, ...] = ("branch_name", "series_group")) -> dict[str, set[str]]:
    """Values already present (in this table or Branch Wise Monthly Target), to flag likely typos."""
    known: dict[str, set[str]] = {c: set() for c in cols}
    for source in {table, BRANCH_MONTHLY}:
        index = get_filter_index(source)
        for col in cols:
            if col in index.columns:
                known[col] |= {str(v).strip().upper() for v in index[col].dropna()}
    return {c: v for c, v in known.items() if v}


def get_filter_index(table: str) -> pd.DataFrame:
    """Distinct combinations of all filter columns, for fast in-memory cascading filters."""
    get_table(table)
    return _filter_index(table, data_version(table))


@st.cache_data(ttl=300, max_entries=50, show_spinner=False)
def _filter_index(table: str, version: int) -> pd.DataFrame:
    cols = get_table(table).filter_cols
    query = f"SELECT DISTINCT {', '.join(cols)} FROM {table} FINAL WHERE is_active = 1"
    try:
        result = get_client().query(query)
        return pd.DataFrame(result.result_rows, columns=result.column_names)
    except Exception:
        logger.exception("Error fetching filter index for %s", table)
        return pd.DataFrame()


def get_all_filter_values(table: str, current_selections: dict | None = None) -> dict:
    """Options for every filter, each constrained by the selections made in the *other* filters."""
    index_df = get_filter_index(table)
    if index_df.empty:
        return {}

    result = {}
    for target_col in index_df.columns:
        mask = pd.Series(True, index=index_df.index)
        for col, vals in (current_selections or {}).items():
            if col == target_col or not vals or col not in index_df.columns:
                continue
            if col == "date":
                series_dt = pd.to_datetime(index_df[col]).dt.tz_localize(None)
                vals = list(vals)
                start = pd.to_datetime(vals[0]).tz_localize(None)
                end = pd.to_datetime(vals[-1]).tz_localize(None)
                mask &= (series_dt >= start) & (series_dt <= end)
            else:
                mask &= index_df[col].astype(str).isin([str(v) for v in vals])

        unique_vals = index_df.loc[mask, target_col].unique().tolist()
        result[target_col] = sorted(v for v in unique_vals if v is not None)
    return result


# -------------------------------
# WRITES
# -------------------------------
def _coerce_to_schema(df: pd.DataFrame, schema: dict[str, str]) -> pd.DataFrame:
    for col, ch_type in schema.items():
        if col in SYSTEM_COLUMNS or col not in df.columns:
            continue
        if "String" in ch_type:
            df[col] = df[col].fillna("").astype(str).str.strip()
            df[col] = df[col].replace(NULL_TOKENS + [t.lower() for t in NULL_TOKENS], "")
        elif any(t in ch_type for t in ("Decimal", "Float", "Int")):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)
        elif "Date" in ch_type:
            df[col] = pd.to_datetime(df[col]).dt.date
    return df


def insert_dataframe(table: str, df: pd.DataFrame) -> tuple[bool, str]:
    """Insert rows as a new version (ReplacingMergeTree supersedes older versions of the same key)."""
    get_table(table)
    try:
        client = get_client()
        schema = {row[0]: row[1] for row in client.query(f"DESCRIBE TABLE {table}").result_rows}

        df = _coerce_to_schema(clean_dataframe_for_db(df), schema)
        df["version"] = int(time.time() + 1)
        df["updated_at"] = datetime.now()
        df["is_active"] = 1
        df = df[[c for c in schema if c in df.columns]]

        client.insert_df(table, df)
        invalidate(table)
        logger.info("Inserted %d rows into %s", len(df), table)
        return True, f"{len(df)} records updated successfully"
    except Exception as e:
        logger.exception("Insert into %s failed", table)
        return False, str(e)


def deactivate_keys(table: str, key_rows: list[dict]) -> None:
    """Set is_active = 0 for rows whose key columns match any of `key_rows` (one dict per row)."""
    if not key_rows:
        return
    cfg = get_table(table)
    params: dict = {}
    clauses = []
    for i, key in enumerate(key_rows):
        parts = []
        for col in cfg.key_cols:
            ch_type = _param_type(table, col)
            params[f"k{i}_{col}"] = _to_param(key[col], ch_type)
            parts.append(f"{col} = {{k{i}_{col}:{ch_type}}}")
        clauses.append("(" + " AND ".join(parts) + ")")

    query = f"ALTER TABLE {table} UPDATE is_active = 0 WHERE {' OR '.join(clauses)}"
    logger.info("Deactivating %d old key(s) in %s", len(key_rows), table)
    get_client().command(query, parameters=params, settings=_MUTATION_SETTINGS)
    invalidate(table)


def deactivate_daily_for_months(month_keys: list[dict]) -> None:
    """Deactivate every daily row of the given (month, branch_name, series_group) combinations."""
    if not month_keys:
        return
    params: dict = {}
    clauses = []
    for i, key in enumerate(month_keys):
        month_start = pd.to_datetime(key["month"]).to_period("M")
        params[f"b{i}"] = str(key["branch_name"])
        params[f"s{i}"] = str(key["series_group"])
        params[f"d{i}_from"] = month_start.start_time.date()
        params[f"d{i}_to"] = month_start.end_time.date()
        clauses.append(
            f"(branch_name = {{b{i}:String}} AND series_group = {{s{i}:String}}"
            f" AND date BETWEEN {{d{i}_from:Date}} AND {{d{i}_to:Date}})"
        )
    query = f"ALTER TABLE {DATE_BRANCH} UPDATE is_active = 0 WHERE {' OR '.join(clauses)}"
    logger.info("Deactivating daily targets for %d month key(s)", len(month_keys))
    get_client().command(query, parameters=params, settings=_MUTATION_SETTINGS)
    invalidate(DATE_BRANCH)
