from datetime import date

import pandas as pd

from config import TABLES
from services.edits import cell_changes, changed_rows_mask, check_edits

BRANCH = TABLES["branch_wise_monthly_target"]


def frame(*rows, index=None):
    """rows: (month, branch, series, target_value1 as shown in the editor)"""
    data = []
    for m, b, s, t1 in rows:
        r = {c: "₹0.00" for c in BRANCH.value_cols}
        r.update(month=date.fromisoformat(m), branch_name=b, series_group=s, target_value1=t1)
        data.append(r)
    return pd.DataFrame(data, index=index)[list(BRANCH.columns)]


ORIG = frame(("2026-11-01", "A", "X", "₹1,00,000.00"), ("2026-11-01", "B", "X", "₹50.00"), index=[10, 11])


def test_formatting_only_differences_are_not_changes():
    edited = frame(("2026-11-01", "a ", "x", "100000"), ("2026-11-01", "B", "X", "50"), index=[10, 11])
    assert not changed_rows_mask(BRANCH, ORIG, edited).any()


def test_cell_changes_lists_old_and_new():
    edited = frame(("2026-11-01", "A", "X", "₹1,20,000"), ("2026-11-01", "B", "X", "₹50.00"), index=[10, 11])
    mask = changed_rows_mask(BRANCH, ORIG, edited)
    assert mask.tolist() == [True, False]
    diff = cell_changes(BRANCH, ORIG[mask], edited[mask])
    assert diff.to_dict(orient="records") == [
        {"Row": "2026-11-01 · A · X", "column": "target_value1", "Old": "₹1,00,000.00", "New": "₹1,20,000"}
    ]


def test_value_edit_is_valid_and_cleaned():
    edited = frame(("2026-11-01", "A", "X", "1,20,000.5"), index=[10])
    check = check_edits(BRANCH, ORIG.loc[[10]], edited)
    assert check.ok and check.replaced_keys == []
    assert check.rows.loc[10, "target_value1"] == 120000.5
    assert check.rows.index.tolist() == [10]


def test_invalid_values_block_saving():
    edited = frame(("2026-11-01", "A", "X", "abc"), ("2026-11-01", "B", "X", "-5"), index=[10, 11])
    check = check_edits(BRANCH, ORIG, edited)
    assert not check.ok
    assert sorted((p["Row"], p["Problem"]) for p in check.problems) == [
        ("2026-11-01 · A · X", "Not a number"),
        ("2026-11-01 · B · X", "Negative value"),
    ]


def test_key_change_recorded_as_replaced():
    edited = frame(("2026-12-01", "A", "X", "₹1,00,000.00"), index=[10])
    check = check_edits(BRANCH, ORIG.loc[[10]], edited)
    assert check.ok
    assert check.replaced_keys == [{"month": date(2026, 11, 1), "branch_name": "A", "series_group": "X"}]


def test_key_change_onto_existing_row_is_blocked():
    edited = frame(("2026-11-01", "C", "X", "1"), index=[10])
    existing = pd.DataFrame([{"month": date(2026, 11, 1), "branch_name": "C", "series_group": "X"}])
    check = check_edits(BRANCH, ORIG.loc[[10]], edited, existing)
    assert [p["Problem"] for p in check.problems] == ["Another row with this key already exists"]


def test_swapping_two_keys_is_allowed():
    edited = frame(("2026-11-01", "B", "X", "1"), ("2026-11-01", "A", "X", "2"), index=[10, 11])
    existing = pd.DataFrame([{"month": date(2026, 11, 1), "branch_name": b, "series_group": "X"} for b in ("A", "B")])
    check = check_edits(BRANCH, ORIG, edited, existing)
    assert check.ok and len(check.replaced_keys) == 2


def test_two_edited_rows_with_same_new_key_blocked():
    edited = frame(("2026-11-01", "A", "X", "1"), ("2026-11-01", "A", "X", "2"), index=[10, 11])
    check = check_edits(BRANCH, ORIG, edited)
    assert any(p["Problem"].startswith("Duplicate") for p in check.problems)
