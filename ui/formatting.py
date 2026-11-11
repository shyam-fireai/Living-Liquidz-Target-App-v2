"""Display helpers: column labels, Indian number format, hiding empty columns."""

import pandas as pd

# Old -> new highlighting used by the Edit review and the History details.
DIFF_OLD_STYLE = "background-color: #FEE2E2; color: #991B1B"
DIFF_NEW_STYLE = "background-color: #DCFCE7; color: #166534; font-weight: 600"

RUPEE = "₹"

# Columns always shown even when every value is zero/blank.
PROTECTED_COLUMNS = ("month", "date", "branch_name", "series_group", "series", "item_code", "item_name", "pack_name")


def format_column(col: str) -> str:
    if col == "series_group":
        return "Series"
    return col.replace("_", " ").title()


def format_indian_number(x, show_rupee: bool = True):
    """1234567.5 -> '12,34,567.50' (lakh/crore grouping). Non-numeric input is returned unchanged."""
    try:
        if pd.isna(x) or x == "":
            return "0.00"
        x_float = float(str(x).replace(RUPEE, "").replace(",", ""))
    except (TypeError, ValueError):
        return x

    sign = "-" if x_float < 0 else ""
    num, dec = f"{abs(x_float):.2f}".split(".")
    if len(num) > 3:
        rest, last3 = num[:-3], num[-3:]
        groups = [rest[max(i - 2, 0) : i] for i in range(len(rest), 0, -2)][::-1]
        num = ",".join(groups) + "," + last3

    prefix = RUPEE if show_rupee else ""
    return f"{prefix}{sign}{num}.{dec}"


def apply_currency_format(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if "value" in col.lower():
            df[col] = df[col].apply(lambda x: format_indian_number(x, show_rupee=True))
        elif "qty" in col.lower():
            df[col] = df[col].apply(lambda x: format_indian_number(x, show_rupee=False))
    return df


def remove_zero_columns(df: pd.DataFrame) -> pd.DataFrame:
    other_cols = [c for c in df.columns if c not in PROTECTED_COLUMNS]
    if not other_cols:
        return df
    num_df = df[other_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    non_zero = set(num_df.columns[(num_df != 0).any()])
    return df[[c for c in df.columns if c in PROTECTED_COLUMNS or c in non_zero]]


def format_indian_compact(x, show_rupee: bool = True) -> str:
    """Short form for summary cards: 6344922729.1 -> '₹634.49 Cr', 250000 -> '₹2.50 L'."""
    value = float(x or 0)
    prefix = RUPEE if show_rupee else ""
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1e7:
        return f"{prefix}{sign}{format_indian_number(value / 1e7, show_rupee=False)} Cr"
    if value >= 1e5:
        return f"{prefix}{sign}{value / 1e5:.2f} L"
    return f"{prefix}{sign}{format_indian_number(value, show_rupee=False)}"
