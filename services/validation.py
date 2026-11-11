"""Normalising user-supplied rows before they reach the database."""

import io

import pandas as pd

from config import STRING_COLUMNS

NULL_TOKENS = ["NONE", "NAN", "<NA>", "NULL"]


def is_numeric_col(col: str) -> bool:
    return any(x in col.lower() for x in ("target", "incentive", "qty"))


def to_number(series: pd.Series) -> pd.Series:
    """Parse numbers that may carry rupee symbols / Indian thousands separators; bad values -> 0.0."""
    cleaned = series.astype(str).str.replace("₹", "", regex=False).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0).astype(float)


def clean_dataframe_for_db(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if col in STRING_COLUMNS:
            df[col] = df[col].fillna("").astype(str).str.strip().str.upper().replace(NULL_TOKENS, "")
        elif is_numeric_col(col):
            df[col] = to_number(df[col])
        elif df[col].dtype == "object":
            df[col] = df[col].fillna("").astype(str).str.strip().replace(NULL_TOKENS, "")
        else:
            df[col] = df[col].fillna(0)
    return df


def robust_read_csv(uploaded_file):
    """
    Robust CSV reader that handles:
    - Multiple encodings (utf-8, utf-8-sig, cp1252, latin1, iso-8859-1)
    - Non-breaking spaces (\xa0) and rogue characters
    - Variable delimiters (comma, semicolon, tab)
    - Inconsistent line terminators
    """
    raw_bytes = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()

    # Common encodings encountered in Excel exports and CSVs
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1", "iso-8859-1"]

    last_err = None
    for enc in encodings:
        try:
            text = raw_bytes.decode(enc)
            # Replace non-breaking spaces (\xa0) and unicode spaces with standard space
            text = text.replace("\xa0", " ")

            # Read via StringIO using Python engine with sep=None to sniff delimiter
            return pd.read_csv(io.StringIO(text), sep=None, engine="python")
        except Exception as e:
            last_err = e
            continue

    # Fallback with replacement of un-decodable bytes
    try:
        text = raw_bytes.decode("utf-8", errors="replace").replace("\xa0", " ")
        return pd.read_csv(io.StringIO(text), sep=None, engine="python")
    except Exception:
        raise (last_err or ValueError("Unable to parse CSV file.")) from None
