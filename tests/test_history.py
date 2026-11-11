import json
from datetime import UTC, date, datetime

from db.audit import _history_where
from services.history import describe, format_ist, ist_day_bounds, state_diff, table_label


class TestTimes:
    def test_ist_day_bounds_cover_whole_ist_days(self):
        start, end = ist_day_bounds(date(2026, 11, 11), date(2026, 11, 11))
        # 11 Nov 00:00 IST = 10 Nov 18:30 UTC; 11 Nov 23:59:59 IST = 11 Nov 18:29:59 UTC
        assert datetime.fromtimestamp(start, tz=UTC) == datetime(2026, 11, 10, 18, 30, tzinfo=UTC)
        assert datetime.fromtimestamp(end, tz=UTC) == datetime(2026, 11, 11, 18, 29, 59, tzinfo=UTC)

    def test_format_ist_converts_from_utc(self):
        utc = datetime(2026, 11, 11, 17, 41, 46, tzinfo=UTC)
        assert format_ist(int(utc.timestamp())) == "11 Nov 2026, 23:11:46"


class TestDescribe:
    def test_upload_main_table(self):
        meta = json.dumps({"file_name": "oct.csv", "new": 2, "updated": 1, "unchanged": 5})
        assert describe("UPLOAD", meta) == "File oct.csv · 2 new, 1 updated, 5 unchanged"

    def test_upload_daily_sync(self):
        meta = json.dumps({"source": "branch_wise_monthly_target_upload", "file_name": "oct.csv"})
        assert describe("UPLOAD", meta) == "Daily targets regenerated · from oct.csv"

    def test_edit_with_key_change_and_partial_error(self):
        meta = json.dumps({"changed_cells": 3, "key_changes": 1})
        assert (
            describe("EDIT", meta, "daily insert failed")
            == "3 cell(s) changed · 1 key change(s) · ⚠️ daily insert failed"
        )

    def test_error_and_bad_metadata(self):
        assert describe("ERROR", "not json", "Insert failed") == "Insert failed"
        assert describe("LOGIN", "") == ""

    def test_table_label(self):
        assert table_label("branch_wise_monthly_target") == "Branch Wise Monthly Target"
        assert table_label("") == "—"
        assert table_label("something_else") == "something_else"


class TestStateDiff:
    KEYS = ("month", "branch_name", "series_group")

    def test_only_changed_cells_listed(self):
        before = [{"month": "2026-10-01T00:00:00", "branch_name": "A", "series_group": "RSL", "target_value1": 100.0}]
        after = [{"month": "2026-10-01", "branch_name": "A", "series_group": "RSL", "target_value1": 150}]
        assert state_diff(json.dumps(before), json.dumps(after), self.KEYS) == [
            {"Row": "2026-10-01 / A / RSL", "Column": "target_value1", "Old": 100.0, "New": 150}
        ]

    def test_key_change_listed_with_new_label(self):
        before = [{"month": "2026-10-01", "branch_name": "A", "series_group": "RSL", "target_value1": 1}]
        after = [{"month": "2026-10-01", "branch_name": "B", "series_group": "RSL", "target_value1": 1}]
        diff = state_diff(json.dumps(before), json.dumps(after), self.KEYS)
        assert diff == [{"Row": "2026-10-01 / B / RSL", "Column": "branch_name", "Old": "A", "New": "B"}]

    def test_missing_or_bad_states(self):
        assert state_diff("", "", self.KEYS) == []
        assert state_diff("oops", "[]", self.KEYS) == []


class TestHistoryWhere:
    def test_values_are_parameters(self):
        evil = "x' OR 1=1 --"
        sql, params = _history_where(1, 2, ["EDIT"], [evil], [])
        assert evil not in sql
        assert "user_email IN {user_email:Array(String)}" in sql
        assert "target_table" not in sql  # empty filter -> no condition
        assert params == {"start": 1, "end": 2, "action_type": ["EDIT"], "user_email": [evil]}
