import io

import pandas as pd
import pytest

from upload import generate_daily_targets_from_monthly, robust_read_csv

BOM = chr(0xFEFF)
NBSP = chr(0xA0)
E_UMLAUT = chr(0xCB)  # cp1252 byte 0xCB; followed by an ASCII byte it is invalid UTF-8


class TestRobustReadCsv:
    def test_utf8_comma(self):
        df = robust_read_csv(io.BytesIO(b"branch_name,target_value1\nA,100\nB,200\n"))
        assert df.columns.tolist() == ["branch_name", "target_value1"]
        assert df["target_value1"].tolist() == [100, 200]

    def test_utf8_bom_stripped(self):
        df = robust_read_csv(io.BytesIO((BOM + "branch_name,x\nA,1\n").encode("utf-8")))
        assert df.columns[0] == "branch_name"

    def test_semicolon_delimiter(self):
        df = robust_read_csv(io.BytesIO(b"branch_name;target_value1\nA;100\nB;200\n"))
        assert df.columns.tolist() == ["branch_name", "target_value1"]

    def test_cp1252_fallback_and_nbsp(self):
        name = "MO" + E_UMLAUT + "T" + NBSP + "CHANDON"
        raw = ("branch_name,note\n" + name + ",x\n").encode("cp1252")
        df = robust_read_csv(io.BytesIO(raw))
        assert df.loc[0, "branch_name"] == "MO" + E_UMLAUT + "T CHANDON"


def _monthly(rows):
    df = pd.DataFrame(rows)
    df["month"] = pd.to_datetime(df["month"])
    return df


class TestGenerateDailyTargets:
    def test_one_row_per_day_and_sum_matches_exactly(self):
        df = _monthly([{"month": "2026-11-01", "branch_name": "A", "series_group": "X", "target_value1": 100000.0}])
        daily = generate_daily_targets_from_monthly(df)
        assert len(daily) == 30
        assert daily["date"].min() == pd.Timestamp("2026-11-01")
        assert daily["date"].max() == pd.Timestamp("2026-11-30")
        assert round(daily["target_value1"].sum(), 2) == 100000.0

    def test_weekends_weighted_higher(self):
        df = _monthly([{"month": "2026-11-01", "branch_name": "A", "series_group": "X", "target_value1": 90000.0}])
        daily = generate_daily_targets_from_monthly(df).set_index("date")
        # 2026-11-02 is a Monday (weight 3), 2026-11-06 is a Friday (weight 5)
        mon = daily.loc["2026-11-02", "target_value1"]
        fri = daily.loc["2026-11-06", "target_value1"]
        assert fri / mon == pytest.approx(5 / 3, rel=1e-3)

    def test_zero_and_missing_targets_become_zero(self):
        df = _monthly(
            [
                {
                    "month": "2026-02-01",
                    "branch_name": "A",
                    "series_group": "X",
                    "target_value1": 0,
                    "target_value2": None,
                }
            ]
        )
        daily = generate_daily_targets_from_monthly(df)
        assert len(daily) == 28
        for col in ["target_value1", "target_value2", "target_value3", "target_value4", "target_value5"]:
            assert (daily[col] == 0.0).all()
        assert (daily["incentive_value1"] == 0.0).all()

    def test_multiple_months_and_branches(self):
        df = _monthly(
            [
                {"month": "2026-10-01", "branch_name": "A", "series_group": "X", "target_value1": 3100.0},
                {"month": "2026-11-01", "branch_name": "A", "series_group": "X", "target_value1": 3000.0},
                {"month": "2026-11-01", "branch_name": "B", "series_group": "Y", "target_value1": 1234.56},
            ]
        )
        daily = generate_daily_targets_from_monthly(df)
        assert len(daily) == 31 + 30 + 30
        sums = daily.groupby([daily["date"].dt.month, "branch_name"])["target_value1"].sum().round(2)
        assert sums.to_dict() == {(10, "A"): 3100.0, (11, "A"): 3000.0, (11, "B"): 1234.56}

    def test_empty_input(self):
        df = _monthly([{"month": "2026-11-01", "branch_name": "A", "series_group": "X"}]).iloc[0:0]
        assert generate_daily_targets_from_monthly(df).empty
