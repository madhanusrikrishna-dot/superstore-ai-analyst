"""
data.py - loads the Superstore CSV into an in-memory SQL database
and keeps the lists of allowed columns (so the AI can never invent a column).
"""

import re
import sqlite3

import pandas as pd

CSV_PATH = "Sample - Superstore.csv"

# columns you can split / group by
DIMENSIONS = ["region", "category", "sub_category", "segment", "state", "city", "ship_mode",
              "customer_name", "product_name"]

# columns you can filter by
FILTER_COLUMNS = ["region", "category", "sub_category", "segment", "state", "ship_mode"]

# metric name -> SQL expression
METRICS = {
    "sales": "SUM(sales)",
    "profit": "SUM(profit)",
    "quantity": "SUM(quantity)",
    "orders": "COUNT(DISTINCT order_id)",
    "customers": "COUNT(DISTINCT customer_id)",
    "margin": "SUM(profit) * 1.0 / SUM(sales)",
    "discount": "AVG(discount)",
    "aov": "SUM(sales) * 1.0 / COUNT(DISTINCT order_id)",
}

METRIC_LABELS = {
    "sales": "Sales", "profit": "Profit", "quantity": "Quantity", "orders": "Orders",
    "customers": "Customers", "margin": "Profit margin", "discount": "Average discount",
    "aov": "Average order value",
}

# metrics that can be added up (needed for share-of-total and forecasting)
ADDITIVE = {"sales", "profit", "quantity", "orders"}
RATIOS = {"margin", "discount"}

# row-level number columns (for correlation)
NUMBER_COLUMNS = ["sales", "profit", "quantity", "discount"]


def load(csv_path: str = CSV_PATH):
    df = pd.read_csv(csv_path, encoding="cp1252")
    df.columns = [c.strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]
    for col in ["order_date", "ship_date"]:
        df[col] = pd.to_datetime(df[col], format="%m/%d/%Y").dt.strftime("%Y-%m-%d")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    df.to_sql("superstore", conn, index=False)
    return conn, df


def normalize_filters(filters: dict, df: pd.DataFrame):
    """Match filter values to real values in the data (case-insensitive).
    Returns (clean_filters, warnings)."""
    clean, warnings = {}, []
    for key, value in (filters or {}).items():
        if value in (None, "", "all", "All", "none", "None"):
            continue
        value = str(value).strip()
        if key == "year":
            years = sorted(df["order_date"].str[:4].unique())
            # "2014-2017", "2014–2017", "all years" = the whole data: no filter, no warning
            found = re.findall(r"20\d\d", value)
            if not found or (len(found) >= 2 and found[0] <= years[0] and found[-1] >= years[-1]) \
                    or value.lower() in ("all years", "all time", "every year"):
                continue
            if len(found) >= 2:
                warnings.append(f"Year ranges like {value} aren't supported yet; showing all years "
                                f"({years[0]}–{years[-1]}). Ask about one year to filter.")
                continue
            value = found[0]
            if value in years:
                clean["year"] = value
            else:
                warnings.append(f"No data for year {value} (data covers {years[0]}–{years[-1]}). Year filter ignored.")
            continue
        if key not in FILTER_COLUMNS:
            continue
        real = {str(v).lower(): v for v in df[key].unique()}
        match = real.get(value.lower())
        if match is None:
            # try plural / partial match, e.g. "table" -> "Tables"
            candidates = [v for k, v in real.items() if value.lower() in k or k in value.lower()]
            match = candidates[0] if len(candidates) == 1 else None
        if match is None:
            warnings.append(f"'{value}' is not a known {key.replace('_', '-')}. Filter ignored.")
        else:
            clean[key] = match
    return clean, warnings


def find_filter_values(question: str, df: pd.DataFrame) -> dict:
    """Find region / category / sub-category / segment / state / ship mode / year values
    written in the question itself. Code does this (not the AI), so a value you type is never dropped.
    Longest names are matched first, so 'West Virginia' is a state, not the West region."""
    import re

    text = question.lower()
    found = {}
    candidates = []
    for col in ["state", "sub_category", "category", "segment", "region", "ship_mode"]:
        for v in df[col].dropna().unique():
            candidates.append((len(str(v)), col, str(v)))
    for _, col, v in sorted(candidates, reverse=True):
        pattern = r"\b" + re.escape(v.lower()) + r"\b"
        if col not in found and re.search(pattern, text):
            found[col] = v
            text = re.sub(pattern, " ", text)      # don't match the same words twice
    year = re.search(r"\b(201[4-7])\b", question)
    if year:
        found["year"] = year.group(1)
    return found


def where_clause(filters: dict, extra: str = ""):
    """Build a safe WHERE clause with ? placeholders."""
    parts, params = [], []
    for key, value in filters.items():
        if key == "year":
            parts.append("substr(order_date, 1, 4) = ?")
        else:
            parts.append(f"{key} = ?")
        params.append(value)
    if extra:
        parts.append(extra)
    return ("WHERE " + " AND ".join(parts)) if parts else "", params


def show_sql(sql: str, params: list) -> str:
    """SQL with the real values filled in, for display and copy-paste checking."""
    for p in params:
        sql = sql.replace("?", "'" + str(p).replace("'", "''") + "'", 1)
    return sql.strip()


def run(conn, sql: str, params: list) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)
