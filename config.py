"""Single source of truth for table metadata and secrets."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent
SECRETS_PATH = Path(os.getenv("LL_SECRETS_PATH", PROJECT_DIR / "secrets.json"))

# Columns written by the app itself, never shown to or supplied by users.
SYSTEM_COLUMNS = ("version", "updated_at", "is_active")
STRING_COLUMNS = ("branch_name", "series_group", "item_code", "item_name", "pack_name", "series")
DEFAULT_ROW_LIMIT = 200
# Times shown to users (session expiry, history). India has no DST, so a fixed offset is exact and
# avoids depending on the OS timezone database (absent on Windows and slim Docker images).
DISPLAY_TZ = timezone(timedelta(hours=5, minutes=30), "IST")


@dataclass(frozen=True)
class TableConfig:
    name: str  # ClickHouse table name
    display_name: str
    date_col: str  # "month" (1st of month) or "date"
    key_cols: tuple[str, ...]  # business identity of a row
    value_cols: tuple[str, ...]  # targets / incentives
    currency: bool  # format values as rupees
    editable: bool  # can be edited / uploaded directly

    @property
    def columns(self) -> tuple[str, ...]:
        """User-facing columns in upload/CSV order."""
        return self.key_cols + self.value_cols

    @property
    def filter_cols(self) -> tuple[str, ...]:
        return self.key_cols


def _value_cols(target_prefix: str) -> tuple[str, ...]:
    cols: list[str] = []
    for i in range(1, 6):
        cols += [f"{target_prefix}{i}", f"incentive_value{i}"]
    return tuple(cols)


BRANCH_MONTHLY = "branch_wise_monthly_target"
BRAND_MONTHLY = "brand_wise_monthly_target"
DATE_BRANCH = "date_branch_wise_target"
AUDIT_LOG = "target_system_audit_logs"

TABLES: dict[str, TableConfig] = {
    BRANCH_MONTHLY: TableConfig(
        name=BRANCH_MONTHLY,
        display_name="Branch Wise Monthly Target",
        date_col="month",
        key_cols=("month", "branch_name", "series_group"),
        value_cols=_value_cols("target_value"),
        currency=True,
        editable=True,
    ),
    BRAND_MONTHLY: TableConfig(
        name=BRAND_MONTHLY,
        display_name="Brand Wise Monthly Target",
        date_col="month",
        key_cols=("month", "branch_name", "series_group", "item_code", "item_name", "pack_name"),
        value_cols=_value_cols("target_qty"),
        currency=False,
        editable=True,
    ),
    DATE_BRANCH: TableConfig(
        name=DATE_BRANCH,
        display_name="Date & Branch Wise Target",
        date_col="date",
        key_cols=("date", "branch_name", "series_group"),
        value_cols=_value_cols("target_value"),
        currency=True,
        editable=False,  # generated from Branch Wise Monthly Target
    ),
}


def get_table(name: str) -> TableConfig:
    """Return the config for a known table; raises for anything else (guards SQL identifiers)."""
    try:
        return TABLES[name]
    except KeyError:
        raise ValueError(f"Unknown table: {name!r}") from None


# -------------------------------
# SETTINGS
# Every setting is looked up in this order (first non-empty value wins):
#   1. st.secrets      - Streamlit Community Cloud "Secrets" box, or .streamlit/secrets.toml
#   2. environment     - Docker / servers
#   3. secrets.json    - local development
# See README "Configuration".
# -------------------------------
def _streamlit_secrets() -> dict:
    """Plain dict of st.secrets, or {} when no secrets.toml exists (the normal local case)."""
    try:
        import streamlit as st

        if st.secrets.load_if_toml_exists():
            return st.secrets.to_dict()
    except Exception as e:  # malformed TOML: report the type only, never the contents
        logger.error("Could not read Streamlit secrets (%s); falling back to env / secrets.json", type(e).__name__)
    return {}


def _present(value) -> bool:
    return value is not None and value != "" and value != []


@lru_cache(maxsize=1)
def load_secrets() -> dict:
    """Load secrets.json once. Missing file -> empty dict (env vars may supply everything)."""
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info("No secrets file at %s; using environment variables only", SECRETS_PATH)
        return {}


def get_secret(key: str, default=None):
    """st.secrets, then environment variable, then secrets.json."""
    for value in (_streamlit_secrets().get(key), os.getenv(key), load_secrets().get(key)):
        if _present(value):
            return value
    return default


# env var -> key inside secrets.json "data_clickhouse"
_DB_ENV = {
    "CLICKHOUSE_HOST": "host",
    "CLICKHOUSE_PORT": "port",
    "CLICKHOUSE_USER": "username",
    "CLICKHOUSE_PASSWORD": "password",
    "CLICKHOUSE_DATABASE": "database",
    "CLICKHOUSE_SECURE": "secure",
}


def _as_bool(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def get_db_settings() -> dict:
    """Each field: st.secrets (CLICKHOUSE_HOST or [data_clickhouse] host), then env, then secrets.json."""
    st_secrets = _streamlit_secrets()
    sources = [
        st_secrets,
        st_secrets.get("data_clickhouse") or {},
        os.environ,
        load_secrets().get("data_clickhouse") or {},
    ]
    conf = {}
    for env, key in _DB_ENV.items():
        for i, source in enumerate(sources):
            value = source.get(key if i in (1, 3) else env)
            if value is not None and value != "":
                conf[key] = value
                break
    conf.setdefault("port", 8123)
    conf["port"] = int(conf["port"])
    conf["secure"] = _as_bool(conf.get("secure", False))
    conf.setdefault("password", "")
    return conf


def get_allowed_emails() -> list[str]:
    """Accepts "a@x.com, b@x.com" (env / secrets.json) or a TOML list ["a@x.com", "b@x.com"]."""
    raw = get_secret("ALLOWED_EMAILS", [])
    items = raw.split(",") if isinstance(raw, str) else raw
    emails = []
    for item in items:  # a list entry may itself be "a@x.com, b@x.com"
        emails += [e.strip().lower() for e in str(item).split(",") if e.strip()]
    return emails


def session_seconds() -> int:
    return int(float(get_secret("SESSION_HOURS", 1)) * 3600)


def validate_settings() -> list[str]:
    """Human-readable problems with the configuration (never includes secret values)."""
    problems = []
    db = get_db_settings()
    for env, key in _DB_ENV.items():
        if key not in ("password", "secure", "port") and not db.get(key):
            problems.append(f"Database setting missing: {env} (or data_clickhouse.{key} in secrets.json)")
    for key in ("FIREAI_BASE_URL", "FIREAI_API_KEY"):
        if not get_secret(key):
            problems.append(f"Login service setting missing: {key}")
    if not get_allowed_emails():
        problems.append("ALLOWED_EMAILS is empty: nobody would be able to log in")
    if len(str(get_secret("COOKIE_SECRET") or "")) < 32:
        problems.append("COOKIE_SECRET missing or shorter than 32 characters (see README)")
    try:
        session_seconds()
    except ValueError:
        problems.append("SESSION_HOURS must be a number")
    return problems
