"""Business rules for targets: monthly -> daily split, and the one save path used by upload and edit."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from config import BRANCH_MONTHLY, DATE_BRANCH, get_table

logger = logging.getLogger(__name__)

TARGET_COLS = [f"target_value{i}" for i in range(1, 6)]
WEEKEND_WEIGHT = 5.0  # Fri, Sat, Sun
WEEKDAY_WEIGHT = 3.0  # Mon - Thu


# -------------------------------
# MONTHLY -> DAILY SPLIT
# -------------------------------
def month_weights(month) -> pd.DataFrame:
    """One row per day of `month` with its weight and ratio (ratios sum to 1)."""
    start = pd.to_datetime(month).to_period("M").start_time
    dates = pd.date_range(start, periods=start.days_in_month)
    weights = [WEEKEND_WEIGHT if d.weekday() >= 4 else WEEKDAY_WEIGHT for d in dates]
    df = pd.DataFrame({"date": dates, "weight": weights})
    df["ratio"] = df["weight"] / df["weight"].sum()
    return df


def distribute_target(monthly_val, ratios) -> list[float | None]:
    """Split a monthly value by `ratios`, rounding to paise; the last day absorbs the rounding
    remainder so the daily values always add up exactly to the monthly value."""
    n_days = len(ratios)
    if monthly_val is None or pd.isna(monthly_val) or monthly_val == 0:
        return [None] * n_days
    daily = [round(monthly_val * r, 2) for r in ratios[:-1]]
    daily.append(round(monthly_val - sum(daily), 2))
    return daily


def generate_daily_targets_from_monthly(df_monthly: pd.DataFrame) -> pd.DataFrame:
    """Expand monthly branch targets into daily rows (incentives are not used at daily level)."""
    df = df_monthly.copy()
    for col in TARGET_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else None

    records = []
    for month_val, group in df.groupby(df["month"].dt.strftime("%Y-%m")):
        weights = month_weights(f"{month_val}-01")
        ratios = weights["ratio"].tolist()
        dates = weights["date"].tolist()

        for _, row in group.iterrows():
            daily = {col: distribute_target(row[col], ratios) for col in TARGET_COLS}
            for i, day in enumerate(dates):
                rec = {
                    "date": day,
                    "branch_name": row.get("branch_name", ""),
                    "series_group": row.get("series_group", ""),
                }
                for n in range(1, 6):
                    value = daily[f"target_value{n}"][i]
                    rec[f"target_value{n}"] = value if value is not None else 0.0
                    rec[f"incentive_value{n}"] = 0.0
                records.append(rec)

    df_daily = pd.DataFrame(records)
    if not df_daily.empty:
        df_daily["date"] = pd.to_datetime(df_daily["date"])
    return df_daily


# -------------------------------
# SAVE
# -------------------------------
@dataclass
class SaveReport:
    table: str
    saved_rows: int = 0
    daily_rows: int = 0
    deactivated_keys: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def nothing_saved(self) -> bool:
        return self.saved_rows == 0 and bool(self.errors)

    @property
    def message(self) -> str:
        parts = []
        if self.saved_rows:
            parts.append(f"{self.saved_rows} {get_table(self.table).display_name} row(s) saved")
        if self.daily_rows:
            parts.append(f"{self.daily_rows} daily target row(s) regenerated")
        if self.deactivated_keys:
            parts.append(f"{self.deactivated_keys} old key(s) retired")
        return "; ".join(parts + self.errors)


def _norm_key(row, key_cols, date_col) -> tuple:
    return tuple(pd.to_datetime(row[c]).date() if c == date_col else str(row[c]).strip().upper() for c in key_cols)


def save_targets(table: str, df: pd.DataFrame, replaced_keys: list[dict] | None = None, repo=None) -> SaveReport:
    """Save target rows and keep dependent data consistent.

    Order is chosen so a failure never loses data:
      1. insert the rows (new version supersedes old rows with the same key)
      2. for Branch Wise Monthly Target: regenerate and insert the daily rows
      3. retire rows whose key was changed in an edit (`replaced_keys` = old key values),
         skipping any old key that is also present among the new rows.
    """
    if repo is None:
        from db import repository as repo

    from services.validation import clean_dataframe_for_db

    cfg = get_table(table)
    report = SaveReport(table=table)
    if df.empty:
        return report

    ok, msg = repo.insert_dataframe(table, df)
    if not ok:
        report.errors.append(f"Nothing was saved: {msg}")
        return report
    report.saved_rows = len(df)

    daily_ok = True
    if table == BRANCH_MONTHLY:
        monthly = clean_dataframe_for_db(df)
        monthly["month"] = pd.to_datetime(monthly["month"])
        df_daily = generate_daily_targets_from_monthly(monthly)
        ok, msg = repo.insert_dataframe(DATE_BRANCH, df_daily)
        if ok:
            report.daily_rows = len(df_daily)
        else:
            daily_ok = False
            report.errors.append(f"Daily targets were NOT regenerated ({msg}). Save again to retry.")

    new_keys = {_norm_key(r, cfg.key_cols, cfg.date_col) for _, r in df.iterrows()}
    stale = [k for k in (replaced_keys or []) if _norm_key(k, cfg.key_cols, cfg.date_col) not in new_keys]
    if stale:
        try:
            repo.deactivate_keys(table, stale)
            if table == BRANCH_MONTHLY and daily_ok:
                repo.deactivate_daily_for_months(stale)
            report.deactivated_keys = len(stale)
        except Exception as e:
            logger.exception("Retiring old keys in %s failed", table)
            report.errors.append(f"New values saved, but old rows could not be retired ({e}).")

    logger.info("save_targets(%s): %s", table, report.message)
    return report
