"""
build_dashboard_data.py
Precomputes aggregated metrics and formats records for the Module 4 Web Dashboard.
Outputs: dashboard/data/dashboard_data.json
"""

import json
import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np

def build_data():
    clean_csv_path = Path("data/processed/superstore_clean.csv")
    alerts_csv_path = Path("alerts/frontline_action_queue.csv")
    alerts_summary_path = Path("alerts/alert_summary_report.csv")
    query_results_dir = Path("data/processed/query_results")
    out_dir = Path("dashboard/data")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not clean_csv_path.exists():
        raise FileNotFoundError(f"Missing {clean_csv_path}")

    df = pd.read_csv(clean_csv_path)
    df["order_date"] = pd.to_datetime(df["order_date"])
    df["ship_date"] = pd.to_datetime(df["ship_date"])

    alerts_df = pd.read_csv(alerts_csv_path) if alerts_csv_path.exists() else pd.DataFrame()

    # --- 1. Executive KPIs ---
    gross_sales = float(df["sales"].sum())
    net_profit = float(df["profit"].sum())
    blended_margin = float((net_profit / gross_sales) * 100) if gross_sales else 0.0
    discount_bleed = float(df["discount_loss_amount"].sum())
    total_orders = int(df["order_id"].nunique())
    total_lines = int(len(df))
    loss_making_count = int((df["profit"] < 0).sum())
    avg_discount = float(df["discount"].mean() * 100)
    avg_fulfillment_days = float(df["shipping_duration_days"].mean())

    # Yearly breakdown
    years = sorted(df["order_year"].unique().tolist())
    yearly_stats = []
    for yr in years:
        ydf = df[df["order_year"] == yr]
        ysales = float(ydf["sales"].sum())
        yprofit = float(ydf["profit"].sum())
        ymargin = (yprofit / ysales * 100) if ysales else 0
        ybleed = float(ydf["discount_loss_amount"].sum())
        yorders = int(ydf["order_id"].nunique())
        yearly_stats.append({
            "year": int(yr),
            "sales": round(ysales, 2),
            "profit": round(yprofit, 2),
            "margin_pct": round(ymargin, 2),
            "discount_bleed": round(ybleed, 2),
            "orders": yorders
        })

    # Calculate YoY deltas
    for i in range(1, len(yearly_stats)):
        prev = yearly_stats[i-1]
        curr = yearly_stats[i]
        curr["sales_yoy_pct"] = round(((curr["sales"] - prev["sales"]) / prev["sales"]) * 100, 2) if prev["sales"] else 0
        curr["profit_yoy_pct"] = round(((curr["profit"] - prev["profit"]) / abs(prev["profit"])) * 100, 2) if prev["profit"] else 0
        curr["margin_pp_delta"] = round(curr["margin_pct"] - prev["margin_pct"], 2)

    # Monthly Trend (for Dual-Axis Chart)
    df["year_month"] = df["order_date"].dt.strftime("%Y-%m")
    monthly = df.groupby("year_month").agg(
        sales=("sales", "sum"),
        profit=("profit", "sum"),
        discount_loss=("discount_loss_amount", "sum"),
        order_count=("order_id", "nunique")
    ).reset_index().sort_values("year_month")
    monthly["margin_pct"] = (monthly["profit"] / monthly["sales"]) * 100
    monthly_trend = [
        {
            "month": r["year_month"],
            "sales": round(float(r["sales"]), 2),
            "profit": round(float(r["profit"]), 2),
            "margin_pct": round(float(r["margin_pct"]), 2),
            "discount_loss": round(float(r["discount_loss"]), 2),
            "orders": int(r["order_count"])
        }
        for _, r in monthly.iterrows()
    ]

    # Waterfall Chart components
    orig_list_price = float(df["original_list_price"].sum())
    # Est COGS = sales - profit
    est_cogs = gross_sales - net_profit
    waterfall = {
        "gross_list_price": round(orig_list_price, 2),
        "discount_applied": round(-discount_bleed, 2),
        "net_sales": round(gross_sales, 2),
        "cost_of_goods": round(-est_cogs, 2),
        "net_profit": round(net_profit, 2)
    }

    # State-level metrics for Geographic Map
    state_metrics = df.groupby(["state", "region"]).agg(
        sales=("sales", "sum"),
        profit=("profit", "sum"),
        order_count=("order_id", "nunique"),
        avg_discount=("discount", "mean"),
        avg_shipping=("shipping_duration_days", "mean")
    ).reset_index()
    state_metrics["margin_pct"] = (state_metrics["profit"] / state_metrics["sales"]) * 100

    # Count alerts by state
    if not alerts_df.empty:
        alerts_by_state = alerts_df["state"].value_counts().to_dict()
    else:
        alerts_by_state = {}

    # State Grid Cartogram mapping (US Geographic standard 8x12 grid)
    STATE_GRID = {
        "AK": ("Alaska", 0, 0), "ME": ("Maine", 0, 11),
        "VT": ("Vermont", 1, 10), "NH": ("New Hampshire", 1, 11),
        "WA": ("Washington", 2, 0), "ID": ("Idaho", 2, 1), "MT": ("Montana", 2, 2), "ND": ("North Dakota", 2, 3), "MN": ("Minnesota", 2, 4), "IL": ("Illinois", 2, 5), "WI": ("Wisconsin", 2, 6), "MI": ("Michigan", 2, 7), "NY": ("New York", 2, 8), "MA": ("Massachusetts", 2, 9), "RI": ("Rhode Island", 2, 10),
        "OR": ("Oregon", 3, 0), "NV": ("Nevada", 3, 1), "WY": ("Wyoming", 3, 2), "SD": ("South Dakota", 3, 3), "IA": ("Iowa", 3, 4), "IN": ("Indiana", 3, 5), "OH": ("Ohio", 3, 6), "PA": ("Pennsylvania", 3, 7), "NJ": ("New Jersey", 3, 8), "CT": ("Connecticut", 3, 9),
        "CA": ("California", 4, 0), "UT": ("Utah", 4, 1), "CO": ("Colorado", 4, 2), "NE": ("Nebraska", 4, 3), "MO": ("Missouri", 4, 4), "KY": ("Kentucky", 4, 5), "WV": ("West Virginia", 4, 6), "VA": ("Virginia", 4, 7), "MD": ("Maryland", 4, 8), "DE": ("Delaware", 4, 9),
        "AZ": ("Arizona", 5, 1), "NM": ("New Mexico", 5, 2), "KS": ("Kansas", 5, 3), "AR": ("Arkansas", 5, 4), "TN": ("Tennessee", 5, 5), "NC": ("North Carolina", 5, 6), "SC": ("South Carolina", 5, 7),
        "OK": ("Oklahoma", 6, 3), "LA": ("Louisiana", 6, 4), "MS": ("Mississippi", 6, 5), "AL": ("Alabama", 6, 6), "GA": ("Georgia", 6, 7),
        "HI": ("Hawaii", 7, 0), "TX": ("Texas", 7, 3), "FL": ("Florida", 7, 8)
    }

    state_name_to_code = {v[0]: k for k, v in STATE_GRID.items()}

    states_data = []
    for _, r in state_metrics.iterrows():
        s = r["state"]
        code = state_name_to_code.get(s, s[:2].upper())
        grid_pos = STATE_GRID.get(code, (s, 0, 0))
        states_data.append({
            "state": s,
            "code": code,
            "grid_row": grid_pos[1],
            "grid_col": grid_pos[2],
            "region": r["region"],
            "sales": round(float(r["sales"]), 2),
            "profit": round(float(r["profit"]), 2),
            "margin_pct": round(float(r["margin_pct"]), 2),
            "orders": int(r["order_count"]),
            "avg_discount": round(float(r["avg_discount"] * 100), 2),
            "avg_shipping": round(float(r["avg_shipping"]), 2),
            "alert_count": int(alerts_by_state.get(s, 0))
        })
    states_data.sort(key=lambda x: x["sales"], reverse=True)

    # --- 2. Category & Pricing Diagnostics ---
    # Sub-category x Region Matrix (for Cross-Dimensional Heatmap)
    subcat_reg_grp = df.groupby(["category", "sub_category", "region"]).agg(
        sales=("sales", "sum"),
        profit=("profit", "sum"),
        discount_loss=("discount_loss_amount", "sum"),
        avg_discount=("discount", "mean")
    ).reset_index()
    subcat_reg_grp["margin_pct"] = (subcat_reg_grp["profit"] / subcat_reg_grp["sales"]) * 100

    subcat_reg_matrix = {}
    for _, r in subcat_reg_grp.iterrows():
        sc = r["sub_category"]
        reg = r["region"]
        if sc not in subcat_reg_matrix:
            subcat_reg_matrix[sc] = {
                "category": r["category"],
                "sub_category": sc,
                "regions": {}
            }
        subcat_reg_matrix[sc]["regions"][reg] = {
            "sales": round(float(r["sales"]), 2),
            "profit": round(float(r["profit"]), 2),
            "margin_pct": round(float(r["margin_pct"]), 2),
            "discount_bleed": round(float(r["discount_loss"]), 2),
            "avg_discount": round(float(r["avg_discount"] * 100), 2)
        }

    subcat_grp = df.groupby(["category", "sub_category"]).agg(
        sales=("sales", "sum"),
        profit=("profit", "sum"),
        discount_loss=("discount_loss_amount", "sum"),
        avg_discount=("discount", "mean"),
        order_count=("order_id", "nunique"),
        line_items=("order_id", "count")
    ).reset_index()
    subcat_grp["margin_pct"] = (subcat_grp["profit"] / subcat_grp["sales"]) * 100
    subcat_grp["avg_discount_pct"] = subcat_grp["avg_discount"] * 100

    subcat_diagnostics = []
    for _, r in subcat_grp.iterrows():
        sc_name = r["sub_category"]
        # Quadrant classification
        disc = r["avg_discount_pct"]
        mrg = r["margin_pct"]
        if disc < 20 and mrg >= 0:
            quadrant = "STAR (Low Disc, High Margin)"
            quadrant_class = "star"
        elif disc >= 20 and mrg >= 0:
            quadrant = "MONITOR (High Disc, Profitable)"
            quadrant_class = "monitor"
        elif disc < 20 and mrg < 0:
            quadrant = "INVESTIGATE (Low Disc, Loss)"
            quadrant_class = "investigate"
        else:
            quadrant = "DANGER ZONE (High Disc + Margin Bleed)"
            quadrant_class = "danger"

        subcat_diagnostics.append({
            "category": r["category"],
            "sub_category": sc_name,
            "sales": round(float(r["sales"]), 2),
            "profit": round(float(r["profit"]), 2),
            "margin_pct": round(float(r["margin_pct"]), 2),
            "avg_discount_pct": round(float(disc), 2),
            "discount_bleed": round(float(r["discount_loss"]), 2),
            "order_count": int(r["order_count"]),
            "line_items": int(r["line_items"]),
            "quadrant": quadrant,
            "quadrant_class": quadrant_class,
            "is_loss_leader": bool(r["profit"] < 0),
            "regional_matrix": subcat_reg_matrix.get(sc_name, {}).get("regions", {})
        })
    subcat_diagnostics.sort(key=lambda x: x["profit"])

    # Category summaries
    cat_grp = df.groupby("category").agg(
        sales=("sales", "sum"),
        profit=("profit", "sum"),
        discount_loss=("discount_loss_amount", "sum"),
        orders=("order_id", "nunique")
    ).reset_index()
    cat_grp["margin_pct"] = (cat_grp["profit"] / cat_grp["sales"]) * 100
    category_summary = [
        {
            "category": r["category"],
            "sales": round(float(r["sales"]), 2),
            "profit": round(float(r["profit"]), 2),
            "margin_pct": round(float(r["margin_pct"]), 2),
            "discount_bleed": round(float(r["discount_loss"]), 2),
            "orders": int(r["orders"])
        }
        for _, r in cat_grp.iterrows()
    ]

    # --- 3. Frontline Operations & Last-Mile ---
    # Heatmap Matrix: Region x Ship Mode
    region_ship = df.groupby(["region", "ship_mode"]).agg(
        avg_fulfillment=("shipping_duration_days", "mean"),
        order_count=("order_id", "count"),
        sla_breaches=("shipping_duration_days", lambda s: (s > 5).sum())
    ).reset_index()
    region_ship["breach_rate_pct"] = (region_ship["sla_breaches"] / region_ship["order_count"]) * 100

    regions_list = sorted(df["region"].unique().tolist())
    ship_modes_list = ["Same Day", "First Class", "Second Class", "Standard Class"]
    
    heatmap_matrix = []
    for reg in regions_list:
        row_data = {"region": reg, "modes": {}}
        for sm in ship_modes_list:
            match = region_ship[(region_ship["region"] == reg) & (region_ship["ship_mode"] == sm)]
            if not match.empty:
                r = match.iloc[0]
                row_data["modes"][sm] = {
                    "avg_days": round(float(r["avg_fulfillment"]), 2),
                    "orders": int(r["order_count"]),
                    "breaches": int(r["sla_breaches"]),
                    "breach_rate": round(float(r["breach_rate_pct"]), 2)
                }
            else:
                row_data["modes"][sm] = {"avg_days": 0, "orders": 0, "breaches": 0, "breach_rate": 0}
        heatmap_matrix.append(row_data)

    # Fulfillment Lag Distribution Histogram
    bins = [
        ("0-1 Days (Optimal)", (df["shipping_duration_days"] <= 1)),
        ("2-3 Days (Target)", (df["shipping_duration_days"] > 1) & (df["shipping_duration_days"] <= 3)),
        ("4-5 Days (Acceptable)", (df["shipping_duration_days"] > 3) & (df["shipping_duration_days"] <= 5)),
        ("6-7 Days (At Risk)", (df["shipping_duration_days"] > 5) & (df["shipping_duration_days"] <= 7)),
        ("8+ Days (SLA Breach)", (df["shipping_duration_days"] > 7))
    ]
    lag_histogram = []
    for label, cond in bins:
        count = int(cond.sum())
        pct = round((count / total_lines) * 100, 2)
        lag_histogram.append({"bin": label, "count": count, "pct": pct})

    # Alert Queue Top Records & Stats
    alert_summary = {}
    if not alerts_df.empty:
        action_counts = alerts_df["primary_action_code"].value_counts().to_dict()
        priority_counts = alerts_df["alert_priority"].value_counts().to_dict()
        
        # Take top 300 alerts sorted by priority ASC, risk score DESC
        sorted_alerts = alerts_df.sort_values(
            by=["alert_priority", "composite_risk_score", "sales"],
            ascending=[True, False, False]
        ).head(300)

        alerts_list = []
        for _, a in sorted_alerts.iterrows():
            alerts_list.append({
                "order_id": str(a["order_id"]),
                "order_date": str(a["order_date"]),
                "category": str(a["category"]),
                "sub_category": str(a["sub_category"]),
                "product_name": str(a.get("product_name", "")),
                "region": str(a["region"]),
                "state": str(a["state"]),
                "ship_mode": str(a["ship_mode"]),
                "segment": str(a.get("segment", "Consumer")),
                "sales": round(float(a["sales"]), 2),
                "profit": round(float(a["profit"]), 2),
                "discount_pct": round(float(a["discount"] * 100), 1),
                "profit_margin_pct": round(float(a["profit_margin_pct"]), 1),
                "shipping_days": int(a["shipping_duration_days"]),
                "rules_triggered": str(a["rules_triggered"]).split(" | "),
                "rules_count": int(a.get("rules_triggered_count", 1)),
                "composite_risk_score": int(a.get("composite_risk_score", 10)),
                "primary_action_code": str(a["primary_action_code"]),
                "alert_priority": int(a["alert_priority"]),
                "alert_display_name": str(a.get("alert_display_name", "Risk Alert")),
                "alert_rationale": str(a.get("alert_rationale", "")),
                "alert_owner": str(a.get("alert_owner", "Category Manager")),
                "alert_sla_hours": float(a.get("alert_sla_hours", 4.0))
            })
            
        alert_summary = {
            "total_alerts": int(len(alerts_df)),
            "freeze_discount_count": int(action_counts.get("FREEZE_DISCOUNT", 0)),
            "audit_freight_count": int(action_counts.get("AUDIT_FREIGHT", 0)),
            "urgent_restock_count": int(action_counts.get("URGENT_RESTOCK", 0)),
            "priority_1_count": int(priority_counts.get(1, 0)),
            "priority_2_count": int(priority_counts.get(2, 0)),
            "priority_3_count": int(priority_counts.get(3, 0)),
            "priority_4_count": int(priority_counts.get(4, 0)),
            "total_revenue_at_risk": round(float(alerts_df["sales"].sum()), 2),
            "total_profit_loss": round(float(alerts_df["profit"].sum()), 2),
            "total_discount_bleed": round(float(alerts_df["discount_loss_amount"].sum()), 2),
            "multi_rule_count": int((alerts_df.get("rules_triggered_count", 1) >= 2).sum()),
            "queue": alerts_list
        }

    # Load SQL query results if available
    query_data = {}
    if query_results_dir.exists():
        for qf in query_results_dir.glob("*.csv"):
            try:
                qdf = pd.read_csv(qf)
                query_data[qf.stem] = {
                    "filename": qf.name,
                    "rows": qdf.head(15).replace({np.nan: None}).to_dict(orient="records"),
                    "total_rows": len(qdf),
                    "columns": list(qdf.columns)
                }
            except Exception as e:
                print(f"Error reading {qf}: {e}")

    # Prepare records for dynamic real-time filtering in frontend
    if not alerts_df.empty:
        alert_map = {}
        for _, a in alerts_df.iterrows():
            oid = a["order_id"]
            if oid not in alert_map:
                alert_map[oid] = {
                    "action": a.get("primary_action_code", "NO_ACTION"),
                    "priority": int(a.get("alert_priority", 0)),
                    "risk": int(a.get("composite_risk_score", 0)),
                    "owner": a.get("alert_owner", "Category Manager"),
                    "sla": float(a.get("alert_sla_hours", 4.0)),
                    "rules": str(a.get("rules_triggered", "")).split(" | "),
                    "rationale": str(a.get("alert_rationale", ""))
                }
    else:
        alert_map = {}

    all_records = []
    for _, r in df.iterrows():
        oid = r["order_id"]
        al = alert_map.get(oid, {
            "action": "NO_ACTION",
            "priority": 0,
            "risk": 0,
            "owner": "Store Operations",
            "sla": 24.0,
            "rules": [],
            "rationale": "Clean order within normal operating parameters."
        })
        all_records.append({
            "id": oid,
            "dt": r["order_date"].strftime("%Y-%m-%d"),
            "yr": int(r["order_year"]),
            "ym": r["year_month"],
            "cat": r["category"],
            "sc": r["sub_category"],
            "prod": r.get("product_name", ""),
            "reg": r["region"],
            "st": r["state"],
            "sm": r["ship_mode"],
            "sales": round(float(r["sales"]), 2),
            "profit": round(float(r["profit"]), 2),
            "disc": round(float(r["discount"]), 3),
            "mrg": round(float(r["profit_margin_pct"]), 2),
            "bleed": round(float(r["discount_loss_amount"]), 2),
            "ship_d": int(r["shipping_duration_days"]),
            "action": al["action"],
            "priority": al["priority"],
            "risk": al["risk"],
            "owner": al["owner"],
            "sla": al["sla"],
            "rules": al["rules"],
            "rationale": al["rationale"]
        })

    # Final Payload
    payload = {
        "metadata": {
            "title": "Retail Margin & Inventory Leakage — Last-Mile Decision Engine",
            "subtitle": "Interactive Enterprise Operational Analytics Dashboard",
            "dataset_rows": total_lines,
            "unique_orders": total_orders,
            "years_covered": years,
            "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        },
        "records": all_records,
        "executive": {
            "kpis": {
                "gross_sales": round(gross_sales, 2),
                "net_profit": round(net_profit, 2),
                "blended_margin_pct": round(blended_margin, 2),
                "discount_loss_bleed": round(discount_bleed, 2),
                "discount_bleed_pct_sales": round((discount_bleed / gross_sales) * 100, 2) if gross_sales else 0,
                "total_orders": total_orders,
                "loss_making_count": loss_making_count,
                "loss_making_pct": round((loss_making_count / total_lines) * 100, 2),
                "avg_discount_pct": round(avg_discount, 2),
                "avg_fulfillment_days": round(avg_fulfillment_days, 2)
            },
            "yearly_stats": yearly_stats,
            "monthly_trend": monthly_trend,
            "waterfall": waterfall,
            "states": states_data,
            "categories": category_summary
        },
        "category_diagnostics": {
            "subcategories": subcat_diagnostics,
            "categories": category_summary
        },
        "operations": {
            "summary": alert_summary,
            "heatmap": heatmap_matrix,
            "lag_histogram": lag_histogram,
            "ship_modes": ship_modes_list,
            "regions": regions_list
        },
        "sql_queries": query_data
    }

    out_file = out_dir / "dashboard_data.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Dashboard data generated successfully -> {out_file} ({out_file.stat().st_size / 1024:.1f} KB)")

if __name__ == "__main__":
    build_data()
