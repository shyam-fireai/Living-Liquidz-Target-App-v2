import io

import pandas as pd

from services.validation import clean_dataframe_for_db, robust_read_csv

BOM = chr(0xFEFF)
NBSP = chr(0xA0)
E_UMLAUT = chr(0xCB)  # cp1252 byte 0xCB; followed by an ASCII byte it is invalid UTF-8


class TestRobustReadCsv:
    def test_utf8_comma(self):
        df = robust_read_csv(io.BytesIO(b"branch_name,target_value1\nA,100\nB,200\n"))
        assert df.columns.tolist() == ["branch_name", "target_value1"]
        assert df["target_value1"].tolist() == ["100", "200"]  # cells stay text; validation parses them

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


class TestCleanDataframeForDb:
    def test_strings_upper_stripped_and_null_tokens_blank(self):
        df = pd.DataFrame({"branch_name": ["  mumbai ", None, "nan"], "series_group": ["a", "b", "NULL"]})
        out = clean_dataframe_for_db(df)
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
        out = clean_dataframe_for_db(df)
        assert out["target_value1"].tolist() == [123456.5, 0.0, 0.0]
        assert out["incentive_value1"].tolist() == [10.0, 2000.0, 0.0]
        assert out["target_qty1"].tolist() == [5.0, 6.0, 0.0]

    def test_input_not_mutated(self):
        df = pd.DataFrame({"branch_name": [" a "]})
        clean_dataframe_for_db(df)
        assert df.loc[0, "branch_name"] == " a "
