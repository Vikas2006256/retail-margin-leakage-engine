"""
=============================================================================
data_pipeline.py  —  MODULE 1: Data Profiling, Cleaning & Feature Engineering
=============================================================================
Project : Retail Margin & Inventory Leakage — A Last-Mile Decision Engine
Author  : Analytics Engineering Team
Version : 1.0.0
Python  : 3.10+

Description
-----------
This module is the entry point of the analytics pipeline. It ingests the raw
Superstore Sales dataset, performs defensive data cleaning, engineers business-
critical derived metrics, detects operational anomalies, and persists a
fully analytics-ready dataset to both CSV and a SQLite database for downstream
SQL processing and dashboarding.

Architecture Position
---------------------
  [Raw CSV]
      │
      ▼
  data_pipeline.py          ← YOU ARE HERE
      │
      ├── data/processed/superstore_clean.csv
      └── data/db/superstore.db  (table: orders)

Usage
-----
  python data_pipeline.py --input data/raw/superstore.csv
  python data_pipeline.py --input data/raw/superstore.csv --encoding utf-8 --verbose
=============================================================================
"""

# ---------------------------------------------------------------------------
# Standard Library Imports
# ---------------------------------------------------------------------------
import argparse
import logging
import os
import re
import sys
import warnings
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Third-Party Imports  (install via: pip install pandas numpy sqlalchemy)
# ---------------------------------------------------------------------------
try:
    import numpy as np
    import pandas as pd
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError
except ImportError as e:
    sys.exit(
        f"[FATAL] Missing dependency: {e}\n"
        "Run: pip install pandas numpy sqlalchemy\n"
    )

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# 0. CONFIGURATION & CONSTANTS
# ---------------------------------------------------------------------------

# Default filesystem paths (override via CLI args)
DEFAULT_RAW_PATH       = Path("data/raw/superstore.csv")
DEFAULT_CLEAN_CSV_PATH = Path("data/processed/superstore_clean.csv")
DEFAULT_DB_PATH        = Path("data/db/superstore.db")
DB_TABLE_NAME          = "orders"

# Encoding fallback chain — tried in order until one succeeds
ENCODING_FALLBACKS = ["utf-8", "latin1", "cp1252", "iso-8859-1"]

# Columns expected in the raw Superstore dataset (case-insensitive check)
REQUIRED_COLUMNS = {
    "Order ID", "Order Date", "Ship Date", "Ship Mode",
    "Customer ID", "Customer Name", "Segment", "Country",
    "City", "State", "Postal Code", "Region",
    "Product ID", "Category", "Sub-Category", "Product Name",
    "Sales", "Quantity", "Discount", "Profit",
}

# ---------------------------------------------------------------------------
# 1. LOGGING SETUP
# ---------------------------------------------------------------------------

def configure_logging(verbose: bool = False) -> logging.Logger:
    """
    Configure a named logger with console (and optionally file) handlers.
    Using a named logger (not root) prevents interference with library logs.
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("data_pipeline")
    logger.setLevel(log_level)

    if not logger.handlers:
        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(log_level)
        fmt = logging.Formatter(
            fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        ch.setFormatter(fmt)
        logger.addHandler(ch)

        # File handler — persists run logs alongside processed output
        log_dir = Path("data/processed")
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "pipeline_run.log", mode="a", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# 2. DATA INGESTION  — encoding-safe CSV loading
# ---------------------------------------------------------------------------

def load_raw_data(
    filepath: Path,
    encoding: str | None = None,
    logger: logging.Logger = None,
) -> pd.DataFrame:
    """
    Load a CSV file with automatic encoding detection.

    Encoding Strategy
    -----------------
    Superstore datasets downloaded from Kaggle / Tableau often ship as
    'latin1' (Windows-1252) despite appearing UTF-8 compatible. We attempt
    the caller-supplied encoding first, then fall back through a priority chain.

    Parameters
    ----------
    filepath : Path
        Absolute or relative path to the raw CSV file.
    encoding : str | None
        Preferred encoding. If None, the fallback chain is tried from index 0.
    logger   : logging.Logger

    Returns
    -------
    pd.DataFrame
        Raw dataframe exactly as read from disk — no transformations applied.

    Raises
    ------
    FileNotFoundError  : If filepath does not exist.
    ValueError         : If all encodings in the fallback chain fail.
    """
    if not filepath.exists():
        raise FileNotFoundError(
            f"Raw dataset not found at '{filepath}'.\n"
            "Place the Superstore CSV at data/raw/superstore.csv or pass --input <path>."
        )

    attempts = [encoding] + [e for e in ENCODING_FALLBACKS if e != encoding] if encoding else ENCODING_FALLBACKS

    for enc in attempts:
        try:
            df = pd.read_csv(filepath, encoding=enc, low_memory=False)
            logger.info(f"Loaded '{filepath.name}' using encoding='{enc}' | Shape: {df.shape}")
            return df
        except (UnicodeDecodeError, LookupError):
            logger.debug(f"Encoding '{enc}' failed — trying next fallback...")
            continue

    raise ValueError(
        f"All encoding attempts failed for '{filepath}'.\n"
        f"Tried: {attempts}\nTry passing --encoding <codec> explicitly."
    )


# ---------------------------------------------------------------------------
# 3. COLUMN NORMALIZATION  — snake_case SQL-friendly headers
# ---------------------------------------------------------------------------

def _to_snake(col: str) -> str:
    """Convert a single column name to snake_case."""
    col = col.strip()
    col = re.sub(r"[\s\-/]+", "_", col)
    col = re.sub(r"[^\w]", "", col)
    col = re.sub(r"_+", "_", col)
    return col.lower()


def normalize_column_names(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """
    Convert raw column headers to lowercase, SQL-compatible snake_case.

    Transformation examples
    -----------------------
    'Order ID'     -> 'order_id'
    'Sub-Category' -> 'sub_category'
    'Ship Mode'    -> 'ship_mode'
    'Postal Code'  -> 'postal_code'
    """
    original_cols = df.columns.tolist()
    df.columns = [_to_snake(c) for c in original_cols]

    renamed = {o: n for o, n in zip(original_cols, df.columns.tolist()) if o != n}
    logger.info(f"Normalized {len(renamed)} column headers to snake_case.")
    logger.debug(f"Renamed columns: {renamed}")

    return df


# ---------------------------------------------------------------------------
# 4. SCHEMA VALIDATION
# ---------------------------------------------------------------------------

def validate_schema(df: pd.DataFrame, logger: logging.Logger) -> None:
    """
    Confirm that all business-critical columns are present after normalization.

    Raises
    ------
    KeyError : If one or more required columns are missing.
    """
    required_snake = {_to_snake(c) for c in REQUIRED_COLUMNS}
    actual_cols    = set(df.columns)
    missing        = required_snake - actual_cols

    if missing:
        raise KeyError(
            f"Schema validation FAILED — {len(missing)} required column(s) missing:\n"
            f"  Missing : {sorted(missing)}\n"
            f"  Present : {sorted(actual_cols)}"
        )

    logger.info("Schema validation PASSED — all required columns present.")


# ---------------------------------------------------------------------------
# 5. DATA QUALITY CLEANING
# ---------------------------------------------------------------------------

def clean_data(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """
    Apply a layered data quality cleaning pipeline.

    Steps (in order)
    ----------------
    5a. Duplicate removal     — drop fully duplicated rows
    5b. Datetime parsing      — coerce order_date & ship_date with error isolation
    5c. Numeric coercion      — ensure sales, profit, discount are float64
    5d. Missing value handling — targeted imputation & row removal
    5e. Domain constraint enforcement — clip discount to [0, 1], sales > 0
    """
    initial_rows = len(df)
    logger.info(f"Cleaning pipeline started | Input rows: {initial_rows:,}")

    # -- 5a. Duplicate Removal -----------------------------------------------
    # Use the business key (order_id + product_id) rather than full row
    # equality to catch partial duplicates that carry different timestamps.
    business_key = ["order_id", "product_id"]
    key_cols_present = all(c in df.columns for c in business_key)

    if key_cols_present:
        dupes_bk = df.duplicated(subset=business_key).sum()
        df = df.drop_duplicates(subset=business_key, keep="first")
        logger.info(f"Removed {dupes_bk:,} business-key duplicates (order_id + product_id).")
    else:
        dupes_full = df.duplicated().sum()
        df = df.drop_duplicates()
        logger.info(f"Removed {dupes_full:,} fully-duplicated rows (business key not found).")

    # -- 5b. Datetime Parsing ------------------------------------------------
    # Superstore dates are typically 'MM/DD/YYYY' or 'YYYY-MM-DD'.
    # Using infer_datetime_format is removed in Pandas 2.x; we rely on
    # dayfirst=False and errors='coerce' to safely handle parse failures.
    for date_col in ["order_date", "ship_date"]:
        if date_col not in df.columns:
            logger.warning(f"Date column '{date_col}' not found — skipping.")
            continue

        parsed = pd.to_datetime(df[date_col], errors="coerce", dayfirst=False)
        failed_count = parsed.isna().sum()

        if failed_count > 0:
            logger.warning(
                f"'{date_col}': {failed_count:,} values could not be parsed "
                "and will be set to NaT."
            )

        df[date_col] = parsed
        logger.info(
            f"Parsed '{date_col}' -> dtype={df[date_col].dtype} | "
            f"Range: {df[date_col].min().date()} -> {df[date_col].max().date()}"
        )

    # Drop rows where either date is unparseable
    before_date_drop = len(df)
    df = df.dropna(subset=["order_date", "ship_date"])
    date_dropped = before_date_drop - len(df)
    if date_dropped:
        logger.warning(f"Dropped {date_dropped:,} rows with unparseable dates.")

    # -- 5c. Numeric Coercion ------------------------------------------------
    numeric_cols = {"sales": 0.0, "profit": 0.0, "discount": 0.0, "quantity": 1}
    for col, fill_val in numeric_cols.items():
        if col in df.columns:
            original_dtype = df[col].dtype
            df[col] = pd.to_numeric(df[col], errors="coerce")
            coerce_count = df[col].isna().sum()
            if coerce_count:
                logger.warning(
                    f"'{col}': {coerce_count:,} non-numeric values coerced to NaN "
                    f"(original dtype: {original_dtype}) — filling with {fill_val}."
                )
            df[col] = df[col].fillna(fill_val)

    # -- 5d. Missing Value Handling ------------------------------------------
    categorical_cols = [
        "ship_mode", "segment", "country", "city", "state",
        "region", "category", "sub_category", "product_name",
    ]
    for col in categorical_cols:
        if col in df.columns:
            missing = df[col].isna().sum()
            if missing:
                df[col] = df[col].fillna("Unknown")
                logger.debug(f"Filled {missing:,} NaN in '{col}' with 'Unknown'.")

    if "postal_code" in df.columns:
        df["postal_code"] = df["postal_code"].astype(str).str.zfill(5).replace("nan", "00000")

    # -- 5e. Domain Constraint Enforcement -----------------------------------
    if "discount" in df.columns:
        # Some datasets encode discount as percentage (e.g., 30 instead of 0.30)
        if df["discount"].max() > 1.0:
            logger.warning(
                "Discount values > 1 detected — converting from percentage to decimal."
            )
            df["discount"] = df["discount"] / 100.0

        out_of_range = ((df["discount"] < 0) | (df["discount"] > 1)).sum()
        if out_of_range:
            logger.warning(f"Clipping {out_of_range:,} discount values to [0, 1].")
        df["discount"] = df["discount"].clip(0.0, 1.0)

    if "sales" in df.columns:
        invalid_sales = (df["sales"] <= 0).sum()
        if invalid_sales:
            logger.warning(
                f"{invalid_sales:,} rows with Sales <= 0 detected — flagged "
                "but retained for anomaly analysis."
            )

    final_rows = len(df)
    logger.info(
        f"Cleaning pipeline complete | "
        f"Output rows: {final_rows:,} | "
        f"Dropped: {initial_rows - final_rows:,} "
        f"({(initial_rows - final_rows) / initial_rows * 100:.1f}%)"
    )
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 6. FEATURE ENGINEERING  — derived business & operational metrics
# ---------------------------------------------------------------------------

def engineer_features(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """
    Compute all derived business metrics required for downstream analytics.

    Metric Definitions
    ------------------
    profit_margin_pct      = (Profit / Sales) * 100
    shipping_duration_days = Ship Date - Order Date (calendar days)
    original_list_price    = Sales / (1 - Discount)
    discount_loss_amount   = original_list_price - Sales
    discount_impact_factor = Discount / (Sales + Profit)
    """
    logger.info("Engineering derived features...")

    for col in ["sales", "profit", "discount"]:
        if col not in df.columns:
            raise KeyError(f"Feature engineering requires column '{col}' — not found.")

    # -- 6a. Profit Margin % -------------------------------------------------
    # Protect against division by zero: rows with Sales=0 get NaN -> filled 0
    df["profit_margin_pct"] = np.where(
        df["sales"] != 0,
        (df["profit"] / df["sales"]) * 100,
        np.nan,
    )
    df["profit_margin_pct"] = df["profit_margin_pct"].round(4)
    logger.debug(
        f"profit_margin_pct | mean={df['profit_margin_pct'].mean():.2f}% | "
        f"min={df['profit_margin_pct'].min():.2f}% | "
        f"max={df['profit_margin_pct'].max():.2f}%"
    )

    # -- 6b. Shipping Duration (days) ----------------------------------------
    df["shipping_duration_days"] = (df["ship_date"] - df["order_date"]).dt.days

    # Negative durations indicate bad data (ship before order) — cap at 0
    negative_ship = (df["shipping_duration_days"] < 0).sum()
    if negative_ship:
        logger.warning(
            f"{negative_ship:,} rows have Ship Date < Order Date "
            "(data quality issue) — clamped to 0."
        )
        df["shipping_duration_days"] = df["shipping_duration_days"].clip(lower=0)

    # -- 6c. Original List Price ---------------------------------------------
    # When Discount = 1.0 the item was free; list price is undefined -> NaN
    denominator = 1.0 - df["discount"]
    df["original_list_price"] = np.where(
        denominator > 0,
        df["sales"] / denominator,
        np.nan,
    )
    df["original_list_price"] = df["original_list_price"].fillna(df["sales"]).round(4)

    # -- 6d. Discount Loss Amount --------------------------------------------
    df["discount_loss_amount"] = (df["original_list_price"] - df["sales"]).round(4)

    # -- 6e. Discount Impact Factor ------------------------------------------
    # Factor close to 0 = discount negligible; close to 1 = discount dominates
    value_base = df["sales"] + df["profit"]
    df["discount_impact_factor"] = np.where(
        value_base != 0,
        df["discount"] / value_base,
        np.nan,
    )
    df["discount_impact_factor"] = df["discount_impact_factor"].round(6)

    # -- 6f. Time Dimension Columns ------------------------------------------
    if "order_date" in df.columns:
        df["order_year"]    = df["order_date"].dt.year
        df["order_month"]   = df["order_date"].dt.month
        df["order_quarter"] = df["order_date"].dt.quarter
        df["order_week"]    = df["order_date"].dt.isocalendar().week.astype(int)

    logger.info(
        "Feature engineering complete. New columns: "
        "profit_margin_pct, shipping_duration_days, original_list_price, "
        "discount_loss_amount, discount_impact_factor, "
        "order_year, order_month, order_quarter, order_week"
    )
    return df


# ---------------------------------------------------------------------------
# 7. ANOMALY DETECTION & FLAGGING
# ---------------------------------------------------------------------------

def detect_anomalies(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """
    Apply rule-based operational anomaly detection and emit flag columns.

    Each anomaly rule creates a binary integer column (0/1) that can be:
      - Used in SQL WHERE clauses for targeted reporting
      - Fed into alert_engine.py for multi-variable risk scoring
      - Used in Power BI / Tableau conditional formatting

    Anomaly Rules
    -------------
    HIGH_DISCOUNT_FLAG   : Discount >= 50%  — potential pricing control failure
    MARGIN_BLEED_FLAG    : Profit Margin <= -20%  — severe margin destruction
    ZERO_SALES_FLAG      : Sales = 0  — data entry error or free-goods
    NEGATIVE_PROFIT_FLAG : Profit < 0  — any loss-making transaction
    LONG_SHIPPING_FLAG   : Shipping > 7 days  — fulfillment SLA breach
    """
    logger.info("Running anomaly detection...")

    df["high_discount_flag"]   = (df["discount"] >= 0.50).astype(int)
    df["margin_bleed_flag"]    = (df["profit_margin_pct"] <= -20.0).astype(int)
    df["zero_sales_flag"]      = (df["sales"] <= 0).astype(int)
    df["negative_profit_flag"] = (df["profit"] < 0).astype(int)

    if "shipping_duration_days" in df.columns:
        df["long_shipping_flag"] = (df["shipping_duration_days"] > 7).astype(int)
    else:
        df["long_shipping_flag"] = 0

    # Composite anomaly count per row
    flag_cols = [
        "high_discount_flag", "margin_bleed_flag",
        "zero_sales_flag", "negative_profit_flag", "long_shipping_flag",
    ]
    df["anomaly_count"] = df[flag_cols].sum(axis=1)

    for flag in flag_cols:
        count = df[flag].sum()
        pct   = count / len(df) * 100
        logger.info(f"  {flag:<28}: {count:>6,} rows ({pct:5.2f}%)")

    multi_anomaly = (df["anomaly_count"] >= 2).sum()
    logger.warning(
        f"  Multi-anomaly rows (>=2 flags)  : {multi_anomaly:>6,} rows "
        "— HIGH PRIORITY for alert engine."
    )

    return df


# ---------------------------------------------------------------------------
# 8. DATA PROFILING REPORT
# ---------------------------------------------------------------------------

def generate_profile_report(df: pd.DataFrame, logger: logging.Logger) -> None:
    """
    Print a concise data quality summary to the log for pipeline auditability.
    Lightweight replacement for heavy profiling libraries (pandas-profiling).
    """
    logger.info("=" * 60)
    logger.info("DATA PROFILE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total Rows         : {len(df):,}")
    logger.info(f"  Total Columns      : {len(df.columns)}")
    logger.info(f"  Memory Usage       : {df.memory_usage(deep=True).sum() / 1e6:.2f} MB")
    logger.info(f"  Date Range         : {df['order_date'].min().date()} -> {df['order_date'].max().date()}")

    null_summary = df.isnull().sum()
    null_cols    = null_summary[null_summary > 0]
    if null_cols.empty:
        logger.info("  Null Values        : None detected")
    else:
        logger.warning(f"  Null Values        : {len(null_cols)} columns contain nulls")
        for col, count in null_cols.items():
            logger.warning(f"    - {col}: {count:,} nulls")

    key_metrics = ["sales", "profit", "discount", "profit_margin_pct", "shipping_duration_days"]
    key_metrics = [m for m in key_metrics if m in df.columns]
    logger.info("\n  Key Metric Statistics:")
    logger.info(f"  {'Metric':<30} {'Min':>10} {'Mean':>10} {'Median':>10} {'Max':>10}")
    logger.info(f"  {'-' * 72}")
    for metric in key_metrics:
        logger.info(
            f"  {metric:<30} "
            f"{df[metric].min():>10.2f} "
            f"{df[metric].mean():>10.2f} "
            f"{df[metric].median():>10.2f} "
            f"{df[metric].max():>10.2f}"
        )
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# 9. EXPORT: Sanitized CSV
# ---------------------------------------------------------------------------

def export_csv(df: pd.DataFrame, output_path: Path, logger: logging.Logger) -> None:
    """
    Export the analytics-ready DataFrame to CSV.

    Export decisions
    ----------------
    index=False    : Prevents unnamed index column in downstream tools.
    utf-8-sig      : BOM prefix ensures Excel opens without encoding dialog.
    date_format    : ISO 8601 standard for cross-tool compatibility.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df_export = df.copy()
    for col in ["order_date", "ship_date"]:
        if col in df_export.columns:
            df_export[col] = df_export[col].dt.strftime("%Y-%m-%d")

    df_export.to_csv(output_path, index=False, encoding="utf-8-sig")
    file_size_kb = output_path.stat().st_size / 1024
    logger.info(
        f"Exported cleaned CSV -> '{output_path}' "
        f"| {len(df_export):,} rows | {file_size_kb:.1f} KB"
    )


# ---------------------------------------------------------------------------
# 10. EXPORT: SQLite Database
# ---------------------------------------------------------------------------

def export_sqlite(df: pd.DataFrame, db_path: Path, logger: logging.Logger) -> None:
    """
    Persist the analytics-ready DataFrame to a SQLite database table.

    The 'orders' table schema mirrors a production OLAP table structure,
    enabling SQL queries in Module 2 to run without modification against
    both SQLite (local dev) and PostgreSQL/BigQuery (production).

    if_exists='replace' ensures the pipeline is fully idempotent (re-runnable).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")

    df_db = df.copy()
    for col in ["order_date", "ship_date"]:
        if col in df_db.columns:
            df_db[col] = df_db[col].dt.strftime("%Y-%m-%d")

    try:
        df_db.to_sql(
            name      = DB_TABLE_NAME,
            con       = engine,
            if_exists = "replace",
            index     = False,
            method    = "multi",   # Batch insert — faster for large datasets
            # SQLite SQLITE_MAX_VARIABLE_NUMBER = 999
            # chunksize = floor(999 / num_columns) to stay within limit
            chunksize = max(1, 999 // len(df_db.columns)),
        )

        with engine.connect() as conn:
            result    = conn.execute(text(f"SELECT COUNT(*) FROM {DB_TABLE_NAME}"))
            row_count = result.scalar()

        logger.info(
            f"Exported to SQLite -> '{db_path}' | "
            f"Table: '{DB_TABLE_NAME}' | {row_count:,} rows"
        )

    except SQLAlchemyError as e:
        logger.error(f"SQLite export FAILED: {e}")
        raise


# ---------------------------------------------------------------------------
# 11. PIPELINE ORCHESTRATOR
# ---------------------------------------------------------------------------

def run_pipeline(
    input_path : Path,
    output_csv : Path,
    output_db  : Path,
    encoding   : str | None,
    verbose    : bool,
) -> pd.DataFrame:
    """
    Master orchestration function. Calls each module stage in sequence.

    Pipeline Stages
    ---------------
    1. Load raw data (encoding-safe)
    2. Normalize column headers to snake_case
    3. Validate schema against REQUIRED_COLUMNS
    4. Clean data quality issues
    5. Engineer derived business features
    6. Detect and flag operational anomalies
    7. Generate profile report
    8. Export sanitized CSV
    9. Export SQLite database

    Returns
    -------
    pd.DataFrame — fully processed, flag-enriched dataset.
    """
    logger = configure_logging(verbose=verbose)
    run_start = datetime.now()

    logger.info("=" * 60)
    logger.info("RETAIL MARGIN & INVENTORY LEAKAGE — DATA PIPELINE v1.0")
    logger.info("=" * 60)
    logger.info(f"Run started : {run_start.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Input file  : {input_path}")
    logger.info(f"Output CSV  : {output_csv}")
    logger.info(f"Output DB   : {output_db}")

    df = load_raw_data(input_path, encoding=encoding, logger=logger)
    df = normalize_column_names(df, logger)
    validate_schema(df, logger)
    df = clean_data(df, logger)
    df = engineer_features(df, logger)
    df = detect_anomalies(df, logger)
    generate_profile_report(df, logger)
    export_csv(df, output_csv, logger)
    export_sqlite(df, output_db, logger)

    elapsed = (datetime.now() - run_start).total_seconds()
    logger.info(f"Pipeline completed successfully in {elapsed:.2f}s")
    logger.info("=" * 60)

    return df


# ---------------------------------------------------------------------------
# 12. CLI ENTRY POINT
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Define and parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="data_pipeline.py",
        description=(
            "Retail Margin & Inventory Leakage — Module 1: "
            "Data Cleaning & Feature Engineering Pipeline"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python data_pipeline.py
  python data_pipeline.py --input data/raw/superstore.csv
  python data_pipeline.py --input data/raw/superstore.csv --encoding latin1
  python data_pipeline.py --input data/raw/superstore.csv --verbose
        """,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=DEFAULT_RAW_PATH,
        help="Path to raw Superstore CSV (default: data/raw/superstore.csv)",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_CLEAN_CSV_PATH,
        help="Path for cleaned CSV output",
    )
    parser.add_argument(
        "--output-db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path for SQLite database output",
    )
    parser.add_argument(
        "--encoding", "-e",
        type=str,
        default=None,
        help="Preferred CSV encoding (default: auto-detect from fallback chain)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging for detailed diagnostics",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    try:
        final_df = run_pipeline(
            input_path = args.input,
            output_csv = args.output_csv,
            output_db  = args.output_db,
            encoding   = args.encoding,
            verbose    = args.verbose,
        )

        print("\n" + "=" * 60)
        print("  PIPELINE SUMMARY")
        print("=" * 60)
        print(f"  Rows processed     : {len(final_df):,}")
        print(f"  Columns            : {len(final_df.columns)}")
        print(f"  High-discount rows : {final_df['high_discount_flag'].sum():,}")
        print(f"  Margin bleed rows  : {final_df['margin_bleed_flag'].sum():,}")
        print(f"  Negative profit    : {final_df['negative_profit_flag'].sum():,}")
        print(f"  Clean CSV          : {args.output_csv}")
        print(f"  SQLite DB          : {args.output_db}")
        print("=" * 60 + "\n")

    except (FileNotFoundError, KeyError, ValueError) as exc:
        logging.getLogger("data_pipeline").error(f"Pipeline ABORTED: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[CANCELLED] Pipeline interrupted by user.")
        sys.exit(0)
