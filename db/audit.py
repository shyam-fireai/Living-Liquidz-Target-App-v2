"""Audit trail written to target_system_audit_logs. Failures are logged, never raised."""

import json
import logging
import time
import urllib.parse
from datetime import date, datetime

import pandas as pd
import streamlit as st

from config import AUDIT_LOG
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
        logger.info("Audit: %s on %s (%s rows)", action_type, target_table or "-", params["record_count"])
    except Exception:
        logger.exception("Audit log write failed for %s", action_type)
