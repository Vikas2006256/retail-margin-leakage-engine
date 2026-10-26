"""
=============================================================================
alert_engine.py  —  MODULE 3: Frontline Operational Alert Engine
=============================================================================
Project : Retail Margin & Inventory Leakage — A Last-Mile Decision Engine
Author  : Analytics Engineering Team
Version : 1.0.0
Python  : 3.10+

Philosophy (Tredence Last-Mile Adoption)
-----------------------------------------
Most analytics projects stop at insight. This engine closes the "last-mile gap"
by converting passive analytical findings into prioritized, prescriptive action
codes that a store manager or category buyer can act on in under 10 seconds —
without ever opening a BI dashboard.

The engine operates in 3 stages:
  Stage 1 — EVALUATE  : Score every order against multi-variable risk rules
  Stage 2 — TRIAGE    : Assign a single highest-priority action code per order
  Stage 3 — DISPATCH  : Export a lean, role-specific action queue CSV

Architecture Position
---------------------
  data/processed/superstore_clean.csv
        │
        ▼
  alert_engine.py              ← YOU ARE HERE
        │
        └── alerts/frontline_action_queue.csv

Usage
-----
  python alert_engine.py
  python alert_engine.py --input data/processed/superstore_clean.csv --verbose
  python alert_engine.py --dry-run    # Evaluate rules without writing output
=============================================================================
"""

# ---------------------------------------------------------------------------
# Standard Library
# ---------------------------------------------------------------------------
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Third-Party
# ---------------------------------------------------------------------------
try:
    import numpy as np
    import pandas as pd
except ImportError as e:
    sys.exit(f"[FATAL] Missing dependency: {e}\nRun: pip install pandas numpy")

# ---------------------------------------------------------------------------
# 0. CONFIGURATION
# ---------------------------------------------------------------------------

DEFAULT_INPUT_PATH  = Path("data/processed/superstore_clean.csv")
DEFAULT_OUTPUT_PATH = Path("alerts/frontline_action_queue.csv")
DEFAULT_SUMMARY_PATH = Path("alerts/alert_summary_report.csv")

# ---------------------------------------------------------------------------
# RULE REGISTRY
# ---------------------------------------------------------------------------
# Each rule is a self-contained dict. Adding or modifying a rule here
# automatically propagates through the entire evaluation engine — no other
# code needs to change.
#
# Fields:
#   rule_id      : Unique machine-readable identifier
#   display_name : Human-readable label for the frontline queue
#   priority     : 1 = highest urgency (shown first in action queue)
#   action_code  : Operational instruction for the store manager
#   conditions   : Dict of column -> (operator, threshold) pairs
#                  ALL conditions must be True for the rule to fire (AND logic)
#   rationale    : Business explanation printed in the action queue
#   owner        : Role responsible for resolving the alert
# ---------------------------------------------------------------------------

RULE_REGISTRY = [
    {
        "rule_id"     : "CRITICAL_PRICE_OVERRIDE",
        "display_name": "Critical Price Override",
        "priority"    : 1,
        "action_code" : "FREEZE_DISCOUNT",
        "conditions"  : {
            "discount"         : (">=", 0.30),
            "profit_margin_pct": ("<=", -20.0),
        },
        "rationale": (
            "Discount >= 30% has driven margin below -20%. "
            "This order is actively destroying shareholder value. "
            "Immediate pricing governance review required."
        ),
        "owner"       : "Category Manager",
        "sla_hours"   : 4,
    },
    {
        "rule_id"     : "LOGISTICS_CHOKEPOINT",
        "display_name": "Logistics Chokepoint",
        "priority"    : 2,
        "action_code" : "AUDIT_FREIGHT",
        "conditions"  : {
            "shipping_duration_days": (">",  5),
            "ship_mode_premium"     : ("==", 1),   # derived flag (First/Second Class)
        },
        "rationale": (
            "Premium freight (First/Second Class) is taking > 5 days. "
            "Customer is being charged for fast delivery that is not being fulfilled. "
            "Investigate carrier SLA breach and log a freight claim."
        ),
        "owner"       : "Logistics / Operations Manager",
        "sla_hours"   : 8,
    },
    {
        "rule_id"     : "HIGH_VOLUME_LEAKAGE",
        "display_name": "High-Volume Revenue Leakage",
        "priority"    : 3,
        "action_code" : "URGENT_RESTOCK",
        "conditions"  : {
            "sales" : (">",  1000.0),
            "profit": ("<",  0.0),
        },
        "rationale": (
            "High-revenue order (Sales > $1,000) is generating a net loss. "
            "This is a high-impact leakage event — review COGS, supplier pricing, "
            "and restock terms to prevent recurrence on reorder."
        ),
        "owner"       : "Category Buyer / Merchandise Planner",
        "sla_hours"   : 24,
    },
    {
        "rule_id"     : "RUNAWAY_DISCOUNT",
        "display_name": "Runaway Discounting",
        "priority"    : 2,
        "action_code" : "FREEZE_DISCOUNT",
        "conditions"  : {
            "discount"           : (">=", 0.50),
            "discount_loss_amount": (">",  100.0),
        },
        "rationale": (
            "Discount >= 50% is causing a discount dollar loss > $100. "
            "Unauthorized markdown or pricing system error suspected. "
            "Freeze further discounts on this SKU pending approval."
        ),
        "owner"       : "Pricing Analyst",
        "sla_hours"   : 4,
    },
    {
        "rule_id"     : "STRUCTURAL_MARGIN_EROSION",
        "display_name": "Structural Margin Erosion",
        "priority"    : 4,
        "action_code" : "FREEZE_DISCOUNT",
        "conditions"  : {
            "profit_margin_pct": ("<=", -20.0),
            "discount"         : ("<",   0.10),   # Low discount → cost problem, not pricing
        },
        "rationale": (
            "Margin < -20% despite minimal discounting. "
            "Structural cost issue detected — likely supplier COGS overrun or "
            "misaligned pricing. Escalate to Category Buyer for cost renegotiation."
        ),
        "owner"       : "Category Buyer",
        "sla_hours"   : 48,
    },
    {
        "rule_id"     : "SAME_DAY_DELAY",
        "display_name": "Same-Day Delivery Failure",
        "priority"    : 1,
        "action_code" : "AUDIT_FREIGHT",
        "conditions"  : {
            "shipping_duration_days": (">", 1),
            "ship_mode_same_day"    : ("==", 1),  # derived flag
        },
        "rationale": (
            "Same-Day delivery took more than 1 day. "
            "Customer SLA violated — immediate carrier escalation and "
            "customer satisfaction credit required."
        ),
        "owner"       : "Logistics Manager",
        "sla_hours"   : 2,
    },
]

# Priority ordering for action codes (when multiple rules fire, highest wins)
ACTION_CODE_PRIORITY = {
    "FREEZE_DISCOUNT": 1,
    "AUDIT_FREIGHT"  : 2,
    "URGENT_RESTOCK" : 3,
}

# Columns to include in the frontline output CSV — keep it lean for operators
FRONTLINE_COLUMNS = [
    "order_id",
    "order_date",
    "category",
    "sub_category",
    "product_name",
    "region",
    "state",
    "ship_mode",
    "segment",
    "sales",
    "profit",
    "discount",
    "profit_margin_pct",
    "shipping_duration_days",
    "discount_loss_amount",
    # Alert engine outputs
    "rules_triggered",
    "rules_triggered_count",
    "composite_risk_score",
    "primary_action_code",
    "alert_priority",
    "alert_display_name",
    "alert_rationale",
    "alert_owner",
    "alert_sla_hours",
    "alert_timestamp",
]

# ---------------------------------------------------------------------------
# 1. LOGGING
# ---------------------------------------------------------------------------

def configure_logging(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("alert_engine")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not logger.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] alert_engine — %(message)s",
            "%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(ch)

        Path("alerts").mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler("alerts/alert_engine.log", mode="a", encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(message)s", "%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(fh)
    return logger


# ---------------------------------------------------------------------------
# 2. DATA INGESTION
# ---------------------------------------------------------------------------

def load_clean_data(input_path: Path, logger: logging.Logger) -> pd.DataFrame:
    """
    Load the analytics-ready CSV produced by data_pipeline.py.
    Validates that all required derived columns are present.
    """
    if not input_path.exists():
        raise FileNotFoundError(
            f"Input file not found: '{input_path}'.\n"
            "Run data_pipeline.py first to generate the cleaned dataset."
        )

    df = pd.read_csv(input_path, low_memory=False, encoding="utf-8-sig")
    logger.info(f"Loaded '{input_path.name}' | Shape: {df.shape}")

    # Parse dates (they are stored as strings in the CSV)
    for col in ["order_date", "ship_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Validate required derived columns exist (produced by data_pipeline.py)
    required = [
        "order_id", "sales", "profit", "discount",
        "profit_margin_pct", "shipping_duration_days",
        "discount_loss_amount", "ship_mode",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(
            f"Missing required columns: {missing}\n"
            "Ensure data_pipeline.py ran successfully and produced all derived features."
        )

    logger.info(f"All required columns verified.")
    return df


# ---------------------------------------------------------------------------
# 3. DERIVED RULE INPUTS
# ---------------------------------------------------------------------------

def add_rule_input_features(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """
    Compute binary helper columns needed by specific rules.
    Keeps rule conditions clean and readable (no inline string matching in rules).

    ship_mode_premium  : 1 if ship mode is First Class or Second Class
    ship_mode_same_day : 1 if ship mode is Same Day
    """
    if "ship_mode" in df.columns:
        ship_mode_clean = df["ship_mode"].str.strip().str.title()

        df["ship_mode_premium"] = ship_mode_clean.isin(
            ["First Class", "Second Class"]
        ).astype(int)

        df["ship_mode_same_day"] = (
            ship_mode_clean == "Same Day"
        ).astype(int)

        logger.debug(
            f"ship_mode_premium : {df['ship_mode_premium'].sum():,} orders | "
            f"ship_mode_same_day: {df['ship_mode_same_day'].sum():,} orders"
        )
    else:
        df["ship_mode_premium"]  = 0
        df["ship_mode_same_day"] = 0
        logger.warning("'ship_mode' column not found — premium/same-day flags set to 0.")

    return df


# ---------------------------------------------------------------------------
# 4. RULE EVALUATION ENGINE
# ---------------------------------------------------------------------------

OPERATOR_MAP = {
    ">=" : lambda col, val: col >= val,
    "<=" : lambda col, val: col <= val,
    ">"  : lambda col, val: col >  val,
    "<"  : lambda col, val: col <  val,
    "==" : lambda col, val: col == val,
    "!=" : lambda col, val: col != val,
}


def evaluate_single_rule(df: pd.DataFrame, rule: dict, logger: logging.Logger) -> pd.Series:
    """
    Evaluate a single rule against the full DataFrame.
    Returns a boolean Series where True = this rule fires for that row.

    All conditions within a rule are combined with AND logic.
    This means EVERY condition must hold simultaneously for an alert to trigger,
    preventing false positives from individual metric spikes.
    """
    composite_mask = pd.Series(True, index=df.index)  # Start: all rows eligible

    for col, (operator, threshold) in rule["conditions"].items():
        if col not in df.columns:
            logger.warning(
                f"Rule '{rule['rule_id']}': condition column '{col}' not found — "
                "skipping this condition (rule may over-fire)."
            )
            continue

        op_fn     = OPERATOR_MAP.get(operator)
        if op_fn is None:
            raise ValueError(f"Unknown operator '{operator}' in rule '{rule['rule_id']}'.")

        condition_mask = op_fn(df[col], threshold)
        composite_mask = composite_mask & condition_mask

        fired = condition_mask.sum()
        logger.debug(
            f"  Rule '{rule['rule_id']}' | "
            f"condition '{col} {operator} {threshold}' | "
            f"{fired:,} rows match"
        )

    total_fired = composite_mask.sum()
    logger.info(
        f"Rule '{rule['rule_id']:<28}': "
        f"{total_fired:>5,} alerts fired "
        f"({total_fired / len(df) * 100:.1f}%)"
    )
    return composite_mask


def evaluate_all_rules(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """
    Run all rules in the RULE_REGISTRY against every order row.

    For each row, computes:
      rules_triggered       : Pipe-delimited list of all fired rule IDs
      rules_triggered_count : How many rules fired
      composite_risk_score  : Weighted score (sum of inverse priority values)
      primary_action_code   : Highest-priority action from all triggered rules
      alert_priority        : Numeric priority of the primary action
      alert_display_name    : Human-readable alert label
      alert_rationale       : Prescriptive explanation for the frontline operator
      alert_owner           : Role responsible for resolution
      alert_sla_hours       : Time-to-resolve target in hours
    """
    logger.info("=" * 60)
    logger.info(f"Evaluating {len(RULE_REGISTRY)} rules against {len(df):,} orders...")
    logger.info("=" * 60)

    # Build a matrix: one boolean column per rule
    rule_masks = {}
    for rule in RULE_REGISTRY:
        rule_masks[rule["rule_id"]] = evaluate_single_rule(df, rule, logger)

    # Aggregate across rules for each row
    rules_triggered_list   = []
    primary_action_list    = []
    alert_priority_list    = []
    alert_display_name_list = []
    alert_rationale_list   = []
    alert_owner_list       = []
    alert_sla_list         = []
    risk_score_list        = []

    # Build a lookup for rapid rule metadata access
    rule_lookup = {r["rule_id"]: r for r in RULE_REGISTRY}

    for idx in df.index:
        # Collect all rules that fired for this row
        fired_ids = [
            rule_id for rule_id, mask in rule_masks.items() if mask.loc[idx]
        ]

        if not fired_ids:
            # No alerts — clean order
            rules_triggered_list.append("")
            primary_action_list.append("NO_ACTION")
            alert_priority_list.append(99)
            alert_display_name_list.append("No Alert")
            alert_rationale_list.append("")
            alert_owner_list.append("")
            alert_sla_list.append(None)
            risk_score_list.append(0)
        else:
            # Sort fired rules by their priority (ascending = most critical first)
            fired_rules = sorted(
                [rule_lookup[rid] for rid in fired_ids],
                key=lambda r: r["priority"],
            )

            # Primary rule = highest priority rule that fired
            primary_rule = fired_rules[0]

            # Composite risk score: sum of (10 - priority) for each fired rule
            # Higher priority rules contribute MORE to the score
            score = sum(10 - r["priority"] for r in fired_rules)

            rules_triggered_list.append(" | ".join(r["rule_id"] for r in fired_rules))
            primary_action_list.append(primary_rule["action_code"])
            alert_priority_list.append(primary_rule["priority"])
            alert_display_name_list.append(primary_rule["display_name"])
            alert_rationale_list.append(primary_rule["rationale"])
            alert_owner_list.append(primary_rule["owner"])
            alert_sla_list.append(primary_rule["sla_hours"])
            risk_score_list.append(score)

    df["rules_triggered"]       = rules_triggered_list
    df["rules_triggered_count"] = df["rules_triggered"].apply(
        lambda x: len(x.split(" | ")) if x else 0
    )
    df["composite_risk_score"]  = risk_score_list
    df["primary_action_code"]   = primary_action_list
    df["alert_priority"]        = alert_priority_list
    df["alert_display_name"]    = alert_display_name_list
    df["alert_rationale"]       = alert_rationale_list
    df["alert_owner"]           = alert_owner_list
    df["alert_sla_hours"]       = alert_sla_list
    df["alert_timestamp"]       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return df


# ---------------------------------------------------------------------------
# 5. ALERT SUMMARY STATISTICS
# ---------------------------------------------------------------------------

def generate_alert_summary(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """
    Produce a concise operational summary report:
      - Alert counts per action code
      - Top impacted categories and regions
      - Estimated total financial exposure (discount bleed + profit loss)
    """
    alerted_df = df[df["primary_action_code"] != "NO_ACTION"]

    logger.info("=" * 60)
    logger.info("ALERT ENGINE — OPERATIONAL SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total orders evaluated  : {len(df):,}")
    logger.info(f"  Total alerts generated  : {len(alerted_df):,} "
                f"({len(alerted_df)/len(df)*100:.1f}%)")
    logger.info(f"  Clean orders (no alert) : {(df['primary_action_code']=='NO_ACTION').sum():,}")
    logger.info("")

    # By action code
    logger.info("  ACTION CODE BREAKDOWN:")
    action_summary = (
        alerted_df.groupby("primary_action_code")
        .agg(
            alert_count       =("order_id", "count"),
            total_revenue_at_risk=("sales", "sum"),
            total_profit_loss =("profit", lambda x: x[x < 0].sum()),
            total_discount_bleed=("discount_loss_amount", "sum"),
        )
        .round(2)
        .sort_values("alert_count", ascending=False)
    )
    for action, row in action_summary.iterrows():
        logger.info(
            f"    {action:<20} : {int(row['alert_count']):>5} alerts | "
            f"Revenue at Risk: ${row['total_revenue_at_risk']:>10,.2f} | "
            f"Profit Loss: ${row['total_profit_loss']:>8,.2f}"
        )
    logger.info("")

    # By category
    logger.info("  TOP IMPACTED CATEGORIES:")
    cat_summary = (
        alerted_df.groupby("category")
        .agg(alert_count=("order_id", "count"), profit_impact=("profit", "sum"))
        .sort_values("profit_impact")
    )
    for cat, row in cat_summary.iterrows():
        logger.info(
            f"    {cat:<20} : {int(row['alert_count']):>4} alerts | "
            f"Profit Impact: ${row['profit_impact']:>10,.2f}"
        )
    logger.info("")

    # Multi-rule orders (highest risk)
    multi_rule = alerted_df[alerted_df["rules_triggered_count"] >= 2]
    logger.info(
        f"  MULTI-RULE ORDERS (>=2 rules): {len(multi_rule):,} — "
        "these require IMMEDIATE management attention."
    )
    logger.info("=" * 60)

    return action_summary.reset_index()


# ---------------------------------------------------------------------------
# 6. EXPORT: Frontline Action Queue
# ---------------------------------------------------------------------------

def export_action_queue(
    df         : pd.DataFrame,
    output_path: Path,
    logger     : logging.Logger,
) -> pd.DataFrame:
    """
    Export the alert-tagged dataset to a frontline-ready CSV.

    Design Principles for Frontline Adoption
    -----------------------------------------
    1. ALERTED ORDERS FIRST  : Sort by alert_priority, then composite_risk_score.
       A store manager opening this file sees the most critical items at the top.

    2. LEAN COLUMN SET       : Only operator-relevant columns are included.
       Financial analysts get all 36 columns; the frontline queue has ~25.

    3. CURRENCY FORMATTING   : Sales, profit, and discount columns are formatted
       as human-readable strings (e.g., "$1,234.56") in a separate "display" block.
       The raw numeric values are preserved for downstream formula use.

    4. ACTION CODE FIRST     : primary_action_code is the 2nd column so it's
       immediately visible without horizontal scrolling.

    5. ALERT-ONLY EXPORT     : The queue only contains rows with active alerts.
       Clean orders are excluded — operators should not have to filter themselves.
    """
    # Filter to alerted orders only
    queue_df = df[df["primary_action_code"] != "NO_ACTION"].copy()

    # Sort: primary sort by alert priority (1=most urgent), secondary by risk score desc
    queue_df = queue_df.sort_values(
        by=["alert_priority", "composite_risk_score"],
        ascending=[True, False],
    )

    # Select and order frontline columns (only include those that exist in df)
    cols_present = [c for c in FRONTLINE_COLUMNS if c in queue_df.columns]
    queue_df = queue_df[cols_present]

    # Export
    output_path.parent.mkdir(parents=True, exist_ok=True)
    queue_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    size_kb = output_path.stat().st_size / 1024
    logger.info(
        f"Frontline action queue exported -> '{output_path}' | "
        f"{len(queue_df):,} alerts | {size_kb:.1f} KB"
    )
    return queue_df


def export_alert_summary(
    summary_df : pd.DataFrame,
    output_path: Path,
    logger     : logging.Logger,
) -> None:
    """Export the management-level alert summary report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info(f"Alert summary report exported -> '{output_path}'")


# ---------------------------------------------------------------------------
# 7. CONSOLE ALERT TABLE (terminal preview)
# ---------------------------------------------------------------------------

def print_alert_table(queue_df: pd.DataFrame, top_n: int = 15) -> None:
    """
    Print a formatted, human-readable alert table to the terminal.
    Designed to mimic the look of a store manager's morning briefing report.
    """
    if queue_df.empty:
        print("\n  [OK] No alerts generated — all orders are within operational thresholds.\n")
        return

    print("\n" + "=" * 110)
    print(f"  FRONTLINE ACTION QUEUE  |  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Showing top {min(top_n, len(queue_df))} of {len(queue_df)} alerts")
    print("=" * 110)

    display_cols = [
        "order_id", "primary_action_code", "alert_priority",
        "category", "sub_category", "region",
        "sales", "profit", "discount", "profit_margin_pct",
        "shipping_duration_days", "alert_owner",
    ]
    display_cols = [c for c in display_cols if c in queue_df.columns]

    preview = queue_df[display_cols].head(top_n).copy()

    # Format numeric columns for readability
    for col in ["sales", "profit"]:
        if col in preview.columns:
            preview[col] = preview[col].apply(lambda x: f"${x:>8,.2f}")
    if "discount" in preview.columns:
        preview["discount"] = preview["discount"].apply(lambda x: f"{x*100:.0f}%")
    if "profit_margin_pct" in preview.columns:
        preview["profit_margin_pct"] = preview["profit_margin_pct"].apply(lambda x: f"{x:.1f}%")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 180)
    pd.set_option("display.colheader_justify", "left")
    print(preview.to_string(index=False))
    print("=" * 110 + "\n")


# ---------------------------------------------------------------------------
# 8. PIPELINE ORCHESTRATOR
# ---------------------------------------------------------------------------

def run_alert_engine(
    input_path   : Path,
    output_path  : Path,
    summary_path : Path,
    dry_run      : bool,
    verbose      : bool,
    top_n        : int,
) -> pd.DataFrame:
    """
    Master orchestration function for the alert engine.

    Stages
    ------
    1. Load clean data from data_pipeline.py output
    2. Add rule-input derived features (ship mode flags)
    3. Evaluate all rules in RULE_REGISTRY
    4. Generate alert summary statistics
    5. Print terminal briefing table
    6. Export frontline action queue CSV (unless --dry-run)
    7. Export management summary CSV (unless --dry-run)
    """
    logger = configure_logging(verbose=verbose)
    run_start = datetime.now()

    logger.info("=" * 60)
    logger.info("RETAIL MARGIN & INVENTORY LEAKAGE — ALERT ENGINE v1.0")
    logger.info("=" * 60)
    logger.info(f"Run started : {run_start.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Input       : {input_path}")
    logger.info(f"Output      : {output_path}")
    logger.info(f"Dry run     : {dry_run}")
    logger.info(f"Rules loaded: {len(RULE_REGISTRY)}")

    # Stage 1 — Load
    df = load_clean_data(input_path, logger)

    # Stage 2 — Add derived rule inputs
    df = add_rule_input_features(df, logger)

    # Stage 3 — Evaluate all rules
    df = evaluate_all_rules(df, logger)

    # Stage 4 — Summary statistics
    summary_df = generate_alert_summary(df, logger)

    # Stage 5 — Terminal briefing
    alerted_df = df[df["primary_action_code"] != "NO_ACTION"].copy()
    alerted_df = alerted_df.sort_values(
        by=["alert_priority", "composite_risk_score"], ascending=[True, False]
    )
    print_alert_table(alerted_df, top_n=top_n)

    # Stage 6+7 — Export
    queue_df = pd.DataFrame()
    if not dry_run:
        queue_df = export_action_queue(df, output_path, logger)
        export_alert_summary(summary_df, summary_path, logger)
    else:
        logger.info("DRY RUN MODE — no files written.")

    elapsed = (datetime.now() - run_start).total_seconds()
    logger.info(f"Alert engine completed in {elapsed:.2f}s")
    logger.info("=" * 60)

    return df


# ---------------------------------------------------------------------------
# 9. CLI ENTRY POINT
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="alert_engine.py",
        description=(
            "Retail Margin & Inventory Leakage — Module 3: "
            "Frontline Operational Alert Engine"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python alert_engine.py
  python alert_engine.py --input data/processed/superstore_clean.csv
  python alert_engine.py --dry-run --verbose
  python alert_engine.py --top 25
        """,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to cleaned CSV (output of data_pipeline.py)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for frontline action queue CSV",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="Path for management alert summary CSV",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Evaluate rules and print results without writing any files",
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=15,
        help="Number of top alerts to preview in terminal table (default: 15)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    try:
        final_df = run_alert_engine(
            input_path   = args.input,
            output_path  = args.output,
            summary_path = args.summary,
            dry_run      = args.dry_run,
            verbose      = args.verbose,
            top_n        = args.top,
        )

        # Terminal summary card
        alert_count  = (final_df["primary_action_code"] != "NO_ACTION").sum()
        freeze_count = (final_df["primary_action_code"] == "FREEZE_DISCOUNT").sum()
        audit_count  = (final_df["primary_action_code"] == "AUDIT_FREIGHT").sum()
        restock_count= (final_df["primary_action_code"] == "URGENT_RESTOCK").sum()
        multi_count  = (final_df["rules_triggered_count"] >= 2).sum()

        print("=" * 60)
        print("  ALERT ENGINE — FINAL SUMMARY")
        print("=" * 60)
        print(f"  Total orders evaluated  : {len(final_df):,}")
        print(f"  Total alerts generated  : {alert_count:,}")
        print(f"  |-- FREEZE_DISCOUNT      : {freeze_count:,}")
        print(f"  |-- AUDIT_FREIGHT        : {audit_count:,}")
        print(f"  +-- URGENT_RESTOCK       : {restock_count:,}")
        print(f"  Multi-rule (highest risk): {multi_count:,}")
        if not args.dry_run:
            print(f"  Action queue exported   : {args.output}")
            print(f"  Summary report exported : {args.summary}")
        print("=" * 60 + "\n")

    except (FileNotFoundError, KeyError) as exc:
        logging.getLogger("alert_engine").error(f"Alert engine ABORTED: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[CANCELLED] Alert engine interrupted by user.")
        sys.exit(0)
