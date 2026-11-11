import io

import pandas as pd
import pytest

from config import TABLES
from services.changes import NEW, UNCHANGED, UPDATED, classify_changes
from services.validation import ERROR, WARNING, parse_date, parse_number, robust_read_csv, validate_upload

BRANCH = TABLES["branch_wise_monthly_target"]
BRAND = TABLES["brand_wise_monthly_target"]
HEADER = ",".join(BRANCH.columns)


def csv(*lines):
    """Build a branch-monthly CSV; each line gives month,branch,series,target_value1 (rest blank)."""
    body = [HEADER] + [line + "," * (len(BRANCH.columns) - 1 - line.count(",")) for line in lines]
    return robust_read_csv(io.BytesIO("\n".join(body).encode()))


def problems(check, severity=ERROR):
    return sorted(
        ((i.row, i.column, i.problem) for i in check.issues if i.severity == severity), key=lambda t: (t[0] or 0, t[1])
    )


class TestParsers:
    @pytest.mark.parametrize("text", ["2026-03-01", "01-03-2026", "01/03/2026", "2026-03-01 00:00:00"])
    def test_dates(self, text):
        assert parse_date(text) == pd.Timestamp("2026-03-01")

    @pytest.mark.parametrize("text", ["03/01/2026x", "2026-13-01", "March 2026", "abc"])
    def test_bad_dates(self, text):
        assert parse_date(text) is None

    @pytest.mark.parametrize(
        "text, expected", [("", 0.0), ("nan", 0.0), ("₹1,00,000.50", 100000.5), ("-5", -5.0), ("1e3", 1000.0)]
    )
    def test_numbers(self, text, expected):
        assert parse_number(text) == expected

    def test_bad_number(self):
        assert parse_number("12 lakh") is None


class TestValidateUpload:
    def test_clean_file(self):
        check = validate_upload(csv('2026-11-01,amrut wines ret,rsl,"₹1,000"'), BRANCH)
        assert check.issues == []
        row = check.rows.iloc[0]
        assert (row["branch_name"], row["series_group"], row["target_value1"]) == ("AMRUT WINES RET", "RSL", 1000.0)
        assert row["month"] == pd.Timestamp("2026-11-01") and row["_row"] == 2

    def test_all_problems_reported_at_once(self):
        check = validate_upload(
            csv(
                "2026-11-05,A,X,10",  # row 2: not 1st of month
                "not a date,B,X,10",  # row 3: bad date
                "2026-11-01,,X,abc",  # row 4: missing branch + not a number
                "2026-11-01,C,X,-1",  # row 5: negative
                "2026-11-01,D,X,100000000",  # row 6: too large
            ),
            BRANCH,
        )
        assert problems(check) == [
            (2, "month", "Month must be the 1st day of the month"),
            (3, "month", "Not a valid date (use YYYY-MM-DD)"),
            (4, "branch_name", "Missing value"),
            (4, "target_value1", "Not a number"),
            (5, "target_value1", "Negative value"),
            (6, "target_value1", "Too large (max 9,99,99,999.99)"),
        ]

    def test_duplicate_keys_case_insensitive(self):
        check = validate_upload(csv("2026-11-01,A,X,1", "2026-11-01,B,X,1", "01-11-2026, a ,x,2"), BRANCH)
        assert problems(check) == [(2, "key", "Duplicate of row 4"), (4, "key", "Duplicate of row 2")]

    def test_missing_columns_stop_early(self):
        raw = pd.DataFrame({"month": ["2026-11-01"], "branch_name": ["A"]})
        check = validate_upload(raw, BRANCH)
        assert len(check.errors) == 1 and check.errors[0].row is None
        assert "series_group" in check.errors[0].column

    def test_header_whitespace_and_case_tolerated(self):
        raw = csv("2026-11-01,A,X,1")
        raw.columns = [f" {c.upper()} " for c in raw.columns]
        assert validate_upload(raw, BRANCH).issues == []

    def test_unknown_branch_and_extra_column_are_warnings(self):
        raw = csv("2026-11-01,NEW SHOP,RSL,1")
        raw["remarks"] = "x"
        check = validate_upload(raw, BRANCH, {"branch_name": {"AMRUT WINES RET"}, "series_group": {"RSL"}})
        assert check.errors == []
        assert problems(check, WARNING) == [
            (None, "remarks", "Unknown column(s) will be ignored"),
            (2, "branch_name", "Not found in existing data (new?)"),
        ]

    def test_empty_file(self):
        check = validate_upload(robust_read_csv(io.BytesIO(HEADER.encode())), BRANCH)
        assert [i.problem for i in check.errors] == ["The file has no data rows"]

    def test_item_codes_keep_leading_zeros(self):
        header = ",".join(BRAND.columns)
        line = "2026-11-01,A,X,007,GIN,750ML" + ",1" * len(BRAND.value_cols)
        check = validate_upload(robust_read_csv(io.BytesIO(f"{header}\n{line}".encode())), BRAND)
        assert check.issues == [] and check.rows.iloc[0]["item_code"] == "007"

    def test_issues_frame_errors_first(self):
        raw = csv("2026-11-01,A,X,-1")
        raw["remarks"] = ""
        frame = validate_upload(raw, BRANCH).issues_frame()
        assert frame["Severity"].tolist() == ["Error", "Warning"]


class TestClassifyChanges:
    def _existing(self, *rows):
        df = pd.DataFrame(
            [{"month": pd.Timestamp(m).date(), "branch_name": b, "series_group": s} for m, b, s, _ in rows]
        )
        for col in BRANCH.value_cols:
            df[col] = 0.0
        df["target_value1"] = [v for *_, v in rows]
        return df

    def test_new_updated_unchanged(self):
        incoming = validate_upload(csv("2026-11-01,A,X,100", "2026-11-01,B,X,200", "2026-11-01,C,X,300"), BRANCH).rows
        existing = self._existing(("2026-11-01", "A", "X", 100), ("2026-11-01", "B", "X", 150))
        changes = classify_changes(incoming, existing, BRANCH)
        assert changes.rows["status"].tolist() == [UNCHANGED, UPDATED, NEW]
        assert changes.rows.iloc[1]["changes"] == [("target_value1", 150.0, 200.0)]
        assert changes.summary == "1 new, 1 updated, 1 unchanged"
        assert changes.to_save["branch_name"].tolist() == ["B", "C"]

    def test_decimal_from_db_compares_equal(self):
        from decimal import Decimal

        incoming = validate_upload(csv("2026-11-01,A,X,1234.5"), BRANCH).rows
        existing = self._existing(("2026-11-01", "A", "X", Decimal("1234.50")))
        assert classify_changes(incoming, existing, BRANCH).count(UNCHANGED) == 1

    def test_nothing_stored(self):
        incoming = validate_upload(csv("2026-11-01,A,X,1"), BRANCH).rows
        changes = classify_changes(incoming, pd.DataFrame(), BRANCH)
        assert changes.count(NEW) == 1
