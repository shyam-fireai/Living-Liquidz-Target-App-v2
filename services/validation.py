"""Normalising user-supplied rows before they reach the database."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from config import STRING_COLUMNS, TableConfig

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
    Robust CSV reader. Every cell is returned as text (validation parses it), so codes such as
    "007" keep their leading zeros. Handles:
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
            return pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, keep_default_na=False)
        except Exception as e:
            last_err = e
            continue

    # Fallback with replacement of un-decodable bytes
    try:
        text = raw_bytes.decode("utf-8", errors="replace").replace("\xa0", " ")
        return pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, keep_default_na=False)
    except Exception:
        raise (last_err or ValueError("Unable to parse CSV file.")) from None


# -------------------------------
# UPLOAD VALIDATION
# -------------------------------
MAX_VALUE = 99_999_999.99  # Decimal(10, 2) in ClickHouse
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")  # ISO, or Indian day-first
ERROR, WARNING = "error", "warning"


@dataclass
class Issue:
    row: int | None  # spreadsheet row number (header = row 1); None = whole file
    column: str
    value: str
    problem: str
    severity: str = ERROR


@dataclass
class UploadCheck:
    rows: pd.DataFrame  # cleaned, typed rows (only meaningful when there are no errors)
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    def issues_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Row": i.row if i.row is not None else "-",
                    "Column": i.column,
                    "Value": i.value,
                    "Problem": i.problem,
                    "Severity": i.severity.title(),
                }
                for i in sorted(self.issues, key=lambda i: (i.severity != ERROR, i.row or 0, i.column))
            ]
        )


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().replace("\xa0", " ").lower() for c in df.columns]
    return df


def _is_blank(value) -> bool:
    return (
        value is None
        or (isinstance(value, float) and pd.isna(value))
        or str(value).strip().upper() in ("", *NULL_TOKENS)
    )


def parse_date(value):
    """Return a Timestamp for ISO (2026-03-01) or day-first (01-03-2026, 01/03/2026) dates, else None."""
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).normalize()
    text = str(value).strip().split(" ")[0].split("T")[0]
    for fmt in DATE_FORMATS:
        try:
            return pd.Timestamp(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None


def parse_number(value):
    """Blank -> 0.0; '₹1,00,000.50' -> 100000.5; anything else non-numeric -> None."""
    if _is_blank(value):
        return 0.0
    try:
        return float(str(value).replace("₹", "").replace(",", "").strip())
    except ValueError:
        return None


def validate_upload(
    raw: pd.DataFrame,
    cfg: TableConfig,
    known_values: dict[str, set[str]] | None = None,
) -> UploadCheck:
    """Check every row of an uploaded file and report all problems at once.

    known_values: e.g. {"branch_name": {...}} - values not in the set give a *warning*
    (a new branch may be legitimate), everything else is an *error* that blocks the upload.
    """
    df = normalize_columns(raw)
    issues: list[Issue] = []

    missing = [c for c in cfg.columns if c not in df.columns]
    if missing:
        issues.append(Issue(None, ", ".join(missing), "", "Required column(s) missing from the file"))
        return UploadCheck(rows=pd.DataFrame(columns=list(cfg.columns)), issues=issues)
    extra = [c for c in df.columns if c not in cfg.columns and not c.startswith("unnamed")]
    if extra:
        issues.append(Issue(None, ", ".join(extra), "", "Unknown column(s) will be ignored", WARNING))
    if df.empty:
        issues.append(Issue(None, "", "", "The file has no data rows"))
        return UploadCheck(rows=pd.DataFrame(columns=list(cfg.columns)), issues=issues)

    clean_rows = []
    for idx, row in df[list(cfg.columns)].iterrows():
        line = int(idx) + 2
        rec = {}
        for col in cfg.key_cols:
            value = row[col]
            if col == cfg.date_col:
                parsed = None if _is_blank(value) else parse_date(value)
                if parsed is None:
                    problem = "Missing date" if _is_blank(value) else "Not a valid date (use YYYY-MM-DD)"
                    issues.append(Issue(line, col, "" if _is_blank(value) else str(value), problem))
                elif col == "month" and parsed.day != 1:
                    issues.append(Issue(line, col, str(value), "Month must be the 1st day of the month"))
                rec[col] = parsed
            else:
                if _is_blank(value):
                    issues.append(Issue(line, col, "", "Missing value"))
                    rec[col] = ""
                else:
                    rec[col] = str(value).strip().upper()
                    known = (known_values or {}).get(col)
                    if known and rec[col] not in known:
                        issues.append(Issue(line, col, rec[col], "Not found in existing data (new?)", WARNING))
        for col in cfg.value_cols:
            number = parse_number(row[col])
            if number is None:
                issues.append(Issue(line, col, str(row[col]), "Not a number"))
                number = 0.0
            elif number < 0:
                issues.append(Issue(line, col, str(row[col]), "Negative value"))
            elif number > MAX_VALUE:
                issues.append(Issue(line, col, str(row[col]), "Too large (max 9,99,99,999.99)"))
            rec[col] = round(number, 2)
        rec["_row"] = line
        clean_rows.append(rec)

    rows = pd.DataFrame(clean_rows)
    # Duplicate keys inside the file: the last one would silently win, so make the user choose.
    complete = rows.dropna(subset=list(cfg.key_cols))
    dup_mask = complete.duplicated(subset=list(cfg.key_cols), keep=False)
    for _, group in complete[dup_mask].groupby(list(cfg.key_cols), sort=False):
        lines = group["_row"].tolist()
        label = " / ".join(
            str(v.date() if isinstance(v, pd.Timestamp) else v) for v in group.iloc[0][list(cfg.key_cols)]
        )
        for line in lines:
            others = ", ".join(str(n) for n in lines if n != line)
            issues.append(Issue(line, "key", label, f"Duplicate of row {others}"))

    return UploadCheck(rows=rows, issues=issues)
