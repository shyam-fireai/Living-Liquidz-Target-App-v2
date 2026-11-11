"""Turn raw audit-log entries into what the History page shows. Pure functions (unit-tested)."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from config import DISPLAY_TZ, TABLES

ACTION_LABELS = {
    "UPLOAD": "\U0001f4e4 Upload",
    "EDIT": "\U0001f4dd Edit",
    "ERROR": "❌ Error",
    "LOGIN": "\U0001f511 Login",
    "LOGOUT": "\U0001f6aa Logout",
}
DEFAULT_ACTIONS = ("UPLOAD", "EDIT", "ERROR")


def ist_day_bounds(start: date, end: date) -> tuple[int, int]:
    """Unix seconds covering whole IST days start..end (inclusive)."""
    first = datetime.combine(start, time.min, tzinfo=DISPLAY_TZ)
    last = datetime.combine(end + timedelta(days=1), time.min, tzinfo=DISPLAY_TZ) - timedelta(seconds=1)
    return int(first.timestamp()), int(last.timestamp())


def format_ist(unix_seconds: int) -> str:
    return datetime.fromtimestamp(int(unix_seconds), tz=DISPLAY_TZ).strftime("%d %b %Y, %H:%M:%S")


def table_label(name: str) -> str:
    return TABLES[name].display_name if name in TABLES else (name or "—")


def parse_json(raw) -> object:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def describe(action: str, metadata_raw: str, error_message: str = "") -> str:
    """One-line, human summary of an entry."""
    meta = parse_json(metadata_raw) or {}
    if not isinstance(meta, dict):
        meta = {}
    parts: list[str] = []
    source = str(meta.get("source", ""))

    if action == "UPLOAD":
        if source:
            parts.append("Daily targets regenerated")
            if meta.get("file_name"):
                parts.append(f"from {meta['file_name']}")
        else:
            if meta.get("file_name"):
                parts.append(f"File {meta['file_name']}")
            counts = [f"{meta[k]} {k}" for k in ("new", "updated", "unchanged") if k in meta]
            if counts:
                parts.append(", ".join(counts))
    elif action == "EDIT":
        if source:
            parts.append("Daily targets regenerated after edit")
        else:
            if "changed_cells" in meta:
                parts.append(f"{meta['changed_cells']} cell(s) changed")
            if meta.get("key_changes"):
                parts.append(f"{meta['key_changes']} key change(s)")

    if error_message:
        parts.append(f"⚠️ {error_message}" if action in ("UPLOAD", "EDIT") else error_message)
    return " · ".join(parts)


def state_diff(before_raw: str, after_raw: str, key_cols: tuple[str, ...] = ()) -> list[dict]:
    """Cell-level changes of an EDIT entry. before/after are lists of row dicts in the same order."""
    before = parse_json(before_raw)
    after = parse_json(after_raw)
    if not isinstance(before, list) or not isinstance(after, list):
        return []
    changes = []
    for old, new in zip(before, after, strict=False):
        if not isinstance(old, dict) or not isinstance(new, dict):
            continue
        label = " / ".join(_short(new.get(c, old.get(c))) for c in key_cols if c in new or c in old)
        for col in dict.fromkeys([*old, *new]):
            if not _same(old.get(col), new.get(col)):
                changes.append({"Row": label, "Column": col, "Old": old.get(col), "New": new.get(col)})
    return changes


def _short(value) -> str:
    text = str(value)
    return text[:10] if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-" else text  # ISO date


def _same(a, b) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return _short(a) == _short(b)
