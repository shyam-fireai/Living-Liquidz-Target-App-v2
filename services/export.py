"""CSV / Excel exports of target rows (numbers stay numeric; Excel shows Indian digit grouping)."""

from __future__ import annotations

import io

import pandas as pd

from config import TableConfig

# Excel number format with lakh/crore grouping: 1,23,45,678.00
INDIAN_NUMBER_FORMAT = "[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00"


def export_frame(cfg: TableConfig, df: pd.DataFrame) -> pd.DataFrame:
    """Business columns only, in upload order, with plain dates and float values.
    Column names stay technical so an exported file can be edited and uploaded again."""
    out = df[list(cfg.columns)].copy()
    out[cfg.date_col] = pd.to_datetime(out[cfg.date_col]).dt.date
    for col in cfg.value_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0).astype(float)
    return out


def to_csv_bytes(cfg: TableConfig, df: pd.DataFrame) -> bytes:
    # utf-8-sig so Excel opens it with the right encoding
    return export_frame(cfg, df).to_csv(index=False).encode("utf-8-sig")


def to_excel_bytes(cfg: TableConfig, df: pd.DataFrame, sheet: str = "Targets") -> bytes:
    data = export_frame(cfg, df)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        data.to_excel(writer, index=False, sheet_name=sheet)
        ws = writer.sheets[sheet]
        ws.freeze_panes = "A2"
        for idx, col in enumerate(data.columns, start=1):
            letter = ws.cell(row=1, column=idx).column_letter
            ws.column_dimensions[letter].width = max(12, min(40, len(col) + 4))
            if col in cfg.value_cols:
                for (c,) in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                    c.number_format = INDIAN_NUMBER_FORMAT
            elif col == cfg.date_col:
                for (c,) in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                    c.number_format = "yyyy-mm-dd"
    return buf.getvalue()
