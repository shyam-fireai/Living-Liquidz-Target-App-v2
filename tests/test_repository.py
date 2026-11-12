import pandas as pd
import pytest

from db import repository as db


class TestBuildWhere:
    def test_no_filters_only_active(self):
        assert db.build_where("branch_wise_monthly_target", None) == ("is_active = 1", {})

    def test_values_are_parameters_never_inlined(self):
        evil = "X' OR 1=1 --"
        sql, params = db.build_where("branch_wise_monthly_target", {"branch_name": [evil]})
        assert evil not in sql
        assert "branch_name IN {f0:Array(String)}" in sql
        assert params == {"f0": [evil]}

    def test_month_multiselect_is_in_list_not_range(self):
        # two months picked must not silently include the months in between
        sql, params = db.build_where("branch_wise_monthly_target", {"month": ["2026-01-01", "2026-03-01"]})
        assert "month IN {f0:Array(Date)}" in sql
        assert [str(d) for d in params["f0"]] == ["2026-01-01", "2026-03-01"]

    def test_date_range(self):
        sql, params = db.build_where("date_branch_wise_target", {"date": ("2026-11-01", "2026-11-15")})
        assert "date BETWEEN {f0_from:Date} AND {f0_to:Date}" in sql
        assert (str(params["f0_from"]), str(params["f0_to"])) == ("2026-11-01", "2026-11-15")

    def test_single_day_range(self):
        _, params = db.build_where("date_branch_wise_target", {"date": ("2026-11-05",)})
        assert params["f0_from"] == params["f0_to"]

    def test_unknown_column_or_table_rejected(self):
        with pytest.raises(ValueError):
            db.build_where("branch_wise_monthly_target", {"is_active; DROP TABLE x": ["1"]})
        with pytest.raises(ValueError):
            db.build_where("system.users", {})


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
