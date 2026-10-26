"""
=============================================================================
run_queries.py  —  MODULE 2: SQL Query Runner & Results Exporter
=============================================================================
Project : Retail Margin & Inventory Leakage — A Last-Mile Decision Engine
Version : 1.0.0

Description
-----------
Executes all 4 analytical SQL queries against the SQLite database produced
by data_pipeline.py and exports each result set to a separate CSV in
data/processed/query_results/.

Usage
-----
  python sql/run_queries.py
  python sql/run_queries.py --query 1        # Run only Query 1
  python sql/run_queries.py --preview 15     # Show 15 rows per result
=============================================================================
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DB_PATH        = Path("data/db/superstore.db")
SQL_FILE       = Path("sql/analytical_queries.sql")
OUTPUT_DIR     = Path("data/processed/query_results")

# ---------------------------------------------------------------------------
# Query definitions — each entry maps to a labelled block in the .sql file
# The raw SQL is embedded here for portability; the .sql file is the
# canonical reference and single source of truth for annotations.
# ---------------------------------------------------------------------------

QUERIES = {
    1: {
        "title"      : "HIGH-VOLUME MARGIN BLEED — Sub-Category Discount Correlation",
        "description": "Identifies sub-categories where high discounts produce net-negative margins.",
        "sql": """
WITH sub_category_metrics AS (
    SELECT
        category,
        sub_category,
        COUNT(*)                              AS total_orders,
        SUM(quantity)                         AS total_units_sold,
        ROUND(SUM(sales), 2)                  AS total_revenue,
        ROUND(SUM(profit), 2)                 AS total_profit,
        ROUND(
            CASE WHEN SUM(sales) = 0 THEN NULL
                 ELSE (SUM(profit) / SUM(sales)) * 100 END, 2
        )                                     AS blended_margin_pct,
        ROUND(AVG(discount) * 100, 2)         AS avg_discount_pct,
        ROUND(SUM(discount_loss_amount), 2)   AS total_discount_loss_usd,
        ROUND(SUM(negative_profit_flag) * 100.0 / COUNT(*), 2) AS pct_loss_making_orders
    FROM orders
    GROUP BY category, sub_category
),
bleed_classification AS (
    SELECT
        *,
        CASE
            WHEN blended_margin_pct < 0 AND avg_discount_pct >= 20
                THEN 'CRITICAL - Discount-Driven Loss'
            WHEN blended_margin_pct < 0 AND avg_discount_pct < 20
                THEN 'WARNING - Structural Cost Problem'
            WHEN blended_margin_pct >= 0 AND avg_discount_pct >= 30
                THEN 'MONITOR - High Discount, Margin Positive'
            ELSE 'HEALTHY'
        END AS margin_health_status,
        RANK() OVER (ORDER BY total_profit ASC) AS profit_destruction_rank
    FROM sub_category_metrics
)
SELECT
    profit_destruction_rank  AS priority_rank,
    category, sub_category, total_orders,
    total_revenue, total_profit, blended_margin_pct,
    avg_discount_pct, total_discount_loss_usd,
    pct_loss_making_orders, margin_health_status
FROM bleed_classification
ORDER BY profit_destruction_rank ASC, total_discount_loss_usd DESC;
        """,
    },

    2: {
        "title"      : "LAST-MILE FULFILLMENT LATENCY — Region × Ship Mode Bottleneck Ranking",
        "description": "Ranks state-level shipping delays using window functions and DENSE_RANK.",
        "sql": """
WITH order_shipping_detail AS (
    SELECT
        order_id, region, state, ship_mode, shipping_duration_days,
        ROUND(AVG(shipping_duration_days) OVER (PARTITION BY region, ship_mode), 2)
            AS region_ship_mode_avg_days,
        ROUND(AVG(shipping_duration_days) OVER (PARTITION BY ship_mode), 2)
            AS global_ship_mode_avg_days
    FROM orders
    WHERE shipping_duration_days IS NOT NULL
),
state_shipping_metrics AS (
    SELECT
        region, state, ship_mode,
        COUNT(*)                                   AS total_shipments,
        ROUND(AVG(shipping_duration_days), 2)      AS state_avg_shipping_days,
        ROUND(MAX(shipping_duration_days), 0)      AS max_shipping_days,
        ROUND(AVG(region_ship_mode_avg_days), 2)   AS regional_benchmark_days,
        ROUND(AVG(global_ship_mode_avg_days), 2)   AS global_benchmark_days,
        ROUND(
            SUM(CASE WHEN shipping_duration_days > 5 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2
        )                                          AS pct_sla_breached,
        SUM(CASE WHEN shipping_duration_days > 5
                  AND ship_mode IN ('First Class','Second Class') THEN 1 ELSE 0 END
        )                                          AS premium_sla_breaches
    FROM order_shipping_detail
    GROUP BY region, state, ship_mode
),
state_ranked AS (
    SELECT *,
        DENSE_RANK() OVER (PARTITION BY ship_mode ORDER BY state_avg_shipping_days DESC)
            AS bottleneck_rank_within_ship_mode,
        DENSE_RANK() OVER (ORDER BY state_avg_shipping_days DESC)
            AS overall_bottleneck_rank
    FROM state_shipping_metrics
)
SELECT
    overall_bottleneck_rank, bottleneck_rank_within_ship_mode,
    region, state, ship_mode, total_shipments,
    state_avg_shipping_days, regional_benchmark_days, global_benchmark_days,
    ROUND(state_avg_shipping_days - regional_benchmark_days, 2) AS days_above_regional_avg,
    pct_sla_breached, premium_sla_breaches,
    CASE
        WHEN premium_sla_breaches > 0 THEN 'LOGISTICS_CHOKEPOINT - Escalate'
        WHEN pct_sla_breached > 50    THEN 'SLA_RISK - Monitor'
        ELSE 'WITHIN_SLA'
    END AS operational_status
FROM state_ranked
ORDER BY overall_bottleneck_rank ASC, ship_mode;
        """,
    },

    3: {
        "title"      : "ORDER DECILE & PROFITABILITY DISTRIBUTION — NTILE(10) Tier Analysis",
        "description": "Segments all orders into 10 profitability tiers to isolate value-destroying D1 transactions.",
        "sql": """
WITH order_deciles AS (
    SELECT
        order_id, category, sub_category, region, ship_mode, segment,
        sales, profit, discount, profit_margin_pct, discount_loss_amount,
        NTILE(10) OVER (ORDER BY profit ASC) AS profit_decile,
        NTILE(10) OVER (PARTITION BY category ORDER BY profit ASC)
            AS profit_decile_within_category
    FROM orders
),
decile_summary AS (
    SELECT
        profit_decile,
        COUNT(*)                               AS order_count,
        ROUND(SUM(sales), 2)                   AS total_revenue,
        ROUND(SUM(profit), 2)                  AS total_profit,
        ROUND(AVG(profit), 2)                  AS avg_profit_per_order,
        ROUND(AVG(profit_margin_pct), 2)       AS avg_margin_pct,
        ROUND(AVG(discount) * 100, 2)          AS avg_discount_pct,
        ROUND(SUM(discount_loss_amount), 2)    AS total_discount_bleed,
        ROUND(SUM(sales) * 100.0 / SUM(SUM(sales)) OVER (), 2) AS pct_of_total_revenue,
        ROUND(SUM(profit) * 100.0 / SUM(SUM(profit)) OVER (), 2) AS pct_of_total_profit,
        SUM(SUM(profit)) OVER (
            ORDER BY profit_decile ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_profit
    FROM order_deciles
    GROUP BY profit_decile
)
SELECT
    profit_decile,
    CASE
        WHEN profit_decile = 1  THEN 'D1 - CRITICAL LOSS TIER'
        WHEN profit_decile = 2  THEN 'D2 - HIGH LOSS'
        WHEN profit_decile = 3  THEN 'D3 - MODERATE LOSS'
        WHEN profit_decile <= 5 THEN 'D4-D5 - BREAK-EVEN ZONE'
        WHEN profit_decile <= 7 THEN 'D6-D7 - MARGINALLY PROFITABLE'
        WHEN profit_decile <= 9 THEN 'D8-D9 - HEALTHY PROFIT'
        ELSE                        'D10 - TOP PERFORMERS'
    END AS decile_label,
    order_count, total_revenue, total_profit,
    avg_profit_per_order, avg_margin_pct, avg_discount_pct,
    total_discount_bleed, pct_of_total_revenue, pct_of_total_profit,
    ROUND(cumulative_profit, 2) AS cumulative_profit
FROM decile_summary
ORDER BY profit_decile ASC;
        """,
    },

    4: {
        "title"      : "YoY COHORT SUMMARY — Revenue vs. Net Margin Growth via LAG()",
        "description": "Year-over-Year growth analysis with directional margin trend signals per category.",
        "sql": """
WITH annual_category_metrics AS (
    SELECT
        order_year, category,
        COUNT(DISTINCT order_id)               AS total_orders,
        ROUND(SUM(sales), 2)                   AS total_revenue,
        ROUND(SUM(profit), 2)                  AS total_profit,
        ROUND(SUM(discount_loss_amount), 2)    AS total_discount_bleed,
        ROUND(CASE WHEN SUM(sales)=0 THEN NULL
              ELSE (SUM(profit)/SUM(sales))*100 END, 4) AS blended_margin_pct,
        ROUND(SUM(sales)/NULLIF(COUNT(DISTINCT order_id),0), 2) AS avg_order_value,
        ROUND(AVG(discount)*100, 2) AS avg_discount_pct
    FROM orders
    GROUP BY order_year, category
),
yoy_comparison AS (
    SELECT *,
        LAG(total_revenue,1)     OVER (PARTITION BY category ORDER BY order_year) AS prev_year_revenue,
        LAG(total_profit,1)      OVER (PARTITION BY category ORDER BY order_year) AS prev_year_profit,
        LAG(blended_margin_pct,1)OVER (PARTITION BY category ORDER BY order_year) AS prev_year_margin_pct,
        LAG(avg_discount_pct,1)  OVER (PARTITION BY category ORDER BY order_year) AS prev_year_discount_pct,
        LAG(avg_order_value,1)   OVER (PARTITION BY category ORDER BY order_year) AS prev_year_aov
    FROM annual_category_metrics
),
yoy_growth AS (
    SELECT *,
        ROUND(CASE
            WHEN prev_year_revenue IS NULL OR prev_year_revenue=0 THEN NULL
            ELSE ((total_revenue-prev_year_revenue)/prev_year_revenue)*100 END, 2) AS revenue_yoy_growth_pct,
        ROUND(CASE
            WHEN prev_year_profit IS NULL OR prev_year_profit=0 THEN NULL
            WHEN prev_year_profit<0 AND total_profit>0 THEN 100.0
            WHEN prev_year_profit<0 AND total_profit<0
                THEN ((ABS(total_profit)-ABS(prev_year_profit))/ABS(prev_year_profit))*100
            ELSE ((total_profit-prev_year_profit)/ABS(prev_year_profit))*100 END, 2) AS profit_yoy_growth_pct,
        ROUND(blended_margin_pct - COALESCE(prev_year_margin_pct, blended_margin_pct), 2) AS margin_point_change,
        ROUND(avg_discount_pct   - COALESCE(prev_year_discount_pct, avg_discount_pct), 2) AS discount_rate_drift,
        ROUND(CASE
            WHEN prev_year_aov IS NULL OR prev_year_aov=0 THEN NULL
            ELSE ((avg_order_value-prev_year_aov)/prev_year_aov)*100 END, 2) AS aov_yoy_growth_pct
    FROM yoy_comparison
)
SELECT
    order_year AS fiscal_year, category,
    total_orders, total_revenue, prev_year_revenue, revenue_yoy_growth_pct,
    total_profit, prev_year_profit, profit_yoy_growth_pct,
    blended_margin_pct, prev_year_margin_pct, margin_point_change,
    avg_discount_pct, discount_rate_drift, total_discount_bleed,
    avg_order_value, aov_yoy_growth_pct,
    CASE
        WHEN revenue_yoy_growth_pct IS NULL           THEN 'BASELINE YEAR'
        WHEN revenue_yoy_growth_pct >= 10             THEN 'STRONG GROWTH'
        WHEN revenue_yoy_growth_pct >= 0              THEN 'MODEST GROWTH'
        WHEN revenue_yoy_growth_pct >= -10            THEN 'MILD DECLINE'
        ELSE                                               'SIGNIFICANT DECLINE'
    END AS revenue_trend_signal,
    CASE
        WHEN margin_point_change IS NULL OR margin_point_change=0 THEN 'STABLE'
        WHEN margin_point_change > 2   THEN 'EXPANDING'
        WHEN margin_point_change > 0   THEN 'SLIGHTLY EXPANDING'
        WHEN margin_point_change > -2  THEN 'COMPRESSING'
        ELSE                                'RAPID COMPRESSION - ALERT'
    END AS margin_trend_signal,
    CASE
        WHEN revenue_yoy_growth_pct >= 5 AND margin_point_change >= 0 THEN 'GREEN - HEALTHY'
        WHEN revenue_yoy_growth_pct >= 0 OR  margin_point_change >= 0 THEN 'AMBER - WATCH'
        ELSE                                                                'RED - INTERVENTION'
    END AS executive_rag_status
FROM yoy_growth
ORDER BY category ASC, order_year ASC;
        """,
    },
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def configure_logging() -> logging.Logger:
    logger = logging.getLogger("query_runner")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(message)s", "%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(ch)
    return logger


def run_query(query_id: int, preview_rows: int, engine, logger) -> pd.DataFrame:
    """Execute a single query and return results as a DataFrame."""
    q = QUERIES[query_id]
    sep = "=" * 70

    logger.info(sep)
    logger.info(f"QUERY {query_id}: {q['title']}")
    logger.info(q["description"])
    logger.info(sep)

    try:
        df = pd.read_sql_query(q["sql"], con=engine)
        logger.info(f"Result: {len(df):,} rows x {len(df.columns)} columns")

        # Pretty-print preview to terminal
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 160)
        pd.set_option("display.float_format", "{:.2f}".format)
        print("\n" + df.head(preview_rows).to_string(index=False))
        print()

        return df

    except Exception as e:
        logger.error(f"Query {query_id} FAILED: {e}")
        raise


def export_result(df: pd.DataFrame, query_id: int, logger) -> None:
    """Export a query result DataFrame to CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    q        = QUERIES[query_id]
    filename = f"q{query_id}_{q['title'][:40].lower().replace(' ', '_').replace('—','').strip('_')}.csv"
    # Sanitize filename
    filename = "".join(c if c.isalnum() or c in ("_", "-", ".") else "_" for c in filename)
    out_path = OUTPUT_DIR / filename

    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    size_kb = out_path.stat().st_size / 1024
    logger.info(f"Exported -> '{out_path}' ({size_kb:.1f} KB)")


def parse_args():
    parser = argparse.ArgumentParser(
        prog="run_queries.py",
        description="Execute Module 2 SQL analytical queries against the Superstore SQLite database.",
    )
    parser.add_argument(
        "--query", "-q",
        type=int,
        choices=[1, 2, 3, 4],
        default=None,
        help="Run a single query by number (1-4). Omit to run all.",
    )
    parser.add_argument(
        "--preview", "-p",
        type=int,
        default=10,
        help="Number of rows to preview per result (default: 10)",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        default=False,
        help="Skip CSV export (preview only)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args   = parse_args()
    logger = configure_logging()

    if not DB_PATH.exists():
        logger.error(
            f"Database not found at '{DB_PATH}'.\n"
            "Run data_pipeline.py first to generate the database."
        )
        sys.exit(1)

    engine     = create_engine(f"sqlite:///{DB_PATH}")
    query_ids  = [args.query] if args.query else list(QUERIES.keys())

    logger.info(f"Connected to: {DB_PATH}")
    logger.info(f"Running {len(query_ids)} query(ies): {query_ids}")

    results = {}
    for qid in query_ids:
        df = run_query(qid, preview_rows=args.preview, engine=engine, logger=logger)
        results[qid] = df
        if not args.no_export:
            export_result(df, qid, logger)

    logger.info("All queries completed successfully.")
    logger.info(f"Results exported to: {OUTPUT_DIR}")
