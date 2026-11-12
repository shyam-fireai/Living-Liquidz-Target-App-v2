import pandas as pd
import pytest

from services.targets import (
    distribute_target,
    generate_daily_targets_from_monthly,
    month_weights,
    save_targets,
)


class TestDistributeTarget:
    def test_sums_exactly_with_awkward_values(self):
        ratios = month_weights("2026-10-01")["ratio"].tolist()
        for value in [1.0, 0.01, 99999.99, 12345678.91, 7.77]:
            daily = distribute_target(value, ratios)
            assert len(daily) == 31
            assert round(sum(daily), 2) == value

    def test_zero_none_nan(self):
        assert distribute_target(0, [0.5, 0.5]) == [None, None]
        assert distribute_target(None, [1.0]) == [None]
        assert distribute_target(float("nan"), [1.0]) == [None]


class FakeRepo:
    def __init__(self, fail_tables=(), fail_deactivate=False):
        self.calls = []
        self.fail_tables = fail_tables
        self.fail_deactivate = fail_deactivate

    def insert_dataframe(self, table, df):
        self.calls.append(("insert", table, len(df)))
        if table in self.fail_tables:
            return False, "boom"
        return True, "ok"

    def deactivate_keys(self, table, keys):
        if self.fail_deactivate:
            raise RuntimeError("mutation failed")
        self.calls.append(("deactivate", table, keys))

    def deactivate_daily_for_months(self, keys):
        self.calls.append(("deactivate_daily", keys))


def _branch_rows(*rows):
    return pd.DataFrame([{"month": m, "branch_name": b, "series_group": s, "target_value1": v} for m, b, s, v in rows])


OLD_OCT_KEY = [{"month": "2026-10-01", "branch_name": "A", "series_group": "X"}]
BRANCH = "branch_wise_monthly_target"


class TestSaveTargets:
    def test_upload_inserts_monthly_then_daily(self):
        repo = FakeRepo()
        report = save_targets(BRANCH, _branch_rows(("2026-11-01", "A", "X", 3000)), repo=repo)
        assert report.ok and report.saved_rows == 1 and report.daily_rows == 30
        assert [c[:2] for c in repo.calls] == [("insert", BRANCH), ("insert", "date_branch_wise_target")]

    def test_monthly_failure_saves_nothing_else(self):
        repo = FakeRepo(fail_tables=(BRANCH,))
        report = save_targets(BRANCH, _branch_rows(("2026-11-01", "A", "X", 1)), replaced_keys=OLD_OCT_KEY, repo=repo)
        assert report.nothing_saved
        assert len(repo.calls) == 1  # no daily insert, no deactivation

    def test_daily_failure_reported_and_old_daily_kept(self):
        repo = FakeRepo(fail_tables=("date_branch_wise_target",))
        report = save_targets(BRANCH, _branch_rows(("2026-11-01", "A", "X", 1)), replaced_keys=OLD_OCT_KEY, repo=repo)
        assert not report.ok and not report.nothing_saved
        assert "NOT regenerated" in report.message
        assert not any(c[0] == "deactivate_daily" for c in repo.calls)

    def test_key_change_retires_old_key_after_inserts(self):
        repo = FakeRepo()
        report = save_targets(BRANCH, _branch_rows(("2026-11-01", "A", "X", 1)), replaced_keys=OLD_OCT_KEY, repo=repo)
        assert report.ok and report.deactivated_keys == 1
        assert [c[0] for c in repo.calls] == ["insert", "insert", "deactivate", "deactivate_daily"]

    def test_old_key_still_present_in_new_rows_is_not_retired(self):
        # swap A <-> B: both old keys are re-used by new rows, so nothing may be deactivated
        repo = FakeRepo()
        new = _branch_rows(("2026-11-01", "B", "X", 1), ("2026-11-01", "a ", "X", 2))
        old = [
            {"month": "2026-11-01", "branch_name": "A", "series_group": "X"},
            {"month": pd.Timestamp("2026-11-01"), "branch_name": "B", "series_group": "X"},
        ]
        report = save_targets(BRANCH, new, replaced_keys=old, repo=repo)
        assert report.deactivated_keys == 0
        assert all(c[0] == "insert" for c in repo.calls)

    def test_deactivation_failure_is_reported_not_raised(self):
        repo = FakeRepo(fail_deactivate=True)
        report = save_targets(BRANCH, _branch_rows(("2026-11-01", "A", "X", 1)), replaced_keys=OLD_OCT_KEY, repo=repo)
        assert report.saved_rows == 1 and not report.ok
        assert "could not be retired" in report.message

    def test_brand_table_has_no_daily_step(self):
        repo = FakeRepo()
        row = {"month": "2026-11-01", "branch_name": "A", "series_group": "X", "item_code": "1"}
        row |= {"item_name": "N", "pack_name": "P", "target_qty1": 5}
        report = save_targets("brand_wise_monthly_target", pd.DataFrame([row]), repo=repo)
        assert report.ok and report.daily_rows == 0
        assert repo.calls == [("insert", "brand_wise_monthly_target", 1)]


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
