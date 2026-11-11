"""Single source of truth for table metadata and secrets."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent
SECRETS_PATH = Path(os.getenv("LL_SECRETS_PATH", PROJECT_DIR / "secrets.json"))

# Columns written by the app itself, never shown to or supplied by users.
SYSTEM_COLUMNS = ("version", "updated_at", "is_active")
STRING_COLUMNS = ("branch_name", "series_group", "item_code", "item_name", "pack_name", "series")
DEFAULT_ROW_LIMIT = 200


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


@lru_cache(maxsize=1)
def load_secrets() -> dict:
    """Load secrets.json once. Missing file -> empty dict (env vars may still supply values)."""
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("Secrets file not found at %s", SECRETS_PATH)
        return {}


def get_secret(key: str, default=None):
    """Environment variable wins over secrets.json."""
    return os.getenv(key) or load_secrets().get(key, default)
