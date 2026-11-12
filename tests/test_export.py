import io
from datetime import date
from decimal import Decimal

import openpyxl
import pandas as pd

from config import TABLES
from services.export import INDIAN_NUMBER_FORMAT, export_frame, to_csv_bytes, to_excel_bytes
from services.validation import robust_read_csv, validate_upload
from ui.filters import describe_filters

BRANCH = TABLES["branch_wise_monthly_target"]


def stored_rows():
    row = {c: Decimal("0.00") for c in BRANCH.value_cols}
    row.update(month=date(2026, 11, 1), branch_name="AMRUT WINES RET", series_group="RSL")
    row["target_value1"] = Decimal("12345678.90")
    return pd.DataFrame([row | {"version": 1, "is_active": 1}])


def test_export_frame_drops_system_columns_and_keeps_numbers():
    out = export_frame(BRANCH, stored_rows())
    assert list(out.columns) == list(BRANCH.columns)
    assert out.loc[0, "target_value1"] == 12345678.9
    assert out.loc[0, "month"] == date(2026, 11, 1)


def test_csv_export_can_be_uploaded_again():
    raw = robust_read_csv(io.BytesIO(to_csv_bytes(BRANCH, stored_rows())))
    check = validate_upload(raw, BRANCH)
    assert check.issues == []
    assert check.rows.loc[0, "target_value1"] == 12345678.9


def test_excel_export_numbers_dates_and_format():
    wb = openpyxl.load_workbook(io.BytesIO(to_excel_bytes(BRANCH, stored_rows())))
    ws = wb.active
    header = [c.value for c in ws[1]]
    assert header == list(BRANCH.columns)
    t1 = ws.cell(row=2, column=header.index("target_value1") + 1)
    assert t1.value == 12345678.9 and t1.number_format == INDIAN_NUMBER_FORMAT
    assert ws.cell(row=2, column=1).value.date() == date(2026, 11, 1)
    assert ws.freeze_panes == "A2"


def test_describe_filters():
    filters = {
        "month": [date(2026, 10, 1)],
        "branch_name": ["A", "B", "C", "D", "E"],
    }
    assert describe_filters(BRANCH, filters) == ["Month: Oct 2026", "Branch Name: A, B, C +2 more"]
    daily = TABLES["date_branch_wise_target"]
    assert describe_filters(daily, {"date": (date(2026, 11, 1), date(2026, 11, 7))}) == [
        "Date: 2026-11-01 → 2026-11-07"
    ]
    assert describe_filters(BRANCH, {}) == []
