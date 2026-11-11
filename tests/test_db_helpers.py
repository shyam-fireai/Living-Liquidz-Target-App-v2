import pandas as pd
import pytest

import db


class TestFormatSqlValues:
    def test_empty(self):
        assert db.format_sql_values([]) == ""
        assert db.format_sql_values(None) == ""

    def test_numbers_unquoted_strings_quoted(self):
        assert db.format_sql_values([1, 2.5, "MUMBAI", "2026-11-01"]) == "1, 2.5, 'MUMBAI', '2026-11-01'"


class TestFormatColumn:
    @pytest.mark.parametrize(
        "col, expected",
        [("series_group", "Series"), ("branch_name", "Branch Name"), ("target_value1", "Target Value1")],
    )
    def test_labels(self, col, expected):
        assert db.format_column(col) == expected


class TestFormatIndianNumber:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (0, "₹0.00"),
            (999, "₹999.00"),
            (1000, "₹1,000.00"),
            (123456, "₹1,23,456.00"),
            (1234567.5, "₹12,34,567.50"),
            (123456789, "₹12,34,56,789.00"),
            ("₹1,23,456.00", "₹1,23,456.00"),  # already formatted -> idempotent
            (-1234, "₹-1,234.00"),
            (-123456, "₹-1,23,456.00"),
            (-12345, "₹-12,345.00"),
            (-1234567, "₹-12,34,567.00"),
        ],
    )
    def test_with_rupee(self, value, expected):
        assert db.format_indian_number(value) == expected

    def test_without_rupee(self):
        assert db.format_indian_number(1500, show_rupee=False) == "1,500.00"

    def test_blank_and_nan(self):
        assert db.format_indian_number("") == "0.00"
        assert db.format_indian_number(float("nan")) == "0.00"

    def test_non_numeric_returned_unchanged(self):
        assert db.format_indian_number("abc") == "abc"


class TestApplyCurrencyFormat:
    def test_value_and_qty_columns(self):
        df = pd.DataFrame({"branch_name": ["A"], "target_value1": [1000], "target_qty1": [2500]})
        out = db.apply_currency_format(df)
        assert out.loc[0, "target_value1"] == "₹1,000.00"
        assert out.loc[0, "target_qty1"] == "2,500.00"
        assert out.loc[0, "branch_name"] == "A"
        assert df.loc[0, "target_value1"] == 1000  # input not mutated


class TestRemoveZeroColumns:
    def test_drops_all_zero_numeric_columns_keeps_protected(self):
        df = pd.DataFrame(
            {
                "month": ["2026-11-01", "2026-11-01"],
                "branch_name": ["A", "B"],
                "series_group": ["X", "Y"],
                "target_value1": [100, 0],
                "target_value2": [0, 0],
                "incentive_value1": ["0", None],
            }
        )
        out = db.remove_zero_columns(df)
        assert list(out.columns) == ["month", "branch_name", "series_group", "target_value1"]

    def test_only_protected_columns(self):
        df = pd.DataFrame({"branch_name": ["A"]})
        assert list(db.remove_zero_columns(df).columns) == ["branch_name"]


class TestCleanDataframeForDb:
    def test_strings_upper_stripped_and_null_tokens_blank(self):
        df = pd.DataFrame({"branch_name": ["  mumbai ", None, "nan"], "series_group": ["a", "b", "NULL"]})
        out = db.clean_dataframe_for_db(df)
        assert out["branch_name"].tolist() == ["MUMBAI", "", ""]
        assert out["series_group"].tolist() == ["A", "B", ""]

    def test_numeric_columns_strip_currency_and_coerce(self):
        df = pd.DataFrame(
            {
                "target_value1": ["₹1,23,456.50", "abc", None],
                "incentive_value1": [10, "2,000", ""],
                "target_qty1": ["5", 6, None],
            }
        )
        out = db.clean_dataframe_for_db(df)
        assert out["target_value1"].tolist() == [123456.5, 0.0, 0.0]
        assert out["incentive_value1"].tolist() == [10.0, 2000.0, 0.0]
        assert out["target_qty1"].tolist() == [5.0, 6.0, 0.0]

    def test_input_not_mutated(self):
        df = pd.DataFrame({"branch_name": [" a "]})
        db.clean_dataframe_for_db(df)
        assert df.loc[0, "branch_name"] == " a "


class TestGetAllFilterValues:
    @pytest.fixture
    def index_df(self, monkeypatch):
        df = pd.DataFrame(
            {
                "month": pd.to_datetime(["2026-10-01", "2026-10-01", "2026-11-01", "2026-11-01"]),
                "branch_name": ["A", "B", "A", "C"],
                "series_group": ["X", "Y", "X", "Z"],
            }
        )
        monkeypatch.setattr(db, "get_filter_index", lambda table: df)
        return df

    def test_no_selection_returns_all(self, index_df):
        out = db.get_all_filter_values("branch_wise_monthly_target")
        assert out["branch_name"] == ["A", "B", "C"]
        assert out["series_group"] == ["X", "Y", "Z"]

    def test_cascading_multiselect(self, index_df):
        out = db.get_all_filter_values("branch_wise_monthly_target", {"branch_name": ["A"]})
        assert out["series_group"] == ["X"]
        # a filter does not constrain its own options
        assert out["branch_name"] == ["A", "B", "C"]

    def test_date_range(self, index_df):
        out = db.get_all_filter_values("branch_wise_monthly_target", {"month": ("2026-11-01", "2026-11-30")})
        assert out["branch_name"] == ["A", "C"]

    def test_empty_index(self, monkeypatch):
        monkeypatch.setattr(db, "get_filter_index", lambda table: pd.DataFrame())
        assert db.get_all_filter_values("x") == {}
