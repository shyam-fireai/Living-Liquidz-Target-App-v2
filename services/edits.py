"""Edit-screen rules: what changed (cell by cell), and whether the edited rows may be saved."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from config import TableConfig
from services.validation import ERROR, parse_date, parse_number, validate_upload


def row_label(cfg: TableConfig, row: pd.Series) -> str:
    parts = []
    for col in cfg.key_cols:
        value = row[col]
        if col == cfg.date_col:
            parsed = parse_date(value)
            value = parsed.date() if parsed is not None else value
        parts.append(str(value))
    return " · ".join(parts)


def _norm(cfg: TableConfig, col: str, value):
    if col == cfg.date_col:
        parsed = parse_date(value)
        return parsed.date() if parsed is not None else str(value)
    if col in cfg.value_cols:
        number = parse_number(value)
        return round(number, 2) if number is not None else str(value).strip()
    return str(value).strip().upper()


def changed_rows_mask(cfg: TableConfig, original: pd.DataFrame, edited: pd.DataFrame) -> pd.Series:
    """True for rows where any business column differs (display formatting ignored)."""
    mask = []
    for (_, old), (_, new) in zip(original.iterrows(), edited.iterrows(), strict=True):
        mask.append(any(_norm(cfg, c, old[c]) != _norm(cfg, c, new[c]) for c in cfg.columns))
    return pd.Series(mask, index=original.index, dtype=bool)


def cell_changes(cfg: TableConfig, original: pd.DataFrame, edited: pd.DataFrame) -> pd.DataFrame:
    """One line per changed cell: Row (original key), Column, Old, New."""
    out = []
    for idx in original.index:
        old_row, new_row = original.loc[idx], edited.loc[idx]
        for col in cfg.columns:
            if _norm(cfg, col, old_row[col]) != _norm(cfg, col, new_row[col]):
                out.append({"Row": row_label(cfg, old_row), "column": col, "Old": old_row[col], "New": new_row[col]})
    return pd.DataFrame(out, columns=["Row", "column", "Old", "New"])


@dataclass
class EditCheck:
    rows: pd.DataFrame  # cleaned rows ready for save_targets (same index as the edited rows)
    replaced_keys: list[dict]  # original keys of rows whose key was changed
    problems: list[dict] = field(default_factory=list)  # {"Row", "Column", "Value", "Problem"}

    @property
    def ok(self) -> bool:
        return not self.problems


def check_edits(
    cfg: TableConfig, original: pd.DataFrame, edited: pd.DataFrame, existing: pd.DataFrame | None = None
) -> EditCheck:
    """Validate edited rows with the same rules as uploads, plus: a changed key must not collide
    with another row that already exists (that would silently overwrite it)."""
    labels = [row_label(cfg, original.loc[i]) for i in edited.index]
    check = validate_upload(edited[list(cfg.columns)].reset_index(drop=True), cfg)
    problems = [
        {"Row": labels[i.row - 2] if i.row else "-", "Column": i.column, "Value": i.value, "Problem": i.problem}
        for i in check.issues
        if i.severity == ERROR
    ]
    rows = check.rows.drop(columns="_row", errors="ignore")
    rows.index = edited.index

    replaced, moved_to = [], []
    for idx in edited.index:
        old_key = tuple(_norm(cfg, c, original.loc[idx, c]) for c in cfg.key_cols)
        new_key = tuple(_norm(cfg, c, edited.loc[idx, c]) for c in cfg.key_cols)
        if old_key != new_key:
            replaced.append({c: original.loc[idx, c] for c in cfg.key_cols})
            moved_to.append((idx, new_key))

    if moved_to and existing is not None and not existing.empty:
        stored = {tuple(_norm(cfg, c, r[c]) for c in cfg.key_cols) for _, r in existing.iterrows()}
        freed = {tuple(_norm(cfg, c, original.loc[i, c]) for c in cfg.key_cols) for i in edited.index}
        for idx, new_key in moved_to:
            if new_key in stored and new_key not in freed:
                problems.append(
                    {
                        "Row": labels[list(edited.index).index(idx)],
                        "Column": "key",
                        "Value": " · ".join(str(v) for v in new_key),
                        "Problem": "Another row with this key already exists",
                    }
                )
    return EditCheck(rows=rows, replaced_keys=replaced, problems=problems)
