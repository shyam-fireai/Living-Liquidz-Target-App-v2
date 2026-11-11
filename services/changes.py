"""Compare incoming rows with what is already stored, to preview an upload before saving."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import TableConfig

NEW, UPDATED, UNCHANGED = "new", "updated", "unchanged"


@dataclass
class ChangeSet:
    rows: pd.DataFrame  # incoming rows + "status" + "changes" (list of (column, old, new))

    def count(self, status: str) -> int:
        return int((self.rows["status"] == status).sum()) if not self.rows.empty else 0

    @property
    def to_save(self) -> pd.DataFrame:
        """Only rows that actually change something (new or updated)."""
        if self.rows.empty:
            return self.rows
        return self.rows[self.rows["status"] != UNCHANGED]

    @property
    def summary(self) -> str:
        return f"{self.count(NEW)} new, {self.count(UPDATED)} updated, {self.count(UNCHANGED)} unchanged"


def _key_frame(df: pd.DataFrame, cfg: TableConfig) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for col in cfg.key_cols:
        if col == cfg.date_col:
            out[col] = pd.to_datetime(df[col]).dt.normalize()
        else:
            out[col] = df[col].astype(str).str.strip().str.upper()
    return out


def classify_changes(incoming: pd.DataFrame, existing: pd.DataFrame, cfg: TableConfig) -> ChangeSet:
    """Label each incoming row new / updated / unchanged against the active rows in `existing`."""
    rows = incoming.copy()
    if rows.empty:
        return ChangeSet(rows.assign(status=pd.Series(dtype=str), changes=pd.Series(dtype=object)))

    stored: dict[tuple, pd.Series] = {}
    if existing is not None and not existing.empty:
        ex_keys = _key_frame(existing, cfg)
        for i, key in enumerate(ex_keys.itertuples(index=False, name=None)):
            stored[key] = existing.iloc[i]

    statuses, changes = [], []
    for key, (_, row) in zip(_key_frame(rows, cfg).itertuples(index=False, name=None), rows.iterrows(), strict=True):
        old = stored.get(key)
        if old is None:
            statuses.append(NEW)
            changes.append([])
            continue
        diff = []
        for col in cfg.value_cols:
            before = round(float(old[col] or 0), 2)
            after = round(float(row[col] or 0), 2)
            if before != after:
                diff.append((col, before, after))
        statuses.append(UPDATED if diff else UNCHANGED)
        changes.append(diff)

    rows["status"] = statuses
    rows["changes"] = changes
    return ChangeSet(rows)
