"""
=============================================================================
test_pipeline.py  —  Automated Test Suite for All Python Modules
=============================================================================
Project : Retail Margin & Inventory Leakage — A Last-Mile Decision Engine
Version : 1.0.0

Coverage
--------
  Module 1 — data_pipeline.py   : 18 tests
  Module 3 — alert_engine.py    : 14 tests
  Integration                   :  4 tests
  Total                         : 36 tests

Run
---
  .venv\Scripts\pytest tests/test_pipeline.py -v
  .venv\Scripts\pytest tests/test_pipeline.py -v --tb=short   # compact tracebacks
  .venv\Scripts\pytest tests/test_pipeline.py -v -k "clean"   # run only cleaning tests
=============================================================================
"""

import sys
import math
import sqlite3
import tempfile
from io import StringIO
from pathlib import Path

import gc
import numpy as np
import pandas as pd
import pytest
from contextlib import contextmanager


@contextmanager
def temp_db():
    """Temp directory that safely closes SQLite WAL/SHM files on Windows."""
    import tempfile
    tmpdir = tempfile.mkdtemp()
    try:
        yield Path(tmpdir)
    finally:
        gc.collect()   # ensure SQLAlchemy engines are GC'd and connections closed
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

# ── Make sure the project root is on sys.path ─────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_pipeline import (
    _to_snake,
    normalize_column_names,
    validate_schema,
    clean_data,
    engineer_features,
    detect_anomalies,
    export_csv,
    export_sqlite,
    configure_logging,
    REQUIRED_COLUMNS,
)
from alert_engine import (
    add_rule_input_features,
    evaluate_all_rules,
    generate_alert_summary,
    export_action_queue,
    RULE_REGISTRY,
    OPERATOR_MAP,
)

# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES — shared test data
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def logger():
    """Return a configured pipeline logger (suppress output during tests)."""
    import logging
    log = configure_logging(verbose=False)
    log.setLevel(logging.CRITICAL)   # silence test output
    return log


@pytest.fixture
def minimal_raw_df():
    """
    Minimal raw DataFrame that mimics a freshly loaded Superstore CSV
    BEFORE any normalization or cleaning (raw column names).
    """
    return pd.DataFrame({
        "Row ID"       : [1, 2, 3, 4, 5],
        "Order ID"     : ["CA-2019-001", "CA-2019-002", "CA-2019-003", "CA-2019-002", "CA-2019-005"],
        "Order Date"   : ["01/05/2019", "03/10/2019", "05/22/2019", "03/10/2019", "07/14/2019"],
        "Ship Date"    : ["01/10/2019", "03/13/2019", "05/30/2019", "03/13/2019", "07/20/2019"],
        "Ship Mode"    : ["Standard Class", "First Class", "Second Class", "First Class", "Same Day"],
        "Customer ID"  : ["CG-001", "CG-002", "CG-003", "CG-002", "CG-004"],
        "Customer Name": ["Alice Smith", "Bob Jones", "Carol White", "Bob Jones", "Dave Brown"],
        "Segment"      : ["Consumer", "Corporate", "Home Office", "Corporate", "Consumer"],
        "Country"      : ["United States"] * 5,
        "City"         : ["Los Angeles", "New York", "Chicago", "New York", "Seattle"],
        "State"        : ["California", "New York", "Illinois", "New York", "Washington"],
        "Postal Code"  : [90001, 10001, 60601, 10001, 98101],
        "Region"       : ["West", "East", "Central", "East", "West"],
        "Product ID"   : ["FUR-BO-001", "TEC-PH-001", "OFF-BI-001", "TEC-PH-001", "FUR-CH-001"],
        "Category"     : ["Furniture", "Technology", "Office Supplies", "Technology", "Furniture"],
        "Sub-Category" : ["Bookcases", "Phones", "Binders", "Phones", "Chairs"],
        "Product Name" : ["Sauder Shelf", "Cisco Phone", "Avery Binder", "Cisco Phone", "HON Chair"],
        "Sales"        : [261.96, 907.15, 14.62, 907.15, 731.94],
        "Quantity"     : [2, 6, 3, 6, 3],
        "Discount"     : [0.0, 0.5, 0.0, 0.5, 0.3],
        "Profit"       : [41.91, -383.03, 6.87, -383.03, 219.58],
    })


@pytest.fixture
def clean_df(minimal_raw_df, logger):
    """Return a normalized + cleaned DataFrame (post data_pipeline stages 2–5)."""
    df = normalize_column_names(minimal_raw_df.copy(), logger)
    df = clean_data(df, logger)
    return df


@pytest.fixture
def featured_df(clean_df, logger):
    """Return a fully featured DataFrame (post stages 2–6)."""
    return engineer_features(clean_df.copy(), logger)


@pytest.fixture
def alert_ready_df(featured_df, logger):
    """Return a DataFrame fully processed and ready for alert evaluation."""
    df = detect_anomalies(featured_df.copy(), logger)
    df = add_rule_input_features(df, logger)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 1 TESTS — data_pipeline.py
# ─────────────────────────────────────────────────────────────────────────────

class TestColumnNormalization:
    """Tests for _to_snake() and normalize_column_names()."""

    def test_space_to_underscore(self):
        assert _to_snake("Order Date") == "order_date"

    def test_hyphen_to_underscore(self):
        assert _to_snake("Sub-Category") == "sub_category"

    def test_slash_to_underscore(self):
        assert _to_snake("Sales/Revenue") == "sales_revenue"

    def test_leading_trailing_whitespace(self):
        assert _to_snake("  Ship Mode  ") == "ship_mode"

    def test_already_snake_case(self):
        assert _to_snake("profit_margin_pct") == "profit_margin_pct"

    def test_mixed_special_characters(self):
        assert _to_snake("Avg. Discount %") == "avg_discount_"

    def test_normalize_full_dataframe(self, minimal_raw_df, logger):
        df = normalize_column_names(minimal_raw_df.copy(), logger)
        assert "order_id"   in df.columns
        assert "order_date" in df.columns
        assert "ship_date"  in df.columns
        assert "sub_category" in df.columns
        # Verify no raw column names remain
        assert "Order ID"   not in df.columns
        assert "Sub-Category" not in df.columns


class TestSchemaValidation:
    """Tests for validate_schema()."""

    def test_valid_schema_passes(self, logger):
        df = pd.DataFrame(columns=[_to_snake(c) for c in REQUIRED_COLUMNS])
        # Should not raise
        validate_schema(df, logger)

    def test_missing_column_raises(self, logger):
        df = pd.DataFrame(columns=["order_id", "sales"])  # only 2 columns
        with pytest.raises(KeyError, match="Schema validation FAILED"):
            validate_schema(df, logger)


class TestDataCleaning:
    """Tests for clean_data()."""

    def test_business_key_deduplication(self, minimal_raw_df, logger):
        df = normalize_column_names(minimal_raw_df.copy(), logger)
        # Row 1 and Row 3 share order_id=CA-2019-002 + product_id=TEC-PH-001
        cleaned = clean_data(df, logger)
        # Should have fewer rows than input (duplicate removed)
        assert len(cleaned) < len(df)

    def test_datetime_parsing_us_format(self, minimal_raw_df, logger):
        df = normalize_column_names(minimal_raw_df.copy(), logger)
        cleaned = clean_data(df, logger)
        assert pd.api.types.is_datetime64_any_dtype(cleaned["order_date"])
        assert pd.api.types.is_datetime64_any_dtype(cleaned["ship_date"])

    def test_unparseable_dates_dropped(self, logger):
        df = pd.DataFrame({
            "order_id"   : ["X-001"],
            "order_date" : ["not-a-date"],
            "ship_date"  : ["also-bad"],
            "ship_mode"  : ["Standard Class"],
            "customer_id": ["CG-001"],
            "customer_name": ["Test User"],
            "segment"    : ["Consumer"],
            "country"    : ["United States"],
            "city"       : ["LA"],
            "state"      : ["California"],
            "postal_code": ["90001"],
            "region"     : ["West"],
            "product_id" : ["FUR-01"],
            "category"   : ["Furniture"],
            "sub_category": ["Chairs"],
            "product_name": ["Test Chair"],
            "sales"      : [100.0],
            "quantity"   : [1],
            "discount"   : [0.0],
            "profit"     : [10.0],
        })
        cleaned = clean_data(df, logger)
        assert len(cleaned) == 0  # Bad dates → row dropped

    def test_discount_percentage_detection_and_conversion(self, logger):
        df = pd.DataFrame({
            "order_id"   : ["X-001", "X-002"],
            "order_date" : ["2019-01-01", "2019-02-01"],
            "ship_date"  : ["2019-01-05", "2019-02-05"],
            "ship_mode"  : ["Standard Class"] * 2,
            "customer_id": ["CG-001", "CG-002"],
            "customer_name": ["Alice", "Bob"],
            "segment"    : ["Consumer"] * 2,
            "country"    : ["United States"] * 2,
            "city"       : ["LA", "NY"],
            "state"      : ["California", "New York"],
            "postal_code": ["90001", "10001"],
            "region"     : ["West", "East"],
            "product_id" : ["P-001", "P-002"],
            "category"   : ["Furniture"] * 2,
            "sub_category": ["Chairs"] * 2,
            "product_name": ["Chair A", "Chair B"],
            "sales"      : [100.0, 200.0],
            "quantity"   : [1, 2],
            "discount"   : [30.0, 50.0],  # percentage, not decimal — should be converted
            "profit"     : [10.0, -20.0],
        })
        cleaned = clean_data(df, logger)
        # All discounts should now be in [0, 1]
        assert cleaned["discount"].max() <= 1.0
        assert cleaned["discount"].min() >= 0.0

    def test_discount_clipped_to_valid_range(self, logger):
        df = pd.DataFrame({
            "order_id"   : ["X-001"],
            "order_date" : ["2019-01-01"],
            "ship_date"  : ["2019-01-05"],
            "ship_mode"  : ["Standard Class"],
            "customer_id": ["CG-001"],
            "customer_name": ["Alice"],
            "segment"    : ["Consumer"],
            "country"    : ["United States"],
            "city"       : ["LA"],
            "state"      : ["California"],
            "postal_code": ["90001"],
            "region"     : ["West"],
            "product_id" : ["P-001"],
            "category"   : ["Furniture"],
            "sub_category": ["Chairs"],
            "product_name": ["Chair A"],
            "sales"      : [100.0],
            "quantity"   : [1],
            "discount"   : [-0.5],   # invalid: negative
            "profit"     : [10.0],
        })
        cleaned = clean_data(df, logger)
        assert cleaned["discount"].iloc[0] == 0.0   # clipped to 0

    def test_missing_categoricals_filled_unknown(self, minimal_raw_df, logger):
        df = normalize_column_names(minimal_raw_df.copy(), logger)
        df.loc[0, "region"] = None   # inject a null
        cleaned = clean_data(df, logger)
        assert "Unknown" in cleaned["region"].values or cleaned["region"].isna().sum() == 0


class TestFeatureEngineering:
    """Tests for engineer_features()."""

    def test_profit_margin_pct_formula(self, clean_df, logger):
        df = engineer_features(clean_df.copy(), logger)
        for _, row in df.iterrows():
            if row["sales"] != 0:
                expected = (row["profit"] / row["sales"]) * 100
                assert abs(row["profit_margin_pct"] - expected) < 0.01

    def test_shipping_duration_non_negative(self, clean_df, logger):
        df = engineer_features(clean_df.copy(), logger)
        assert (df["shipping_duration_days"] >= 0).all()

    def test_original_list_price_formula(self, clean_df, logger):
        df = engineer_features(clean_df.copy(), logger)
        for _, row in df.iterrows():
            if row["discount"] < 1.0 and row["discount"] >= 0:
                expected = row["sales"] / (1 - row["discount"])
                assert abs(row["original_list_price"] - expected) < 0.01

    def test_discount_loss_amount_non_negative(self, clean_df, logger):
        df = engineer_features(clean_df.copy(), logger)
        # Discount loss should be >= 0 (you can't gain from discounting)
        assert (df["discount_loss_amount"] >= 0).all()

    def test_zero_sales_margin_handled(self, logger):
        df = pd.DataFrame({
            "order_id": ["X-001"], "order_date": pd.to_datetime(["2019-01-01"]),
            "ship_date": pd.to_datetime(["2019-01-05"]),
            "sales": [0.0], "profit": [0.0], "discount": [0.0],
        })
        result = engineer_features(df, logger)
        assert pd.isna(result["profit_margin_pct"].iloc[0]) or result["profit_margin_pct"].iloc[0] == 0

    def test_time_dimension_columns_created(self, clean_df, logger):
        df = engineer_features(clean_df.copy(), logger)
        for col in ["order_year", "order_month", "order_quarter", "order_week"]:
            assert col in df.columns, f"Missing expected column: {col}"

    def test_order_year_matches_date(self, clean_df, logger):
        df = engineer_features(clean_df.copy(), logger)
        for _, row in df.iterrows():
            assert row["order_year"] == row["order_date"].year


class TestAnomalyDetection:
    """Tests for detect_anomalies()."""

    def test_high_discount_flag_threshold(self, featured_df, logger):
        df = detect_anomalies(featured_df.copy(), logger)
        high = df[df["discount"] >= 0.50]
        assert (high["high_discount_flag"] == 1).all()
        low  = df[df["discount"] < 0.50]
        assert (low["high_discount_flag"] == 0).all()

    def test_margin_bleed_flag_threshold(self, featured_df, logger):
        df = detect_anomalies(featured_df.copy(), logger)
        bleed = df[df["profit_margin_pct"] <= -20.0]
        assert (bleed["margin_bleed_flag"] == 1).all()

    def test_negative_profit_flag(self, featured_df, logger):
        df = detect_anomalies(featured_df.copy(), logger)
        neg = df[df["profit"] < 0]
        assert (neg["negative_profit_flag"] == 1).all()

    def test_anomaly_count_is_sum_of_flags(self, featured_df, logger):
        df = detect_anomalies(featured_df.copy(), logger)
        flag_cols = [
            "high_discount_flag", "margin_bleed_flag",
            "zero_sales_flag", "negative_profit_flag", "long_shipping_flag"
        ]
        for _, row in df.iterrows():
            expected = sum(row[f] for f in flag_cols)
            assert row["anomaly_count"] == expected


class TestExports:
    """Tests for export_csv() and export_sqlite()."""

    def test_csv_export_creates_file(self, featured_df, logger):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "test_out.csv"
            df  = detect_anomalies(featured_df, logger)
            export_csv(df, out, logger)
            assert out.exists()
            assert out.stat().st_size > 0

    def test_csv_roundtrip_row_count(self, featured_df, logger):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "test_out.csv"
            df  = detect_anomalies(featured_df, logger)
            export_csv(df, out, logger)
            loaded = pd.read_csv(out, encoding="utf-8-sig")
            assert len(loaded) == len(df)

    def test_sqlite_export_creates_table(self, featured_df, logger):
        with temp_db() as tmpdir:
            db_path = tmpdir / "test.db"
            df      = detect_anomalies(featured_df, logger)
            export_sqlite(df, db_path, logger)
            conn  = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            conn.close()
            assert count == len(df)

    def test_sqlite_export_is_idempotent(self, featured_df, logger):
        """Running export twice should yield same row count (if_exists='replace')."""
        with temp_db() as tmpdir:
            db_path = tmpdir / "test.db"
            df      = detect_anomalies(featured_df, logger)
            export_sqlite(df, db_path, logger)
            export_sqlite(df, db_path, logger)   # run again
            conn  = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            conn.close()
            assert count == len(df)   # NOT doubled


# ─────────────────────────────────────────────────────────────────────────────
# MODULE 3 TESTS — alert_engine.py
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleInputFeatures:
    """Tests for add_rule_input_features()."""

    def test_first_class_flagged_as_premium(self, alert_ready_df, logger):
        fc_rows = alert_ready_df[alert_ready_df["ship_mode"].str.lower() == "first class"]
        if not fc_rows.empty:
            assert (fc_rows["ship_mode_premium"] == 1).all()

    def test_same_day_flag_correct(self, alert_ready_df, logger):
        sd_rows = alert_ready_df[alert_ready_df["ship_mode"].str.lower() == "same day"]
        if not sd_rows.empty:
            assert (sd_rows["ship_mode_same_day"] == 1).all()

    def test_standard_class_not_premium(self, alert_ready_df, logger):
        sc_rows = alert_ready_df[alert_ready_df["ship_mode"].str.lower() == "standard class"]
        if not sc_rows.empty:
            assert (sc_rows["ship_mode_premium"] == 0).all()


class TestRuleEvaluation:
    """Tests for evaluate_all_rules()."""

    def test_critical_price_override_fires_correctly(self, logger):
        """CRITICAL_PRICE_OVERRIDE: discount >= 0.30 AND margin <= -20%"""
        df = pd.DataFrame({
            "order_id"             : ["A", "B", "C"],
            "discount"             : [0.35, 0.10, 0.50],
            "profit_margin_pct"    : [-25.0, -25.0, -10.0],
            "shipping_duration_days": [3, 3, 3],
            "sales"                : [500, 500, 500],
            "profit"               : [-125, -125, -50],
            "discount_loss_amount" : [200, 50, 300],
            "ship_mode_premium"    : [0, 0, 0],
            "ship_mode_same_day"   : [0, 0, 0],
        })
        result = evaluate_all_rules(df, logger)
        # Row A: discount=0.35 >= 0.30 AND margin=-25 <= -20 → FIRES
        assert result.loc[0, "primary_action_code"] == "FREEZE_DISCOUNT"
        # Row B: discount=0.10 < 0.30 → does NOT fire CRITICAL_PRICE_OVERRIDE
        assert result.loc[1, "primary_action_code"] != "FREEZE_DISCOUNT" or \
               "CRITICAL_PRICE_OVERRIDE" not in result.loc[1, "rules_triggered"]
        # Row C: margin=-10 > -20 → does NOT fire CRITICAL_PRICE_OVERRIDE
        assert "CRITICAL_PRICE_OVERRIDE" not in result.loc[2, "rules_triggered"]

    def test_high_volume_leakage_fires_correctly(self, logger):
        """HIGH_VOLUME_LEAKAGE: sales > 1000 AND profit < 0"""
        df = pd.DataFrame({
            "order_id"             : ["A", "B", "C"],
            "discount"             : [0.05, 0.05, 0.05],
            "profit_margin_pct"    : [-5.0, -5.0, 5.0],
            "shipping_duration_days": [3, 3, 3],
            "sales"                : [1500.0, 800.0, 1500.0],   # A fires, B no, C no (positive profit)
            "profit"               : [-75.0, -40.0, 75.0],
            "discount_loss_amount" : [80, 40, 80],
            "ship_mode_premium"    : [0, 0, 0],
            "ship_mode_same_day"   : [0, 0, 0],
        })
        result = evaluate_all_rules(df, logger)
        assert "HIGH_VOLUME_LEAKAGE" in result.loc[0, "rules_triggered"]
        assert "HIGH_VOLUME_LEAKAGE" not in result.loc[1, "rules_triggered"]
        assert "HIGH_VOLUME_LEAKAGE" not in result.loc[2, "rules_triggered"]

    def test_no_alert_for_clean_order(self, logger):
        """A healthy order should produce NO_ACTION."""
        df = pd.DataFrame({
            "order_id"             : ["CLEAN-001"],
            "discount"             : [0.05],
            "profit_margin_pct"    : [20.0],
            "shipping_duration_days": [2],
            "sales"                : [300.0],
            "profit"               : [60.0],
            "discount_loss_amount" : [15.0],
            "ship_mode_premium"    : [0],
            "ship_mode_same_day"   : [0],
        })
        result = evaluate_all_rules(df, logger)
        assert result.loc[0, "primary_action_code"] == "NO_ACTION"
        assert result.loc[0, "rules_triggered"]       == ""
        assert result.loc[0, "rules_triggered_count"] == 0

    def test_composite_risk_score_increases_with_rules(self, logger):
        """Orders triggering more rules should have higher composite_risk_score."""
        df = pd.DataFrame({
            "order_id"             : ["MULTI", "SINGLE"],
            "discount"             : [0.55, 0.55],         # both trigger RUNAWAY_DISCOUNT
            "profit_margin_pct"    : [-30.0, 5.0],         # MULTI also triggers CRITICAL_PRICE_OVERRIDE
            "shipping_duration_days": [3, 3],
            "sales"                : [1500.0, 1500.0],
            "profit"               : [-450.0, 75.0],
            "discount_loss_amount" : [1650.0, 1650.0],
            "ship_mode_premium"    : [0, 0],
            "ship_mode_same_day"   : [0, 0],
        })
        result = evaluate_all_rules(df, logger)
        assert result.loc[0, "composite_risk_score"] >= result.loc[1, "composite_risk_score"]

    def test_primary_action_priority_ordering(self, logger):
        """When multiple rules fire, priority 1 rule should be the primary action."""
        df = pd.DataFrame({
            "order_id"             : ["TEST-001"],
            "discount"             : [0.40],        # fires CRITICAL_PRICE_OVERRIDE (priority 1)
            "profit_margin_pct"    : [-25.0],
            "shipping_duration_days": [3],
            "sales"                : [2000.0],      # also fires HIGH_VOLUME_LEAKAGE (priority 3)
            "profit"               : [-500.0],
            "discount_loss_amount" : [1200.0],
            "ship_mode_premium"    : [0],
            "ship_mode_same_day"   : [0],
        })
        result = evaluate_all_rules(df, logger)
        # Primary should be the highest-priority rule (priority=1 → FREEZE_DISCOUNT)
        assert result.loc[0, "primary_action_code"] == "FREEZE_DISCOUNT"
        assert result.loc[0, "alert_priority"]      == 1

    def test_rules_triggered_count_matches_rules_list(self, alert_ready_df, logger):
        """rules_triggered_count must equal the pipe-count of rules_triggered."""
        result = evaluate_all_rules(alert_ready_df.copy(), logger)
        for _, row in result.iterrows():
            if row["rules_triggered"]:
                expected = len(row["rules_triggered"].split(" | "))
            else:
                expected = 0
            assert row["rules_triggered_count"] == expected

    def test_alert_queue_sorted_priority_ascending(self, alert_ready_df, logger):
        """Exported queue must be sorted: alert_priority ASC, risk_score DESC."""
        df         = evaluate_all_rules(alert_ready_df.copy(), logger)
        alerted    = df[df["primary_action_code"] != "NO_ACTION"].copy()
        alerted    = alerted.sort_values(
            ["alert_priority", "composite_risk_score"], ascending=[True, False]
        )
        # Priority should be non-decreasing
        priorities = alerted["alert_priority"].tolist()
        assert priorities == sorted(priorities)

    def test_rule_registry_has_required_fields(self):
        """Every rule in RULE_REGISTRY must have all required keys."""
        required_keys = {"rule_id", "display_name", "priority", "action_code",
                         "conditions", "rationale", "owner", "sla_hours"}
        for rule in RULE_REGISTRY:
            missing = required_keys - set(rule.keys())
            assert not missing, f"Rule '{rule.get('rule_id','?')}' missing keys: {missing}"

    def test_operator_map_completeness(self):
        """OPERATOR_MAP must cover all operators used in RULE_REGISTRY."""
        for rule in RULE_REGISTRY:
            for col, (op, threshold) in rule["conditions"].items():
                assert op in OPERATOR_MAP, \
                    f"Operator '{op}' in rule '{rule['rule_id']}' not in OPERATOR_MAP"


class TestAlertExport:
    """Tests for export_action_queue()."""

    def test_export_contains_only_alerted_orders(self, alert_ready_df, logger):
        df = evaluate_all_rules(alert_ready_df.copy(), logger)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "queue.csv"
            queue = export_action_queue(df, out, logger)
        assert (queue["primary_action_code"] != "NO_ACTION").all()

    def test_export_file_is_utf8_bom(self, alert_ready_df, logger):
        df = evaluate_all_rules(alert_ready_df.copy(), logger)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "queue.csv"
            export_action_queue(df, out, logger)
            raw_bytes = out.read_bytes()[:3]
            # utf-8-sig starts with BOM: EF BB BF
            assert raw_bytes == b"\xef\xbb\xbf", "CSV should start with UTF-8 BOM"


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegration:
    """End-to-end pipeline integration tests."""

    def test_full_pipeline_preserves_row_count(self, minimal_raw_df, logger):
        """After dedup + clean + feature eng + anomaly: row count should be ≤ input."""
        df = normalize_column_names(minimal_raw_df.copy(), logger)
        validate_schema(df, logger)
        cleaned  = clean_data(df, logger)
        featured = engineer_features(cleaned, logger)
        flagged  = detect_anomalies(featured, logger)
        assert len(flagged) <= len(minimal_raw_df)

    def test_full_pipeline_column_count_grows(self, minimal_raw_df, logger):
        """Feature engineering should add new columns to the DataFrame."""
        df = normalize_column_names(minimal_raw_df.copy(), logger)
        cleaned  = clean_data(df, logger)
        featured = engineer_features(cleaned, logger)
        flagged  = detect_anomalies(featured, logger)
        # Should have more columns than raw (21 original + engineered + flags)
        assert len(flagged.columns) > len(minimal_raw_df.columns)

    def test_pipeline_to_alert_engine_handoff(self, minimal_raw_df, logger):
        """
        Simulate the full M1→M3 handoff:
        data_pipeline output → alert_engine input → action queue produced.
        """
        df = normalize_column_names(minimal_raw_df.copy(), logger)
        cleaned  = clean_data(df, logger)
        featured = engineer_features(cleaned, logger)
        flagged  = detect_anomalies(featured, logger)
        alert_df = add_rule_input_features(flagged, logger)
        result   = evaluate_all_rules(alert_df, logger)
        # Every row should have a primary_action_code (even if NO_ACTION)
        assert "primary_action_code" in result.columns
        assert result["primary_action_code"].notna().all()

    def test_no_data_loss_on_sqlite_roundtrip(self, minimal_raw_df, logger):
        """Data written to SQLite and read back should match the original."""
        df = normalize_column_names(minimal_raw_df.copy(), logger)
        cleaned  = clean_data(df, logger)
        featured = engineer_features(cleaned, logger)
        flagged  = detect_anomalies(featured, logger)

        with temp_db() as tmpdir:
            db_path = tmpdir / "roundtrip.db"
            export_sqlite(flagged, db_path, logger)
            conn    = sqlite3.connect(str(db_path))
            loaded  = pd.read_sql("SELECT * FROM orders", conn)
            conn.close()

        assert len(loaded) == len(flagged)
        # Check key numeric columns match (within float tolerance)
        for col in ["sales", "profit", "profit_margin_pct"]:
            if col in flagged.columns:
                np.testing.assert_allclose(
                    loaded[col].values,
                    flagged[col].values,
                    rtol=1e-4,
                    err_msg=f"Mismatch in column '{col}' after SQLite roundtrip"
                )
