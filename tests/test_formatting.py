import pandas as pd
import pytest

from ui import formatting as fmt


class TestFormatColumn:
    @pytest.mark.parametrize(
        "col, expected",
        [("series_group", "Series"), ("branch_name", "Branch Name"), ("target_value1", "Target Value1")],
    )
    def test_labels(self, col, expected):
        assert fmt.format_column(col) == expected


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
        assert fmt.format_indian_number(value) == expected

    def test_without_rupee(self):
        assert fmt.format_indian_number(1500, show_rupee=False) == "1,500.00"

    def test_blank_and_nan(self):
        assert fmt.format_indian_number("") == "0.00"
        assert fmt.format_indian_number(float("nan")) == "0.00"

    def test_non_numeric_returned_unchanged(self):
        assert fmt.format_indian_number("abc") == "abc"


class TestApplyCurrencyFormat:
    def test_value_and_qty_columns(self):
        df = pd.DataFrame({"branch_name": ["A"], "target_value1": [1000], "target_qty1": [2500]})
        out = fmt.apply_currency_format(df)
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
        out = fmt.remove_zero_columns(df)
        assert list(out.columns) == ["month", "branch_name", "series_group", "target_value1"]

    def test_only_protected_columns(self):
        df = pd.DataFrame({"branch_name": ["A"]})
        assert list(fmt.remove_zero_columns(df).columns) == ["branch_name"]


class TestFormatIndianCompact:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (6344922729.1, "₹634.49 Cr"),
            (123456789012, "₹12,345.68 Cr"),
            (250000, "₹2.50 L"),
            (99999, "₹99,999.00"),
            (0, "₹0.00"),
            (-15000000, "₹-1.50 Cr"),
        ],
    )
    def test_values(self, value, expected):
        assert fmt.format_indian_compact(value) == expected

    def test_without_rupee(self):
        assert fmt.format_indian_compact(5_000_000, show_rupee=False) == "50.00 L"
