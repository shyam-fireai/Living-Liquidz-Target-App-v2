"""Audit trail in target_system_audit_logs: writes (failures logged, never raised) and History reads."""

import json
import logging
import time
import urllib.parse
from datetime import date, datetime

import pandas as pd
import streamlit as st

from config import AUDIT_LOG
from db.cache import data_version, invalidate
from db.client import get_client

logger = logging.getLogger(__name__)

_INSERT = f"""
    INSERT INTO {AUDIT_LOG}
    (session_id, user_email, action_type, target_table, record_count,
     before_state, after_state, device_info, ip_address, error_message, metadata)
    VALUES
    ({{session_id:String}}, {{user_email:String}}, {{action_type:String}}, {{target_table:String}},
     {{record_count:Int32}}, {{before_state:String}}, {{after_state:String}}, {{device_info:String}},
     {{ip_address:String}}, {{error_message:String}}, {{metadata:String}})
"""


def _json_default(obj):
    if isinstance(obj, (datetime, date, pd.Timestamp)):
        return obj.isoformat()
    return str(obj)


def _dumps(value) -> str:
    return json.dumps(value, default=_json_default) if value else ""


def _current_user_email() -> str:
    email = st.session_state.get("user_email")
    if not email:
        raw = st.context.cookies.get("auth_user")
        email = urllib.parse.unquote(raw) if raw else None
    return email or "Anonymous"


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
    try:
        if "audit_session_id" not in st.session_state:
            st.session_state.audit_session_id = f"Session_{int(time.time() * 1000)}"

        params = {
            "session_id": st.session_state.audit_session_id,
            "user_email": user_email or _current_user_email(),
            "action_type": action_type,
            "target_table": target_table or "",
            "record_count": int(record_count or 0),
            "before_state": _dumps(before_state),
            "after_state": _dumps(after_state),
            "device_info": "",
            "ip_address": "",
            "error_message": error_message or "",
            "metadata": _dumps(metadata),
        }
        get_client().command(_INSERT, parameters=params)
        invalidate(AUDIT_LOG)
        logger.info("Audit: %s on %s (%s rows)", action_type, target_table or "-", params["record_count"])
    except Exception:
        logger.exception("Audit log write failed for %s", action_type)


# -------------------------------
# READS (History page)
# -------------------------------
HISTORY_LIMIT = 500

# Timestamps are DateTime (an instant); toUnixTimestamp/toDateTime(UInt32) keep them timezone-proof,
# whatever the server timezone is. The page converts to IST for display.
_HISTORY_COLS = (
    "toString(log_id) AS log_id, toUnixTimestamp(timestamp) AS ts, user_email, action_type, "
    "target_table, record_count, error_message, metadata"
)


def _history_where(start_ts: int, end_ts: int, actions, users, tables) -> tuple[str, dict]:
    conditions = ["timestamp BETWEEN toDateTime({start:UInt32}) AND toDateTime({end:UInt32})"]
    params: dict = {"start": int(start_ts), "end": int(end_ts)}
    for name, values in (("action_type", actions), ("user_email", users), ("target_table", tables)):
        if values:
            conditions.append(f"{name} IN {{{name}:Array(String)}}")
            params[name] = [str(v) for v in values]
    return " AND ".join(conditions), params


# Within the same second the user's own action is listed before its companion entry
# ("Daily targets regenerated", whose metadata has a "source").
_HISTORY_ORDER = """timestamp DESC, position(metadata, '"source"') > 0"""


def fetch_history(
    start_ts: int, end_ts: int, actions=(), users=(), tables=(), limit: int = HISTORY_LIMIT
) -> tuple[pd.DataFrame, int]:
    """(newest entries first, total matching). Raises on database errors."""
    return _fetch_history(
        int(start_ts), int(end_ts), tuple(actions), tuple(users), tuple(tables), int(limit), data_version(AUDIT_LOG)
    )


@st.cache_data(ttl=60, max_entries=100, show_spinner=False)
def _fetch_history(start_ts, end_ts, actions, users, tables, limit, version) -> tuple[pd.DataFrame, int]:
    where, params = _history_where(start_ts, end_ts, actions, users, tables)
    client = get_client()
    total = int(client.query(f"SELECT count() FROM {AUDIT_LOG} WHERE {where}", parameters=params).result_rows[0][0])
    params["limit"] = limit
    result = client.query(
        f"SELECT {_HISTORY_COLS} FROM {AUDIT_LOG} WHERE {where} ORDER BY {_HISTORY_ORDER} LIMIT {{limit:UInt32}}",
        parameters=params,
    )
    return pd.DataFrame(result.result_rows, columns=result.column_names), total


def history_users() -> list[str]:
    return _history_users(data_version(AUDIT_LOG))


@st.cache_data(ttl=300, show_spinner=False)
def _history_users(version) -> list[str]:
    result = get_client().query(f"SELECT DISTINCT user_email FROM {AUDIT_LOG} WHERE user_email != '' ORDER BY 1")
    return [r[0] for r in result.result_rows]


def fetch_entry_states(log_id: str) -> tuple[str, str]:
    """(before_state, after_state) JSON of one entry; loaded only when the user opens it."""
    result = get_client().query(
        f"SELECT before_state, after_state FROM {AUDIT_LOG} WHERE log_id = toUUID({{id:String}}) LIMIT 1",
        parameters={"id": log_id},
    )
    return tuple(result.result_rows[0]) if result.result_rows else ("", "")
