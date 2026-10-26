# MODULE 4: BI Dashboard Specification
## Retail Margin & Inventory Leakage — Last-Mile Decision Engine
### Power BI / Tableau — 3-Page Interactive Dashboard

---

> [!IMPORTANT]
> **Data Source**: Connect to `data/processed/superstore_clean.csv` or `data/db/superstore.db → orders table`.  
> All DAX formulas are written for **Power BI**. Tableau Calculated Field equivalents are provided inline.

---

## DAX MEASURE LIBRARY (Define in a dedicated `_Measures` table)

These 4 foundational measures power every visual on all 3 pages.  
Create them **first** before building any visuals.

```dax
// ─────────────────────────────────────────────────────────
// MEASURE 1: Blended Profit Margin %
// Uses SUM/SUM (not AVERAGE of margin %) to avoid Simpson's Paradox.
// Denominator guard: DIVIDE() returns BLANK() when Sales = 0.
// ─────────────────────────────────────────────────────────
[Blended Profit Margin %] =
DIVIDE(
    SUM( orders[profit] ),
    SUM( orders[sales] ),
    BLANK()
) * 100


// ─────────────────────────────────────────────────────────
// MEASURE 2: Total Discount Dollar Bleed
// Aggregate of all revenue foregone due to applied discounts.
// Sourced from the engineered column discount_loss_amount in data_pipeline.py.
// ─────────────────────────────────────────────────────────
[Total Discount Dollar Bleed] =
SUM( orders[discount_loss_amount] )


// ─────────────────────────────────────────────────────────
// MEASURE 3: Average Fulfillment Days
// Average shipping lag across all orders in the current filter context.
// AVERAGEX over the table handles NULL/BLANK rows cleanly.
// ─────────────────────────────────────────────────────────
[Average Fulfillment Days] =
AVERAGEX(
    FILTER( orders, NOT ISBLANK( orders[shipping_duration_days] ) ),
    orders[shipping_duration_days]
)


// ─────────────────────────────────────────────────────────
// MEASURE 4: Loss-Making Transaction Count
// Count of individual order line items where profit is strictly negative.
// COUNTROWS + FILTER is preferred over COUNTIF for DAX performance.
// ─────────────────────────────────────────────────────────
[Loss-Making Transaction Count] =
COUNTROWS(
    FILTER( orders, orders[profit] < 0 )
)


// ─────────────────────────────────────────────────────────
// SUPPORTING MEASURES (used in specific visuals)
// ─────────────────────────────────────────────────────────

[Gross Sales] =
SUM( orders[sales] )

[Net Profit] =
SUM( orders[profit] )

[Total Orders] =
DISTINCTCOUNT( orders[order_id] )

[Avg Discount %] =
AVERAGE( orders[discount] ) * 100

[Blended Margin % PY] =                        // Prior Year — for YoY card delta
CALCULATE(
    [Blended Profit Margin %],
    DATEADD( orders[order_date], -1, YEAR )
)

[Margin YoY Delta pp] =                         // Percentage POINT change
[Blended Profit Margin %] - [Blended Margin % PY]

[Revenue YoY Growth %] =
DIVIDE(
    [Gross Sales] - CALCULATE( [Gross Sales], DATEADD( orders[order_date], -1, YEAR ) ),
    CALCULATE( [Gross Sales], DATEADD( orders[order_date], -1, YEAR ) ),
    BLANK()
) * 100

[High Risk Alert Count] =                       // For Page 3 alert badge
CALCULATE(
    COUNTROWS( orders ),
    orders[primary_action_code] <> "NO_ACTION"
)
```

> **Tableau Equivalents:**
> - `[Blended Profit Margin %]` → `SUM([Profit]) / SUM([Sales]) * 100`
> - `[Total Discount Dollar Bleed]` → `SUM([Discount Loss Amount])`
> - `[Average Fulfillment Days]` → `AVG([Shipping Duration Days])`
> - `[Loss-Making Transaction Count]` → `COUNTD(IF [Profit] < 0 THEN [Order Id] END)`

---

## PAGE 1: Executive Margin & Revenue Health
### Strategic Overview — Audience: C-Suite, VP of Retail, CFO

**Layout**: 2×2 grid top row (KPI cards) + full-width middle row + 2-column bottom row  
**Color Palette**: Dark navy `#0D1B2A` background | Accent: Amber `#F4A261` | Positive: Teal `#2EC4B6` | Negative: Red `#E63946`

---

### Visual 1 — KPI Summary Metric Cards
**Type**: Card visuals (4 cards in a row)

| Card | Measure | Subtitle | Format | Alert Condition |
|------|---------|----------|--------|-----------------|
| Gross Sales | `[Gross Sales]` | vs Prior Year | `$#,##0.0K` | None |
| Net Profit | `[Net Profit]` | Margin: `[Blended Profit Margin %]` | `$#,##0.0K` | Red if < 0 |
| Blended Margin % | `[Blended Profit Margin %]` | YoY Delta: `[Margin YoY Delta pp]` pp | `0.0%` | Red if < 5%, Amber 5–12%, Green > 12% |
| Discount Loss | `[Total Discount Dollar Bleed]` | % of Gross Sales | `$#,##0.0K` | Amber if > 10% of Gross Sales |

**DAX — Discount Loss as % of Revenue (for card subtitle):**
```dax
[Discount Loss % of Revenue] =
DIVIDE( [Total Discount Dollar Bleed], [Gross Sales], 0 ) * 100
```

**Conditional Formatting Rule (Net Profit card background):**
```dax
// Returns hex color string for background color rule
[KPI Profit Color] =
IF( [Net Profit] < 0, "#E63946", IF( [Blended Profit Margin %] < 8, "#F4A261", "#2EC4B6" ) )
```

---

### Visual 2 — Waterfall Chart (Profit Leakage Bridge)
**Type**: Waterfall / Bridge chart  
**Title**: "Where Does Gross Revenue Go?"  
**Business Purpose**: Makes the abstract concept of margin leakage viscerally visible to non-analysts.

**Category Axis (X)**: Manually ordered sequence:
1. `Gross List Price` (= `SUM(original_list_price)`)
2. `Discount Applied` (negative bar = `-[Total Discount Dollar Bleed]`)
3. `Net Sales Revenue` (running subtotal)
4. `Cost of Goods` (negative bar = `[Net Profit] - [Gross Sales]` as proxy)
5. `Net Profit` (final bar)

**Values**: Corresponding measures per category above  
**Color Rules**:  
- Positive/increase bars → Teal `#2EC4B6`  
- Negative/decrease bars → Red `#E63946`  
- Subtotal bars → Amber `#F4A261`

**DAX — Gross List Price:**
```dax
[Total Original List Price] =
SUM( orders[original_list_price] )
```

> **Tableau**: Use a Gantt bar chart with calculated running sum fields to simulate a waterfall.

---

### Visual 3 — Filled Geographic Map (State-Level Margin Health)
**Type**: Filled Map / Choropleth  
**Field Mapping**:

| Slot | Field |
|------|-------|
| Location | `orders[state]` |
| Color Saturation | `[Blended Profit Margin %]` |
| Tooltip | State, Gross Sales, Net Profit, Margin %, Alert Count |

**Color Scale**: Diverging  
- Min (most negative margin): `#E63946` (Red)  
- Midpoint (0%): `#FFD166` (Yellow)  
- Max (highest margin): `#2EC4B6` (Teal)  
- Midpoint value: `0` (fixed, not auto-centered)

**DAX — State Alert Count (for tooltip):**
```dax
[State Alert Count] =
CALCULATE(
    [High Risk Alert Count],
    ALLEXCEPT( orders, orders[state] )
)
```

---

### Visual 4 — Dual-Axis Combination Chart
**Type**: Clustered Column + Line combo  
**X-Axis**: `orders[order_year]` + `orders[order_month]` (hierarchy, month-level drill)  
**Primary Y-Axis (columns)**: `[Gross Sales]` — Teal `#2EC4B6` fill  
**Secondary Y-Axis (line)**: `[Blended Profit Margin %]` — Amber `#F4A261`, 2.5px line  
**Data Labels**: Enable on line series only (margin %, formatted `0.0%`)

**DAX — Monthly Revenue (for axis label formatting):**
```dax
[Month Label] =
FORMAT( orders[order_date], "MMM YYYY" )
```

**Interaction Behavior**: This chart acts as a **cross-filter source** for Visuals 3 and 5.  
Clicking a month bar filters the map to show only that period's margin geography.

---
---

## PAGE 2: Category & Pricing Diagnostics
### Tactical Deep Dive — Audience: Category Managers, Pricing Analysts, Merchandise Buyers

**Layout**: Top half — 2 visuals side-by-side | Bottom — 1 full-width  
**Slicer Panel** (left sidebar, 180px): Category (multi-select), Region (multi-select), Year

---

### Visual 5 — Quadrant Scatter / Bubble Plot
**Type**: Scatter chart  
**Title**: "Discount Rate vs. Profit Margin — The Pricing Quadrant"  
**Business Purpose**: Instantly shows which sub-categories are high-discount/low-margin (danger zone) vs. low-discount/high-margin (healthy).

**Field Mapping**:

| Slot | Field | Notes |
|------|-------|-------|
| X-Axis | `[Avg Discount %]` | Per sub-category |
| Y-Axis | `[Blended Profit Margin %]` | Per sub-category |
| Bubble Size | `[Gross Sales]` | Larger bubble = higher revenue |
| Color / Legend | `orders[category]` | 3 colors: Furniture=Amber, Tech=Teal, Office=Purple |
| Play Axis (optional) | `orders[order_year]` | Animate over years |
| Tooltip | Sub-Category, Sales, Profit, Margin%, Discount%, Alert Status |

**Reference Lines** (create 4 constant lines to define quadrants):
- Vertical line at X = `20` (20% avg discount threshold)
- Horizontal line at Y = `0` (break-even margin)

**Quadrant Labels** (text boxes overlaid):
- Top-Left → **"STAR: Low Discount, High Margin"** (Green tint)
- Top-Right → **"MONITOR: High Discount, Still Profitable"** (Amber tint)
- Bottom-Left → **"INVESTIGATE: Low Discount, Negative Margin"** (Orange tint)
- Bottom-Right → **"DANGER ZONE: High Discount + Margin Bleed"** (Red tint)

---

### Visual 6 — Horizontal Stacked Bar Chart (Sub-Category Profitability Ranking)
**Type**: Horizontal bar chart  
**Title**: "Sub-Category Net Profit — Loss Leaders Highlighted"  
**Sort**: Ascending by `[Net Profit]` (worst at top, best at bottom)

**Field Mapping**:

| Slot | Field |
|------|-------|
| Y-Axis | `orders[sub_category]` |
| X-Axis | `[Net Profit]` |
| Color | Conditional — see rule below |
| Data Labels | Enabled, format `$#,##0` |
| Tooltip | Sub-Category, Category, Revenue, Profit, Margin%, Discount Loss |

**Conditional Color Rule (bar fill)**:
```dax
[Bar Color Rule] =
SWITCH(
    TRUE(),
    [Net Profit] < -500,    "#E63946",    // Critical red
    [Net Profit] < 0,       "#F4A261",    // Warning amber
    [Net Profit] < 500,     "#FFD166",    // Caution yellow
    "#2EC4B6"                             // Healthy teal
)
```

**DAX — Loss Leader Flag (for conditional bold label):**
```dax
[Is Loss Leader] =
IF( [Net Profit] < 0, "LOSS LEADER", "" )
```

---

### Visual 7 — Treemap
**Type**: Treemap  
**Title**: "Revenue Footprint by Category → Sub-Category"  
**Business Purpose**: Reveals the SIZE of each sub-category's revenue contribution AND its margin health simultaneously — in one glance.

**Field Mapping**:

| Slot | Field | Notes |
|------|-------|-------|
| Group (Level 1) | `orders[category]` | Top-level hierarchy |
| Details (Level 2) | `orders[sub_category]` | Drill-down level |
| Values (tile size) | `[Gross Sales]` | Larger tile = more revenue |
| Color Saturation | `[Blended Profit Margin %]` | Same diverging scale as map |
| Tooltip | Category, Sub-Category, Sales, Profit, Margin%, Discount% |

**Color Scale**: Match Visual 3 (Red → Yellow → Teal, anchored at 0%)  
**Interaction**: Clicking a tile cross-filters Visual 6 and Visual 5.

---
---

## PAGE 3: Frontline Operations & Last-Mile Action Center
### Execution Layer — Audience: Store Managers, Operations Center, Category Buyers

> [!NOTE]
> This page implements Tredence's "Last-Mile Decision" philosophy.  
> Every element is designed for **sub-10-second comprehension** by a non-analyst operator.

**Layout**: Top row — 2 KPI tiles + 1 alert badge | Middle — heatmap + histogram side-by-side | Bottom — full-width alert table  
**Color Palette**: Dark operational feel — `#111827` background | Alert Red `#EF4444` | Safe Green `#10B981` | Warning Amber `#F59E0B`

---

### Visual 8 — Heatmap Matrix (Shipping Delay by Region × Ship Mode)
**Type**: Matrix visual configured as heatmap  
**Title**: "Avg Fulfillment Days — Regional Bottleneck Map"

**Field Mapping**:

| Slot | Field |
|------|-------|
| Rows | `orders[region]` |
| Columns | `orders[ship_mode]` |
| Values | `[Average Fulfillment Days]` |
| Cell Color | Conditional formatting on values |

**Conditional Formatting (background color on cell values)**:
```dax
// Rule applied to the [Average Fulfillment Days] measure in the matrix
// Green = fast, Red = slow
[Heatmap Cell Color] =
SWITCH(
    TRUE(),
    [Average Fulfillment Days] <= 2,  "#10B981",   // Green: within SLA
    [Average Fulfillment Days] <= 4,  "#84CC16",   // Light green: acceptable
    [Average Fulfillment Days] <= 6,  "#F59E0B",   // Amber: monitor
    [Average Fulfillment Days] <= 8,  "#F97316",   // Orange: at risk
    "#EF4444"                                      // Red: SLA breach
)
```

**Data Labels**: Enabled, format `0.0 "days"`, white font  
**Grand Total**: Disabled (confusing for a heatmap context)  
**Row/Column Total**: Enabled as a margin summary row/column

---

### Visual 9 — Histogram (Fulfillment Lag Distribution)
**Type**: Clustered bar chart configured as histogram (using bins)  
**Title**: "Fulfillment Lag Distribution — SLA Breach Frequency"  
**Business Purpose**: Shows whether slow shipments are outliers or systemic.

**Bin Configuration** — Create a calculated column:
```dax
// Calculated Column in 'orders' table
shipping_lag_bin =
SWITCH(
    TRUE(),
    orders[shipping_duration_days] <= 1,  "0-1 Days (Optimal)",
    orders[shipping_duration_days] <= 3,  "2-3 Days (Target)",
    orders[shipping_duration_days] <= 5,  "4-5 Days (Acceptable)",
    orders[shipping_duration_days] <= 7,  "6-7 Days (At Risk)",
    "8+ Days (SLA Breach)"
)
```

**Field Mapping**:

| Slot | Field |
|------|-------|
| X-Axis | `orders[shipping_lag_bin]` (sort by bin order, not alpha) |
| Y-Axis | Count of `orders[order_id]` |
| Color | Per bin — Green / Light-Green / Yellow / Orange / Red |
| Data Labels | Enabled — show count + % of total |

**Bin Sort Order** (custom sort, not alphabetical):
1. `0-1 Days (Optimal)`
2. `2-3 Days (Target)`
3. `4-5 Days (Acceptable)`
4. `6-7 Days (At Risk)`
5. `8+ Days (SLA Breach)`

**DAX — SLA Breach % (for callout annotation):**
```dax
[SLA Breach Rate %] =
DIVIDE(
    COUNTROWS( FILTER( orders, orders[shipping_duration_days] > 5 ) ),
    [Total Orders],
    0
) * 100
```

---

### Visual 10 — Actionable Alert Queue Table
**Type**: Table visual (Power BI) / Text table (Tableau)  
**Title**: "Frontline Action Queue — Prioritized by Risk Score"  
**Data Source**: Connect to `alerts/frontline_action_queue.csv` as a second data source / table

**Column Configuration**:

| Column | Field | Format | Width |
|--------|-------|--------|-------|
| Priority | `alert_priority` | Integer, center-aligned | 60px |
| Order ID | `order_id` | Text | 120px |
| Action Code | `primary_action_code` | **Conditional badge** (see below) | 160px |
| Category | `category` | Text | 120px |
| Sub-Category | `sub_category` | Text | 130px |
| Region | `region` | Text | 80px |
| Sales | `sales` | `$#,##0.00` | 100px |
| Profit | `profit` | `$#,##0.00` + conditional red if < 0 | 100px |
| Margin % | `profit_margin_pct` | `0.0%` + conditional color | 90px |
| Discount | `discount` | `0%` + conditional amber if > 30% | 80px |
| Shipping Days | `shipping_duration_days` | Integer | 100px |
| Owner | `alert_owner` | Text, italic | 180px |
| SLA | `alert_sla_hours` | `0 "hrs"` | 70px |
| Rationale | `alert_rationale` | Wrapped text, 90% opacity | 300px |

**Conditional Formatting Rules:**

```dax
// ACTION CODE BADGE — background color of the 'primary_action_code' column
[Action Badge Color] =
SWITCH(
    SELECTEDVALUE( frontline_action_queue[primary_action_code] ),
    "FREEZE_DISCOUNT", "#7C3AED",    // Purple — pricing action
    "AUDIT_FREIGHT",   "#0369A1",    // Blue — logistics action
    "URGENT_RESTOCK",  "#B45309",    // Brown — inventory action
    "#6B7280"                        // Gray — fallback
)

// PROFIT CELL — font color
[Profit Font Color] =
IF(
    SELECTEDVALUE( frontline_action_queue[profit] ) < 0,
    "#EF4444",   // Red for losses
    "#10B981"    // Green for gains
)

// MARGIN % CELL — background color
[Margin Cell Color] =
SWITCH(
    TRUE(),
    SELECTEDVALUE( frontline_action_queue[profit_margin_pct] ) <= -20, "#EF4444",
    SELECTEDVALUE( frontline_action_queue[profit_margin_pct] ) < 0,    "#F97316",
    SELECTEDVALUE( frontline_action_queue[profit_margin_pct] ) < 10,   "#F59E0B",
    "#10B981"
)

// ROW-LEVEL HIGHLIGHT — rows with 2+ rules triggered
[Row Highlight Color] =
IF(
    SELECTEDVALUE( frontline_action_queue[rules_triggered_count] ) >= 2,
    "#1F1035",   // Dark purple tint for multi-rule rows
    "#111827"    // Default dark background
)
```

**Sort Order**: `alert_priority` ASC, `composite_risk_score` DESC (most critical at top)  
**Row Limit**: Top 50 by default (managers should not scroll past 50)  
**Interaction**: Clicking a row cross-filters Visual 8 (highlights that region in the heatmap)

**DAX — Summary callout above the table (3 KPI tiles on Page 3 top):**
```dax
[Freeze Discount Count] =
CALCULATE( COUNTROWS( frontline_action_queue ),
           frontline_action_queue[primary_action_code] = "FREEZE_DISCOUNT" )

[Audit Freight Count] =
CALCULATE( COUNTROWS( frontline_action_queue ),
           frontline_action_queue[primary_action_code] = "AUDIT_FREIGHT" )

[Urgent Restock Count] =
CALCULATE( COUNTROWS( frontline_action_queue ),
           frontline_action_queue[primary_action_code] = "URGENT_RESTOCK" )
```

---

## CROSS-PAGE FEATURES

### Slicers (Sync across all 3 pages)
| Slicer | Type | Default |
|--------|------|---------|
| Date Range | Date picker (Order Date) | Last 12 months |
| Category | Dropdown multi-select | All |
| Region | Dropdown multi-select | All |
| Alert Status | Toggle: "All" / "Alerts Only" | All |

### Navigation Buttons
Create 3 buttons at the top of every page using **Bookmarks**:
- `[Page 1] Executive Overview` — links to Page 1
- `[Page 2] Category Diagnostics` — links to Page 2
- `[Page 3] Frontline Action Center` — links to Page 3

### Tooltip Page
Create a 4th page marked as a **Tooltip Page** (`320×200px`).  
It appears on hover over any order-level visual showing:
- Order ID, Product Name, Alert Status, Rules Triggered, Action Code, SLA

---

## TABLEAU EQUIVALENTS QUICK REFERENCE

| Power BI Feature | Tableau Equivalent |
|---|---|
| Measure table | Create Calculated Fields in any sheet |
| Conditional formatting | Color encoding with stepped color scale |
| Waterfall chart | Gantt chart with running sum calculated fields |
| KPI card | BANs (Big Ass Numbers) using a text mark |
| Cross-filter click | Dashboard Actions → Filter |
| Bookmark navigation | Dashboard Buttons with Navigate to Sheet action |
| `DATEADD` in DAX | `DATEADD('Order Date', -1, 'year')` in LOD calc |
| `ALLEXCEPT` | Fixed LOD: `{FIXED [State] : SUM([Profit])}` |

---

## DATA MODEL SETUP

```
orders (main fact table)
  └── order_date → Date Table (auto-calendar or custom)
         └── year, quarter, month, week fields

frontline_action_queue (from alerts/frontline_action_queue.csv)
  └── Join key: order_id → orders[order_id]
  └── Relationship: Many-to-One (queue is a subset of orders)
```

**Recommended Power BI Model View settings:**
- Hide all raw flag columns (`high_discount_flag`, `margin_bleed_flag`, etc.) from report view — expose only measures
- Mark `order_date` as a Date table
- Set `order_id` as the row-level identifier

---

## PERFORMANCE OPTIMIZATION NOTES

> [!TIP]
> For datasets >500K rows, apply these optimizations before publishing:
> - Set all string columns to **categorical** data type in Power Query
> - Use **Import mode** (not DirectQuery) for the cleaned CSV
> - Pre-aggregate the alert queue table — it should have <10K rows
> - Disable auto date/time hierarchies in Power BI Options (uses pre-built `order_year`, `order_month` columns instead)
> - Keep calculated columns in the Python pipeline (`data_pipeline.py`) — not in DAX — DAX calculated columns hold memory for every row
