"""Per-table cache invalidation: a write refetches only the table it touched."""

import pandas as pd
import pytest

from db import repository as db

MONTHLY = "branch_wise_monthly_target"
DAILY = "date_branch_wise_target"


class FakeResult:
    column_names = ["branch_name"]
    result_rows = [("A",)]


class FakeClient:
    def __init__(self):
        self.queries: list[str] = []

    def query(self, query, parameters=None):
        self.queries.append(query)
        return FakeResult()

    def command(self, query, parameters=None, settings=None):
        self.queries.append(query)

    def count(self, table):
        return sum(f"FROM {table} " in q for q in self.queries)


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(db, "get_client", lambda: fake)
    db._fetch_data.clear()
    db._versions().clear()
    yield fake
    db._fetch_data.clear()


def test_reads_are_cached(client):
    db.fetch_data(MONTHLY)
    db.fetch_data(MONTHLY)
    assert client.count(MONTHLY) == 1


def test_invalidate_refetches_only_that_table(client):
    db.fetch_data(MONTHLY)
    db.fetch_data(DAILY)
    db.invalidate(MONTHLY)
    db.fetch_data(MONTHLY)
    db.fetch_data(DAILY)
    assert client.count(MONTHLY) == 2
    assert client.count(DAILY) == 1


def test_deactivate_daily_invalidates_daily_table(client):
    before = db.data_version(DAILY)
    db.deactivate_daily_for_months([{"month": "2026-10-01", "branch_name": "A", "series_group": "RSL"}])
    assert db.data_version(DAILY) == before + 1
    assert db.data_version(MONTHLY) == 0


def test_deactivate_keys_invalidates_its_table(client):
    db.deactivate_keys(MONTHLY, [{"month": "2026-10-01", "branch_name": "A", "series_group": "RSL"}])
    assert db.data_version(MONTHLY) == 1


def test_paging_uses_offset_parameter(client):
    db.fetch_data(MONTHLY, limit=200, offset=400)
    assert "OFFSET {offset:UInt32}" in client.queries[-1]
    df = db.fetch_data(MONTHLY, limit=200, offset=400)
    assert isinstance(df, pd.DataFrame)
    assert len(client.queries) == 1  # same page -> cached


class TestPageWindow:
    def test_first_page(self):
        from views.dashboard import page_window

        assert page_window(22_869, 200, 1) == (1, 115, 0)

    def test_last_page_and_clamping(self):
        from views.dashboard import page_window

        assert page_window(22_869, 200, 115) == (115, 115, 22_800)
        assert page_window(22_869, 200, 999) == (115, 115, 22_800)
        assert page_window(22_869, 200, 0) == (1, 115, 0)

    def test_exact_multiple_and_empty(self):
        from views.dashboard import page_window

        assert page_window(400, 200, 2) == (2, 2, 200)
        assert page_window(0, 200, 3) == (1, 1, 0)
