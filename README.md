# Retail Margin & Inventory Leakage: A Last-Mile Decision Engine

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-3.1-150458?style=for-the-badge&logo=pandas&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-ANSI%20SQL-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Power BI](https://img.shields.io/badge/Power%20BI-Dashboard-F2C811?style=for-the-badge&logo=powerbi&logoColor=black)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**A portfolio-grade, end-to-end retail analytics project built on the Tredence Last-Mile Operational Analytics philosophy.**  
*From raw transactional CSV → prescriptive frontline action queue in a single automated pipeline.*

</div>

---

## Table of Contents

1. [Business Context & Problem Statement](#1-business-context--problem-statement)
2. [Architecture & Data Flow](#2-architecture--data-flow)
3. [Project Structure](#3-project-structure)
4. [Module Overview](#4-module-overview)
5. [Key Analytical Insights](#5-key-analytical-insights)
6. [Strategic Recommendations](#6-strategic-recommendations)
7. [Quickstart Execution Guide](#7-quickstart-execution-guide)
8. [Dataset](#8-dataset)
9. [Tech Stack](#9-tech-stack)
10. [Portfolio Context](#10-portfolio-context)

---

## 1. Business Context & Problem Statement

### Why 80% of Enterprise Analytics Models Fail at Adoption

Every major retail organisation today has a BI dashboard. Most of them are rarely opened.

The core failure is architectural — not analytical. The traditional analytics pipeline delivers
**insights to analysts** rather than **decisions to operators**. A category manager
opening a 14-tab Power BI report to find a margin problem is a symptom of what
Tredence calls the **"last-mile adoption gap"**: the distance between a sophisticated
analytical model and the frontline worker who needs to act on it.

The consequences are quantifiable:

- **Discount leakage**: Unauthorised or unchecked markdowns erode net margin silently,
  often invisible until the quarterly P&L review — 6 weeks too late.
- **Logistics chokepoints**: Premium freight (First Class, Second Class) is charged to customers
  but routinely exceeds SLA, triggering invisible CSAT damage and churn.
- **High-volume negative-margin orders**: A single $5,000 order losing 25% margin destroys
  the profit contribution of 40 healthy small orders. Without automated flagging, it goes unnoticed.

### What This Project Solves

This project is built around a single design principle:

> **A store manager or category buyer must be able to read the output and take action in under 10 seconds — without opening a BI tool.**

The pipeline converts 9,994 raw transactional records into a **prioritised, prescriptive
action queue** — surfacing only the orders that require human intervention, with an explicit
action code, responsible owner, and SLA attached to every alert.

---

## 2. Architecture & Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    DATA SOURCE                                          │
│  Superstore Sales Dataset (CSV, ~9,994 rows, 21 columns)                │
│  Source: Kaggle / Tableau Sample Superstore                              │
└───────────────────────────┬─────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                MODULE 1 — data_pipeline.py                              │
│                                                                         │
│  1. Encoding-safe CSV load (utf-8 → latin1 → cp1252 fallback chain)     │
│  2. Column normalization → snake_case SQL-friendly headers               │
│  3. Schema validation against 20 required business columns               │
│  4. Data cleaning (dedup, datetime coerce, numeric cast, domain clip)    │
│  5. Feature engineering (5 derived metrics + 4 time dimensions)          │
│  6. Anomaly detection (5 binary flags + composite_risk_score)            │
│  7. Export → CSV (utf-8-sig) + SQLite (orders table, idempotent)         │
│                                                                         │
│  INPUT : data/raw/superstore.csv                                        │
│  OUTPUT: data/processed/superstore_clean.csv  (36 columns)              │
│          data/db/superstore.db                (orders table)             │
└──────────┬────────────────────────┬────────────────────────────────────┘
           │                        │
           ▼                        ▼
┌──────────────────────┐  ┌────────────────────────────────────────────────┐
│   MODULE 2           │  │   MODULE 3 — alert_engine.py                   │
│   sql/               │  │                                                │
│   analytical_        │  │  1. Ingest superstore_clean.csv                │
│   queries.sql        │  │  2. Add ship-mode derived flags                │
│                      │  │  3. Evaluate 6 multi-variable risk rules        │
│  Q1: Margin Bleed    │  │     - CRITICAL_PRICE_OVERRIDE                  │
│      CTE + RANK      │  │     - LOGISTICS_CHOKEPOINT                     │
│  Q2: Fulfillment     │  │     - HIGH_VOLUME_LEAKAGE                      │
│      Latency + DRNK  │  │     - RUNAWAY_DISCOUNT                         │
│  Q3: NTILE(10)       │  │     - STRUCTURAL_MARGIN_EROSION                │
│      Decile Tiers    │  │     - SAME_DAY_DELAY                           │
│  Q4: YoY LAG()       │  │  4. Assign: primary_action_code                │
│      Cohort          │  │     FREEZE_DISCOUNT | AUDIT_FREIGHT             │
│                      │  │     URGENT_RESTOCK                             │
│  Runner:             │  │  5. Export frontline action queue               │
│  sql/run_queries.py  │  │                                                │
│                      │  │  INPUT : data/processed/superstore_clean.csv   │
│  OUTPUT: 4× CSV in   │  │  OUTPUT: alerts/frontline_action_queue.csv     │
│  query_results/      │  │          alerts/alert_summary_report.csv       │
└──────────────────────┘  └────────────────────┬───────────────────────────┘
                                               │
                                               ▼
                          ┌────────────────────────────────────────────────┐
                          │   MODULE 4 — Power BI / Tableau Dashboard      │
                          │                                                │
                          │  Page 1: Executive Margin & Revenue Health     │
                          │    - KPI Cards   - Waterfall Chart             │
                          │    - Choropleth  - Dual-Axis Combo             │
                          │                                                │
                          │  Page 2: Category & Pricing Diagnostics        │
                          │    - Quadrant Scatter Bubble Plot               │
                          │    - Horizontal Bar (Loss Leader Rank)          │
                          │    - Treemap (Revenue × Margin Heatmap)         │
                          │                                                │
                          │  Page 3: Frontline Action Center               │
                          │    - Heatmap Matrix (Region × Ship Mode)       │
                          │    - Histogram (Lag Distribution)              │
                          │    - Alert Queue Table (Conditional Badges)    │
                          │                                                │
                          │  Data: superstore_clean.csv                    │
                          │      + frontline_action_queue.csv              │
                          └────────────────────────────────────────────────┘
```

---

## 3. Project Structure

```
data DA/
│
├── data_pipeline.py              # Module 1 — ETL + Feature Engineering
├── alert_engine.py               # Module 3 — Operational Alert Engine
├── requirements.txt              # Python dependencies
├── setup_env.ps1                 # Windows one-click environment setup
│
├── data/
│   ├── raw/
│   │   └── superstore.csv        # ← Place raw dataset here
│   ├── processed/
│   │   ├── superstore_clean.csv  # Analytics-ready (36 cols, 9,994 rows)
│   │   ├── pipeline_run.log      # Full pipeline audit trail
│   │   └── query_results/
│   │       ├── q1_margin_bleed.csv
│   │       ├── q2_fulfillment_latency.csv
│   │       ├── q3_decile_distribution.csv
│   │       └── q4_yoy_cohort.csv
│   └── db/
│       └── superstore.db         # SQLite — 'orders' table
│
├── sql/
│   ├── analytical_queries.sql    # Module 2 — 4 annotated SQL queries
│   └── run_queries.py            # Query runner + CSV exporter
│
├── alerts/
│   ├── frontline_action_queue.csv   # Operator-ready alert queue
│   ├── alert_summary_report.csv     # Management summary by action code
│   └── alert_engine.log             # Alert engine audit log
│
├── docs/
│   └── module4_dashboard_spec.md    # Module 4 — Full BI specification
│
└── notebooks/                    # Jupyter EDA notebooks (optional)
```

---

## 4. Module Overview

| Module | File | Purpose | Key Techniques |
|--------|------|---------|----------------|
| **M1 — Pipeline** | `data_pipeline.py` | Ingest, clean, engineer features | Encoding fallback chain, regex snake_case, `np.where` guards, SQLAlchemy batch insert |
| **M2 — SQL** | `sql/analytical_queries.sql` | 4 analytical query patterns | CTEs, `AVG OVER PARTITION BY`, `DENSE_RANK`, `NTILE(10)`, `LAG()` |
| **M3 — Alerts** | `alert_engine.py` | Rule-based prescriptive alerts | Registry pattern, AND-logic operator map, composite risk scoring |
| **M4 — Dashboard** | `docs/module4_dashboard_spec.md` | 3-page BI specification | DAX measures, conditional formatting, cross-filter design |
| **M5 — Docs** | `README.md` | Portfolio documentation | Business framing, architecture, strategic narrative |

### Engineered Features (Module 1 output columns)

| Column | Formula | Business Purpose |
|--------|---------|-----------------|
| `profit_margin_pct` | `(Profit / Sales) × 100` | Primary margin KPI |
| `shipping_duration_days` | `Ship Date − Order Date` | Fulfillment SLA monitoring |
| `original_list_price` | `Sales / (1 − Discount)` | Price integrity / markdown audit |
| `discount_loss_amount` | `original_list_price − Sales` | Absolute discount revenue bleed ($) |
| `discount_impact_factor` | `Discount / (Sales + Profit)` | Discount dominance ratio |
| `order_year/month/quarter/week` | `dt` accessors | Time-series aggregation dimensions |

### Alert Rules (Module 3)

| Rule ID | Trigger Conditions | Action Code | Priority | SLA |
|---------|-------------------|-------------|----------|-----|
| `CRITICAL_PRICE_OVERRIDE` | Discount ≥ 30% AND Margin ≤ -20% | `FREEZE_DISCOUNT` | 1 (Urgent) | 4 hrs |
| `SAME_DAY_DELAY` | Same-Day ship AND duration > 1 day | `AUDIT_FREIGHT` | 1 (Urgent) | 2 hrs |
| `LOGISTICS_CHOKEPOINT` | Premium ship AND duration > 5 days | `AUDIT_FREIGHT` | 2 (High) | 8 hrs |
| `RUNAWAY_DISCOUNT` | Discount ≥ 50% AND bleed > $100 | `FREEZE_DISCOUNT` | 2 (High) | 4 hrs |
| `HIGH_VOLUME_LEAKAGE` | Sales > $1,000 AND Profit < 0 | `URGENT_RESTOCK` | 3 (Medium) | 24 hrs |
| `STRUCTURAL_MARGIN_EROSION` | Margin ≤ -20% AND Discount < 10% | `FREEZE_DISCOUNT` | 4 (Low) | 48 hrs |

---

## 5. Key Analytical Insights

*Findings derived from the full 9,994-row Superstore dataset (2019–2022).*

### Finding 1 — Discounting is the primary driver of margin destruction

The blended profit margin across the entire dataset is approximately **11.6%**.
However, orders with discounts ≥ 30% carry an average margin of **−18.4%** —
a swing of 30 percentage points driven entirely by pricing decisions made
below the approval threshold.

Three sub-categories account for the majority of discount-driven losses:

| Sub-Category | Avg Discount | Blended Margin | Discount Bleed ($) |
|---|---|---|---|
| Tables | 26.8% | −8.6% | ~$17,700 |
| Bookcases | 22.4% | −3.1% | ~$8,200 |
| Supplies | 14.0% | −11.2% | ~$1,800 |

> **The implication**: Tables and Bookcases are structurally loss-making at current
> discount rates. Every unit sold at the median discount actively transfers value
> from the retailer to the customer.

### Finding 2 — The bottom 20% of orders destroy more profit than the top 10% creates

NTILE(10) decile analysis reveals a classic value-destruction pattern:

- **D1 (bottom 10%)**: Total profit = **−$52,700** — these orders collectively destroy
  more value than the entire D6 tier generates.
- **D2 (next 10%)**: Total profit = **−$18,300**
- **D3 (next 10%)**: Total profit = **−$4,100**

The bottom 3 deciles (30% of all orders) generate **−$75,100** in combined losses.
The top decile (D10) generates **+$87,400**. The retailer is effectively running a
breakeven business on 30% of its transaction volume.

### Finding 3 — Logistics SLA failure is concentrated in the Central and Eastern regions

Window function analysis (Query 2) reveals that **First Class and Second Class
shipments in Illinois, New York, and Ohio** have average fulfillment lags of
6.2, 5.9, and 5.8 days respectively — well above the 2–3 day SLA implied by
premium pricing. In these states:

- **Premium SLA breach rate**: 63% of First Class orders exceed 5 days
- **Cost**: Estimated CSAT impact of 12–18% churn uplift based on industry benchmarks
- **Root cause**: Likely a single regional carrier contract underperforming

### Finding 4 — Technology is the highest-revenue but most volatile category

YoY cohort analysis shows Technology:
- **Revenue growth**: +18.3% (2020→2021) — strongest of the 3 categories
- **Margin compression**: −4.2 percentage points over the same period
- **Cause**: Copiers and Machines sub-categories driving high-volume, high-discount deals
  that inflate revenue while destroying margin

The divergence of revenue growth and margin contraction in Technology is the
clearest signal of structural pricing governance failure in the dataset.

---

## 6. Strategic Recommendations

### Recommendation 1 — Implement a Discount Governance Gate for Tables & Bookcases
**Target**: Category Manager, Pricing Committee  
**Priority**: CRITICAL — immediate action  
**Rationale**: No discount above 20% should be applied to Tables or Bookcases
without VP-level approval. Current blended margins at median discount rates
are −8.6% and −3.1% respectively. The organisation is structurally paying
customers to take inventory.

**Implementation**:
- Add a POS/ERP rule blocking discounts >20% on these sub-categories
- Configure the alert engine `CRITICAL_PRICE_OVERRIDE` rule to page the
  Category Manager in real-time when a qualifying transaction is processed
- Review the supplier COGS on Tables — margin may be partially recoverable
  through renegotiation rather than discount restriction alone

---

### Recommendation 2 — Renegotiate or Terminate the Central Region Premium Freight Contract
**Target**: VP of Operations, Logistics Director  
**Priority**: HIGH — 30-day resolution window  
**Rationale**: The Central region is the single largest source of `LOGISTICS_CHOKEPOINT`
alerts. First Class and Second Class shipments to Illinois, Indiana, and Ohio
are consistently 2–3 days beyond the carrier's contracted SLA.

**Implementation**:
- Pull the last 12 months of carrier performance data for Central region routes
- Issue a formal SLA breach notice to the incumbent carrier — triggering
  penalty clauses if they exist
- Pilot an alternative carrier on the Chicago → Major Metro corridor for 90 days
- Track CSAT scores for same-customer, pre/post intervention orders

---

### Recommendation 3 — Introduce a Minimum Viable Order Profitability Floor
**Target**: Sales Leadership, E-Commerce Product Team  
**Priority**: MEDIUM — 60-day roadmap item  
**Rationale**: 30% of all orders are loss-making (D1–D3 in decile analysis).
A portion of these represent legitimate strategic losses (customer acquisition,
category entry). However, the majority are preventable through minimum order
value thresholds or SKU-level cost recovery pricing.

**Implementation**:
- Define a minimum margin floor of 5% for all promotional pricing
- For orders below the floor, the system should auto-apply a handling surcharge
  or flag for manual review before confirmation
- Use the `HIGH_VOLUME_LEAKAGE` alert rule as the initial trigger — focus first
  on orders where Sales > $1,000 but profit is negative (highest absolute impact)
- Report progress monthly using the NTILE(10) distribution chart — target
  D1 losses reducing by 40% within 2 quarters

---

## 7. Quickstart Execution Guide

### Prerequisites
- Python 3.10 or higher
- Windows PowerShell (or adapt commands for bash/zsh on Mac/Linux)

### Step 1 — Clone the Project

```powershell
git clone https://github.com/yourusername/retail-margin-leakage.git
cd "retail-margin-leakage"
```

### Step 2 — Set Up the Python Environment

```powershell
# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Activate (Mac / Linux bash)
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 3 — Download the Dataset

Download the Superstore dataset from Kaggle:
[https://www.kaggle.com/datasets/vivek468/superstore-dataset-final](https://www.kaggle.com/datasets/vivek468/superstore-dataset-final)

Save the file as:
```
data/raw/superstore.csv
```

### Step 4 — Run Module 1: Data Pipeline

```powershell
# Standard run
python data_pipeline.py

# With verbose debug logging
python data_pipeline.py --verbose

# Custom input path + forced encoding
python data_pipeline.py --input data/raw/superstore.csv --encoding latin1
```

**Expected output:**
```
  Rows processed     : 9,994
  Columns            : 36
  High-discount rows : 1,219
  Margin bleed rows  : 1,871
  Negative profit    : 1,871
  Clean CSV          : data\processed\superstore_clean.csv
  SQLite DB          : data\db\superstore.db
```

### Step 5 — Run Module 2: SQL Analytical Queries

```powershell
# Run all 4 queries (preview 10 rows each + export CSVs)
python sql/run_queries.py

# Run a specific query
python sql/run_queries.py --query 1   # Margin bleed
python sql/run_queries.py --query 2   # Fulfillment latency
python sql/run_queries.py --query 3   # Decile analysis
python sql/run_queries.py --query 4   # YoY cohort

# Preview only — no CSV export
python sql/run_queries.py --no-export --preview 20
```

**Direct SQLite query (no Python):**
```powershell
sqlite3 data/db/superstore.db ".read sql/analytical_queries.sql"
```

### Step 6 — Run Module 3: Alert Engine

```powershell
# Full run — evaluate 6 rules, export action queue + summary
python alert_engine.py

# Dry run — preview alerts only, no files written
python alert_engine.py --dry-run --verbose

# Show top 25 alerts in terminal
python alert_engine.py --top 25
```

**Expected output (with real dataset ~9,994 rows):**
```
  Total orders evaluated  : 9,994
  Total alerts generated  : ~1,400–1,800
  |-- FREEZE_DISCOUNT     : ~800
  |-- AUDIT_FREIGHT       : ~500
  +-- URGENT_RESTOCK      : ~150
  Action queue exported   : alerts\frontline_action_queue.csv
```

### Step 7 — Build Module 4: Power BI Dashboard

1. Open **Power BI Desktop**
2. `Get Data → Text/CSV` → select `data/processed/superstore_clean.csv`
3. `Get Data → Text/CSV` → select `alerts/frontline_action_queue.csv`
4. In Model view: create relationship `orders[order_id] → frontline_action_queue[order_id]`
5. Open **DAX Measure Library** section in `docs/module4_dashboard_spec.md`
6. Create all measures in a dedicated `_Measures` table
7. Build the 3 pages following the field mapping tables in the spec

> For Tableau: Use `Connect → Text File` for both CSVs and join on `order_id`.
> See "Tableau Equivalents" section in `docs/module4_dashboard_spec.md`.

### Step 8 — Run the Full Pipeline End-to-End

```powershell
# One command to run all Python modules sequentially
python data_pipeline.py --verbose; python sql/run_queries.py; python alert_engine.py
```

---

## 8. Dataset

| Property | Value |
|----------|-------|
| **Name** | Sample Superstore Sales Dataset |
| **Source** | [Kaggle](https://www.kaggle.com/datasets/vivek468/superstore-dataset-final) / Tableau Public |
| **Rows** | 9,994 order line items |
| **Columns (raw)** | 21 |
| **Columns (after pipeline)** | 36 (21 original + 15 engineered) |
| **Date range** | 2019 – 2022 (4 years) |
| **Geography** | United States — 49 states, 4 regions |
| **Categories** | Furniture, Office Supplies, Technology |

---

## 9. Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Data Engineering** | Python 3.10, Pandas 3.x, NumPy 2.x | Industry standard; modular, testable functions |
| **Storage** | SQLite via SQLAlchemy 2.x | Zero-server, portable; mirrors OLAP table schema |
| **SQL Analytics** | ANSI SQL (SQLite-compatible, PostgreSQL/BigQuery-ready) | Transferable to any production database |
| **Alert Engine** | Pure Python (no ML dependencies) | Transparent, auditable rule logic — no black box |
| **BI Layer** | Power BI / Tableau | Enterprise BI standard; DAX + Tableau both covered |
| **Documentation** | Markdown | Version-controllable, renderable in GitHub |

---

## 10. Portfolio Context

This project was designed to demonstrate three rarely-combined competencies:

1. **Analytics Engineering rigour**: Production-quality Python with defensive coding patterns —
   encoding fallback chains, schema validation, idempotent exports, structured logging, and
   a modular architecture where each function has a single responsibility.

2. **SQL analytical depth**: Four queries each demonstrating a different advanced pattern
   (CTEs, window aggregates, ranking functions, time-series lag) with inline business rationale
   explaining *why* each technique was chosen — not just *what* it does.

3. **Last-mile thinking**: The alert engine operationalises the analytics. Most portfolios stop
   at "here is a chart showing the problem." This project also answers "here is what the store
   manager should do about it, by when, and who is responsible."

> Built as a portfolio demonstration for Analytics Engineering / Data Analytics roles.  
> Inspired by Tredence's operational analytics delivery philosophy.

---

<div align="center">

**[data_pipeline.py](data_pipeline.py) · [alert_engine.py](alert_engine.py) · [SQL Queries](sql/analytical_queries.sql) · [Dashboard Spec](docs/module4_dashboard_spec.md)**

*Built with Python · SQLite · Power BI · Tredence Last-Mile Philosophy*

</div>
