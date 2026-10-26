-- =============================================================================
-- analytical_queries.sql  —  MODULE 2: Advanced SQL Analytical Queries
-- =============================================================================
-- Project : Retail Margin & Inventory Leakage — A Last-Mile Decision Engine
-- Author  : Analytics Engineering Team
-- Version : 1.0.0
--
-- Compatibility : ANSI SQL | SQLite | PostgreSQL | BigQuery
--                 Minor dialect notes are annotated inline where syntax diverges.
--
-- Prerequisites : Run data_pipeline.py first to populate the 'orders' table.
--
-- How to run (SQLite CLI):
--   sqlite3 data/db/superstore.db < sql/analytical_queries.sql
--
-- How to run (Python):
--   python sql/run_queries.py
-- =============================================================================


-- =============================================================================
-- QUERY 1: HIGH-VOLUME MARGIN BLEED  (CTEs + Aggregation)
-- =============================================================================
-- Business Rationale:
--   Not all discounting is equal. A 20% discount on a $5 item is negligible;
--   the same on a $5,000 order can destroy the entire profit pool for a week.
--   This query identifies sub-categories where:
--     (a) the average discount rate is high (structural over-discounting), AND
--     (b) the resulting net margin is negative (value destruction).
--   Output gives category managers a ranked list of "discount-to-bleed" offenders
--   to freeze or escalate for pricing governance review.
-- =============================================================================

WITH

-- Step 1: Sub-category level aggregation
-- Compute all key metrics rolled up to the sub-category + category grain.
sub_category_metrics AS (
    SELECT
        category,
        sub_category,

        -- Volume metrics
        COUNT(*)                              AS total_orders,
        SUM(quantity)                         AS total_units_sold,

        -- Revenue & margin
        ROUND(SUM(sales), 2)                  AS total_revenue,
        ROUND(SUM(profit), 2)                 AS total_profit,

        -- Blended margin % at sub-category level
        -- Using SUM(profit)/SUM(sales) rather than AVG(profit_margin_pct)
        -- to avoid Simpson's paradox from averaging percentages of different bases
        ROUND(
            CASE
                WHEN SUM(sales) = 0 THEN NULL
                ELSE (SUM(profit) / SUM(sales)) * 100
            END, 2
        )                                     AS blended_margin_pct,

        -- Discount exposure
        ROUND(AVG(discount) * 100, 2)         AS avg_discount_pct,
        ROUND(SUM(discount_loss_amount), 2)   AS total_discount_loss_usd,

        -- Anomaly concentration — % of orders that are loss-making
        ROUND(
            SUM(negative_profit_flag) * 100.0 / COUNT(*), 2
        )                                     AS pct_loss_making_orders

    FROM orders
    GROUP BY category, sub_category
),

-- Step 2: Flag the "bleed" cases — sub-categories with both high discount AND negative margin
-- These are the structural offenders that require category-level pricing intervention.
bleed_classification AS (
    SELECT
        *,
        CASE
            WHEN blended_margin_pct < 0 AND avg_discount_pct >= 20
                THEN 'CRITICAL — Discount-Driven Loss'
            WHEN blended_margin_pct < 0 AND avg_discount_pct < 20
                THEN 'WARNING — Structural Cost Problem'
            WHEN blended_margin_pct >= 0 AND avg_discount_pct >= 30
                THEN 'MONITOR — High Discount, Margin Positive'
            ELSE 'HEALTHY'
        END AS margin_health_status,

        -- Rank by the magnitude of absolute profit destruction (worst first)
        RANK() OVER (
            ORDER BY total_profit ASC
        ) AS profit_destruction_rank

    FROM sub_category_metrics
)

-- Step 3: Final output — ordered by priority for category manager action
SELECT
    profit_destruction_rank                          AS priority_rank,
    category,
    sub_category,
    total_orders,
    total_revenue,
    total_profit,
    blended_margin_pct,
    avg_discount_pct,
    total_discount_loss_usd,
    pct_loss_making_orders,
    margin_health_status
FROM bleed_classification
ORDER BY
    profit_destruction_rank ASC,   -- worst margin destroyers first
    total_discount_loss_usd DESC;  -- secondary: largest absolute bleed


-- =============================================================================
-- QUERY 2: LAST-MILE FULFILLMENT LATENCY  (Window Functions + DENSE_RANK)
-- =============================================================================
-- Business Rationale:
--   Shipping lag directly impacts customer satisfaction scores (CSAT) and
--   repeat purchase rates. Critically, a "First Class" shipment taking 6+ days
--   signals a logistics chokepoint — the premium is being charged but SLA is
--   not delivered. This query surfaces:
--     (a) Average shipping lag per Region × Ship Mode combination
--     (b) State-level operational bottlenecks ranked by DENSE_RANK
--   Output feeds the Operations Center heatmap and the alert engine.
-- =============================================================================

WITH

-- Step 1: Order-level shipping data with regional window context
order_shipping_detail AS (
    SELECT
        order_id,
        region,
        state,
        ship_mode,
        shipping_duration_days,

        -- Window: Average shipping duration for the same Region + Ship Mode combo
        -- This is the peer benchmark — compare each state against its regional norm
        ROUND(
            AVG(shipping_duration_days) OVER (
                PARTITION BY region, ship_mode
            ), 2
        ) AS region_ship_mode_avg_days,

        -- Window: Average shipping duration across the entire ship mode (global benchmark)
        ROUND(
            AVG(shipping_duration_days) OVER (
                PARTITION BY ship_mode
            ), 2
        ) AS global_ship_mode_avg_days,

        -- Window: How many standard deviations above the regional mean?
        -- Values > 2 indicate statistical outliers (chokepoints)
        -- Note: STDDEV is PostgreSQL/BigQuery. In SQLite use a subquery approach.
        -- SQLite-compatible version uses the peer average comparison instead.
        ROUND(
            shipping_duration_days - AVG(shipping_duration_days) OVER (
                PARTITION BY region, ship_mode
            ), 2
        ) AS days_above_regional_avg

    FROM orders
    WHERE shipping_duration_days IS NOT NULL
),

-- Step 2: State-level aggregation for bottleneck ranking
state_shipping_metrics AS (
    SELECT
        region,
        state,
        ship_mode,

        COUNT(*)                                   AS total_shipments,
        ROUND(AVG(shipping_duration_days), 2)      AS state_avg_shipping_days,
        ROUND(MAX(shipping_duration_days), 0)      AS max_shipping_days,
        ROUND(MIN(shipping_duration_days), 0)      AS min_shipping_days,

        -- Benchmark deltas for performance assessment
        ROUND(AVG(region_ship_mode_avg_days), 2)   AS regional_benchmark_days,
        ROUND(AVG(global_ship_mode_avg_days), 2)   AS global_benchmark_days,

        -- % of shipments exceeding 5-day SLA threshold
        ROUND(
            SUM(CASE WHEN shipping_duration_days > 5 THEN 1 ELSE 0 END)
            * 100.0 / COUNT(*), 2
        )                                          AS pct_sla_breached,

        -- LOGISTICS_CHOKEPOINT alert flag: First/Second Class taking > 5 days
        SUM(
            CASE
                WHEN shipping_duration_days > 5
                 AND ship_mode IN ('First Class', 'Second Class')
                THEN 1 ELSE 0
            END
        )                                          AS premium_sla_breaches

    FROM order_shipping_detail
    GROUP BY region, state, ship_mode
),

-- Step 3: Rank states within each ship mode by average shipping delay (worst first)
-- DENSE_RANK is used over RANK to handle ties without gaps in rank sequence
state_ranked AS (
    SELECT
        *,
        DENSE_RANK() OVER (
            PARTITION BY ship_mode
            ORDER BY state_avg_shipping_days DESC   -- highest delay = rank 1
        ) AS bottleneck_rank_within_ship_mode,

        -- Overall cross-region bottleneck rank (all ship modes combined)
        DENSE_RANK() OVER (
            ORDER BY state_avg_shipping_days DESC
        ) AS overall_bottleneck_rank

    FROM state_shipping_metrics
)

-- Step 4: Final output — surface the worst-performing state × ship mode combos
SELECT
    overall_bottleneck_rank,
    bottleneck_rank_within_ship_mode,
    region,
    state,
    ship_mode,
    total_shipments,
    state_avg_shipping_days,
    regional_benchmark_days,
    global_benchmark_days,
    ROUND(state_avg_shipping_days - regional_benchmark_days, 2) AS days_above_regional_avg,
    pct_sla_breached,
    premium_sla_breaches,
    CASE
        WHEN premium_sla_breaches > 0 THEN 'LOGISTICS_CHOKEPOINT — Escalate'
        WHEN pct_sla_breached > 50    THEN 'SLA_RISK — Monitor'
        ELSE 'WITHIN_SLA'
    END AS operational_status
FROM state_ranked
ORDER BY
    overall_bottleneck_rank ASC,
    ship_mode;


-- =============================================================================
-- QUERY 3: ORDER DECILE & PROFITABILITY DISTRIBUTION  (NTILE Window)
-- =============================================================================
-- Business Rationale:
--   Not all orders contribute equally. The Pareto principle in retail typically
--   means the bottom 10-20% of orders by profitability are actively destroying
--   value — subsidized by the profitable majority. This query segments all
--   orders into 10 equal-sized profitability tiers (deciles) using NTILE(10),
--   enabling leadership to:
--     (a) Quantify how much profit the bottom 10% destroys
--     (b) Identify which categories/regions produce the most loss-tier orders
--     (c) Define a minimum-viable-order threshold for pricing policy
-- =============================================================================

WITH

-- Step 1: Assign each order a profitability decile (1 = worst, 10 = best)
order_deciles AS (
    SELECT
        order_id,
        category,
        sub_category,
        region,
        ship_mode,
        segment,
        sales,
        profit,
        discount,
        profit_margin_pct,
        discount_loss_amount,

        -- NTILE(10) divides rows into 10 equal-sized buckets sorted by profit
        -- Decile 1 = bottom 10% (most loss-making)
        -- Decile 10 = top 10% (most profitable)
        NTILE(10) OVER (
            ORDER BY profit ASC
        ) AS profit_decile,

        -- Also compute decile within each category independently
        -- to identify category-specific outliers
        NTILE(10) OVER (
            PARTITION BY category
            ORDER BY profit ASC
        ) AS profit_decile_within_category

    FROM orders
),

-- Step 2: Decile-level summary — aggregate metrics by profitability tier
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

        -- Revenue concentration — what % of total revenue does this decile represent?
        ROUND(
            SUM(sales) * 100.0 / SUM(SUM(sales)) OVER (), 2
        ) AS pct_of_total_revenue,

        -- Profit concentration — key for the "bottom 10% destroys X% of value" insight
        ROUND(
            SUM(profit) * 100.0 / SUM(SUM(profit)) OVER (), 2
        ) AS pct_of_total_profit,

        -- Cumulative profit — useful for building a Pareto/waterfall chart
        SUM(SUM(profit)) OVER (
            ORDER BY profit_decile ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_profit

    FROM order_deciles
    GROUP BY profit_decile
),

-- Step 3: Tag deciles with business labels for dashboard display
decile_labeled AS (
    SELECT
        *,
        CASE
            WHEN profit_decile = 1  THEN 'D1 — CRITICAL LOSS TIER'
            WHEN profit_decile = 2  THEN 'D2 — HIGH LOSS'
            WHEN profit_decile = 3  THEN 'D3 — MODERATE LOSS'
            WHEN profit_decile <= 5 THEN 'D4-D5 — BREAK-EVEN ZONE'
            WHEN profit_decile <= 7 THEN 'D6-D7 — MARGINALLY PROFITABLE'
            WHEN profit_decile <= 9 THEN 'D8-D9 — HEALTHY PROFIT'
            ELSE                        'D10 — TOP PERFORMERS'
        END AS decile_label
    FROM decile_summary
)

-- Step 4: Final output with executive-ready framing
SELECT
    profit_decile,
    decile_label,
    order_count,
    total_revenue,
    total_profit,
    avg_profit_per_order,
    avg_margin_pct,
    avg_discount_pct,
    total_discount_bleed,
    pct_of_total_revenue,
    pct_of_total_profit,
    ROUND(cumulative_profit, 2)    AS cumulative_profit
FROM decile_labeled
ORDER BY profit_decile ASC;

-- Supplementary: Category breakdown of BOTTOM DECILE orders
-- Answers: "Which categories generate the most value-destroying D1 orders?"
SELECT
    category,
    sub_category,
    region,
    COUNT(*)                            AS d1_order_count,
    ROUND(SUM(profit), 2)               AS d1_total_profit_loss,
    ROUND(AVG(discount) * 100, 2)       AS d1_avg_discount_pct,
    ROUND(AVG(profit_margin_pct), 2)    AS d1_avg_margin_pct
FROM order_deciles
WHERE profit_decile = 1            -- Bottom 10% only
GROUP BY category, sub_category, region
ORDER BY d1_total_profit_loss ASC; -- Worst offenders first


-- =============================================================================
-- QUERY 4: MULTI-TOUCH COHORT SUMMARY — YoY Revenue & Margin Growth (LAG)
-- =============================================================================
-- Business Rationale:
--   Point-in-time metrics are meaningless without directional context.
--   A 12% margin sounds good — until you learn it was 18% last year.
--   This query builds a Year-over-Year (YoY) growth table using LAG() to:
--     (a) Compare current year revenue and margin vs. prior year
--     (b) Compute YoY growth rates for the executive dashboard
--     (c) Segment by Category to show which business units are improving
--   The LAG approach is superior to a self-join because it handles an
--   arbitrary number of years without schema changes.
-- =============================================================================

WITH

-- Step 1: Annual aggregation by category
-- Note: We use order_year (derived column from Module 1 feature engineering)
annual_category_metrics AS (
    SELECT
        order_year,
        category,

        COUNT(DISTINCT order_id)               AS total_orders,
        COUNT(*)                               AS total_line_items,
        ROUND(SUM(sales), 2)                   AS total_revenue,
        ROUND(SUM(profit), 2)                  AS total_profit,
        ROUND(SUM(discount_loss_amount), 2)    AS total_discount_bleed,

        -- Blended margin at year × category grain
        ROUND(
            CASE
                WHEN SUM(sales) = 0 THEN NULL
                ELSE (SUM(profit) / SUM(sales)) * 100
            END, 4
        ) AS blended_margin_pct,

        -- Average order value (AOV) — key retail health metric
        ROUND(SUM(sales) / NULLIF(COUNT(DISTINCT order_id), 0), 2) AS avg_order_value,

        -- Average discount rate
        ROUND(AVG(discount) * 100, 2) AS avg_discount_pct

    FROM orders
    GROUP BY order_year, category
),

-- Step 2: Apply LAG() to pull the prior year's values alongside current year
-- LAG(expr, 1) looks back exactly 1 partition row (i.e., 1 year earlier)
-- PARTITION BY category ensures year-over-year comparison stays within category
yoy_comparison AS (
    SELECT
        order_year,
        category,
        total_orders,
        total_revenue,
        total_profit,
        total_discount_bleed,
        blended_margin_pct,
        avg_order_value,
        avg_discount_pct,

        -- Prior year values via LAG
        LAG(total_revenue, 1)     OVER (PARTITION BY category ORDER BY order_year) AS prev_year_revenue,
        LAG(total_profit, 1)      OVER (PARTITION BY category ORDER BY order_year) AS prev_year_profit,
        LAG(blended_margin_pct,1) OVER (PARTITION BY category ORDER BY order_year) AS prev_year_margin_pct,
        LAG(avg_discount_pct, 1)  OVER (PARTITION BY category ORDER BY order_year) AS prev_year_discount_pct,
        LAG(avg_order_value, 1)   OVER (PARTITION BY category ORDER BY order_year) AS prev_year_aov,
        LAG(order_year, 1)        OVER (PARTITION BY category ORDER BY order_year) AS prior_year

    FROM annual_category_metrics
),

-- Step 3: Compute YoY growth rates and directional signals
yoy_growth AS (
    SELECT
        order_year,
        category,
        total_orders,
        total_revenue,
        prev_year_revenue,
        total_profit,
        prev_year_profit,
        blended_margin_pct,
        prev_year_margin_pct,
        avg_discount_pct,
        prev_year_discount_pct,
        avg_order_value,
        prev_year_aov,
        total_discount_bleed,

        -- YoY Revenue Growth %
        ROUND(
            CASE
                WHEN prev_year_revenue IS NULL OR prev_year_revenue = 0 THEN NULL
                ELSE ((total_revenue - prev_year_revenue) / prev_year_revenue) * 100
            END, 2
        ) AS revenue_yoy_growth_pct,

        -- YoY Profit Growth %
        ROUND(
            CASE
                WHEN prev_year_profit IS NULL OR prev_year_profit = 0 THEN NULL
                -- Handle sign change (negative -> positive is not a simple % calc)
                WHEN prev_year_profit < 0 AND total_profit > 0
                    THEN 100.0   -- Treat as 100% recovery (improvement)
                WHEN prev_year_profit < 0 AND total_profit < 0
                    THEN ((ABS(total_profit) - ABS(prev_year_profit)) / ABS(prev_year_profit)) * 100
                ELSE ((total_profit - prev_year_profit) / ABS(prev_year_profit)) * 100
            END, 2
        ) AS profit_yoy_growth_pct,

        -- Margin expansion / contraction (percentage POINT change, not % change)
        ROUND(
            blended_margin_pct - COALESCE(prev_year_margin_pct, blended_margin_pct), 2
        ) AS margin_point_change,

        -- Discount rate drift — are we discounting more or less than last year?
        ROUND(
            avg_discount_pct - COALESCE(prev_year_discount_pct, avg_discount_pct), 2
        ) AS discount_rate_drift_pct,

        -- AOV trajectory
        ROUND(
            CASE
                WHEN prev_year_aov IS NULL OR prev_year_aov = 0 THEN NULL
                ELSE ((avg_order_value - prev_year_aov) / prev_year_aov) * 100
            END, 2
        ) AS aov_yoy_growth_pct

    FROM yoy_comparison
),

-- Step 4: Apply business health signals for executive dashboard RAG status
yoy_final AS (
    SELECT
        *,
        -- Revenue trend signal
        CASE
            WHEN revenue_yoy_growth_pct IS NULL          THEN 'BASELINE YEAR'
            WHEN revenue_yoy_growth_pct >= 10            THEN 'STRONG GROWTH'
            WHEN revenue_yoy_growth_pct BETWEEN 0 AND 10 THEN 'MODEST GROWTH'
            WHEN revenue_yoy_growth_pct BETWEEN -10 AND 0 THEN 'MILD DECLINE'
            ELSE                                              'SIGNIFICANT DECLINE'
        END AS revenue_trend_signal,

        -- Margin health signal — did profitability improve or compress?
        CASE
            WHEN margin_point_change IS NULL OR margin_point_change = 0 THEN 'STABLE'
            WHEN margin_point_change > 2   THEN 'EXPANDING'
            WHEN margin_point_change > 0   THEN 'SLIGHTLY EXPANDING'
            WHEN margin_point_change > -2  THEN 'COMPRESSING'
            ELSE                                'RAPID COMPRESSION — ALERT'
        END AS margin_trend_signal,

        -- Combined executive health score (RAG)
        CASE
            WHEN revenue_yoy_growth_pct >= 5 AND margin_point_change >= 0  THEN 'GREEN — HEALTHY'
            WHEN revenue_yoy_growth_pct >= 0 OR  margin_point_change >= 0  THEN 'AMBER — WATCH'
            ELSE                                                                 'RED — INTERVENTION'
        END AS executive_rag_status

    FROM yoy_growth
)

-- Step 5: Final output — the executive YoY dashboard table
SELECT
    order_year                        AS fiscal_year,
    category,
    total_orders,
    total_revenue,
    prev_year_revenue,
    revenue_yoy_growth_pct,
    total_profit,
    prev_year_profit,
    profit_yoy_growth_pct,
    blended_margin_pct,
    prev_year_margin_pct,
    margin_point_change,
    avg_discount_pct,
    discount_rate_drift_pct,
    total_discount_bleed,
    avg_order_value,
    aov_yoy_growth_pct,
    revenue_trend_signal,
    margin_trend_signal,
    executive_rag_status
FROM yoy_final
ORDER BY
    category ASC,
    order_year ASC;
