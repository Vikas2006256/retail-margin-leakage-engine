"""
generate_superstore_data.py
----------------------------
Generates a 9,994-row synthetic Superstore Sales dataset that faithfully
mirrors the statistical properties of the real Kaggle Superstore dataset:
  - Realistic category/sub-category product mix
  - Region and state distributions matching US geography
  - Discount distributions per sub-category (Tables/Bookcases = high discount)
  - Profit margin profiles that reflect actual loss-leader dynamics
  - Date range: 2019-01-01 to 2022-12-31 (4 years, matching real dataset)
  - Shipping durations per ship mode (Same Day=0-1d, First=1-4d, etc.)

Output: data/raw/superstore.csv  (overwrites synthetic test file)
"""

import random
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

random.seed(42)
np.random.seed(42)

# ─── MASTER CONFIGURATION ────────────────────────────────────────────────────

TOTAL_ROWS   = 9994
DATE_START   = datetime(2019, 1, 1)
DATE_END     = datetime(2022, 12, 31)

REGIONS = {
    "West"    : ["California","Washington","Oregon","Nevada","Arizona","Colorado","Utah","Idaho","Montana","Wyoming","Alaska","Hawaii","New Mexico"],
    "East"    : ["New York","Pennsylvania","Virginia","Massachusetts","Maryland","Connecticut","New Jersey","North Carolina","Georgia","Florida","Maine","Vermont","New Hampshire","Rhode Island","Delaware","West Virginia"],
    "Central" : ["Texas","Illinois","Ohio","Michigan","Indiana","Missouri","Wisconsin","Minnesota","Iowa","Kansas","Nebraska","South Dakota","North Dakota","Oklahoma"],
    "South"   : ["Tennessee","Kentucky","Alabama","Mississippi","Louisiana","Arkansas","South Carolina"],
}

SHIP_MODES = {
    "Standard Class": 0.60,
    "Second Class"  : 0.20,
    "First Class"   : 0.15,
    "Same Day"      : 0.05,
}

# Shipping duration in days per mode: (min, max, mean, std)
SHIP_DURATION = {
    "Standard Class": (3,  7,  5.0, 1.0),
    "Second Class"  : (2,  5,  3.5, 0.8),
    "First Class"   : (1,  4,  2.5, 0.7),
    "Same Day"      : (0,  1,  0.3, 0.5),
}

SEGMENTS = {"Consumer": 0.52, "Corporate": 0.30, "Home Office": 0.18}

# Sub-category config:
#   (category, weight, base_price_range, discount_mean, discount_std,
#    margin_mean_pct, margin_std_pct)
SUB_CATEGORIES = [
    # Furniture — often high discount, sometimes negative margin
    ("Furniture", "Chairs",      0.090, (80,   1800), 0.17, 0.10, 7.0,  15.0),
    ("Furniture", "Tables",      0.050, (200,  2000), 0.25, 0.12, -6.0, 20.0),   # loss leader
    ("Furniture", "Bookcases",   0.040, (100,  900),  0.22, 0.11, -3.0, 18.0),   # often negative
    ("Furniture", "Furnishings", 0.055, (15,   250),  0.08, 0.06, 18.0, 10.0),

    # Office Supplies — high volume, thin margins, light discounting
    ("Office Supplies", "Binders",    0.150, (3,    300),  0.18, 0.12, 12.0, 14.0),
    ("Office Supplies", "Paper",      0.075, (10,   120),  0.05, 0.04, 22.0,  8.0),
    ("Office Supplies", "Storage",    0.060, (20,   400),  0.10, 0.07, 9.0,  12.0),
    ("Office Supplies", "Supplies",   0.030, (5,    80),   0.12, 0.08, -11.0, 16.0),  # negative margin
    ("Office Supplies", "Art",        0.035, (3,    50),   0.06, 0.04, 23.0,  7.0),
    ("Office Supplies", "Labels",     0.025, (3,    40),   0.03, 0.02, 25.0,  6.0),
    ("Office Supplies", "Envelopes",  0.020, (3,    30),   0.04, 0.03, 21.0,  8.0),
    ("Office Supplies", "Fasteners",  0.015, (2,    20),   0.02, 0.02, 28.0,  5.0),

    # Technology — high ASP, wide margin variance, some high-discount machine deals
    ("Technology", "Phones",    0.145, (100,  1900), 0.13, 0.10, 14.0, 18.0),
    ("Technology", "Accessories",0.065,(10,   200),  0.09, 0.07, 20.0, 12.0),
    ("Technology", "Machines",   0.040,(400,  6000), 0.10, 0.12, -4.0, 25.0),   # loss leader
    ("Technology", "Copiers",    0.035,(400,  8000), 0.08, 0.09, 22.0, 20.0),
]

PRODUCTS = {
    "Chairs"      : ["HON 5400 Series","Global Troy","Sauder Beginnings","Bush Business"],
    "Tables"      : ["Bretford CR4500","Bevis 36x72","Chromcraft Bull-Nose","Hon 10500"],
    "Bookcases"   : ["Sauder Classic","Bush Industries","O'Sullivan 2-Shelf","Ikea KALLAX"],
    "Furnishings" : ["Deflect-o Partition","Eldon Expressions","Fiskars","Lorell Mesh"],
    "Binders"     : ["Avery Heavy Duty","Cardinal SlantD","Avery DUR","Ibico EPK"],
    "Paper"       : ["Xerox 1967","Hammermill Copy Plus","HP Premium32","Southworth"],
    "Storage"     : ["Steelmaster","Fellowes Mobile","Eldon Wave","Crate&Barrel"],
    "Supplies"    : ["Acco Perma","Rogers","Sanford Liquid","Fiskars Softgrip"],
    "Art"         : ["Sanford 16","SAFE-T Ruler","Avery Marks-A-Lot","Dixon Ticonderoga"],
    "Labels"      : ["Avery 503","Avery 49","Avery 5161","Mead"],
    "Envelopes"   : ["Poly String Tie","Jiffy Padded","Acco 10-Ply","Domtar"],
    "Fasteners"   : ["Advantus Super","PaperMate Oval","OIC Binder Clips","Avery Marks"],
    "Phones"      : ["Cisco TelePresence","Plantronics CS510","GN Audio","Motorola Smart"],
    "Accessories" : ["Logitech G910","Plantronics LS1","Cables Unlimited","HooToo"],
    "Machines"    : ["Fellowes PB500","Samsung MFC-7860DW","HP OfficeJet","Canon PC1060"],
    "Copiers"     : ["Canon imageCLASS","HP LaserJet Pro","Samsung Xpress","Ricoh Aficio"],
}

CUSTOMER_FIRST = ["James","Mary","Robert","Patricia","John","Jennifer","Michael","Linda",
                  "David","Barbara","Sarah","Thomas","Karen","Charles","Lisa","Joseph"]
CUSTOMER_LAST  = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis",
                  "Wilson","Anderson","Taylor","Moore","Jackson","Martin","Lee","Thompson"]

# ─── GENERATOR ──────────────────────────────────────────────────────────────

rows = []
order_id_counter = {}   # tracks order_id → order_date mapping for multi-line orders
order_pool       = []   # pre-generate order IDs for multi-row reuse

# Generate ~3,200 unique orders (avg ~3.1 line items per order, giving ~9,994 rows)
n_orders = 3200
order_dates = [
    DATE_START + timedelta(days=int(d))
    for d in np.random.uniform(0, (DATE_END - DATE_START).days, n_orders)
]
order_dates.sort()

order_ids   = [f"CA-{d.year}-{100000 + i:06d}" for i, d in enumerate(order_dates)]
customer_ids= [f"CG-{random.randint(1000,9999)}" for _ in range(n_orders)]
customers   = [f"{random.choice(CUSTOMER_FIRST)} {random.choice(CUSTOMER_LAST)}" for _ in range(n_orders)]

# Build weighted distributions
sc_names    = list(SHIP_MODES.keys())
sc_weights  = list(SHIP_MODES.values())
seg_names   = list(SEGMENTS.keys())
seg_weights = list(SEGMENTS.values())

# Expand sub-categories to row-level using weighted selection
subcat_names   = [s[1] for s in SUB_CATEGORIES]
subcat_weights = [s[2] for s in SUB_CATEGORIES]
subcat_lookup  = {s[1]: s for s in SUB_CATEGORIES}

# ── Two-pass generation: generate items, then assign dates across full 2019-2022 ──
orders_data = []
total_items = 0

while total_items < TOTAL_ROWS:
    n_items = random.choices([1, 2, 3, 4, 5], weights=[0.35, 0.30, 0.20, 0.10, 0.05])[0]
    items_to_add = min(n_items, TOTAL_ROWS - total_items)
    total_items += items_to_add
    
    region = random.choices(list(REGIONS.keys()), weights=[0.30, 0.35, 0.25, 0.10])[0]
    state = random.choice(REGIONS[region])
    ship_mode = random.choices(sc_names, weights=sc_weights)[0]
    segment = random.choices(seg_names, weights=seg_weights)[0]
    cust_id = f"CG-{random.randint(1000, 9999)}"
    cust_name = f"{random.choice(CUSTOMER_FIRST)} {random.choice(CUSTOMER_LAST)}"
    
    orders_data.append({
        "item_count": items_to_add,
        "region": region,
        "state": state,
        "ship_mode": ship_mode,
        "segment": segment,
        "cust_id": cust_id,
        "cust_name": cust_name,
    })

N_ORDERS = len(orders_data)
order_dates = sorted([
    DATE_START + timedelta(days=int(d))
    for d in np.random.uniform(0, (DATE_END - DATE_START).days, N_ORDERS)
])

rows = []
row_id = 1

for idx, ord_info in enumerate(orders_data):
    order_date = order_dates[idx]
    order_id = f"CA-{order_date.year}-{100000 + idx:06d}"
    region = ord_info["region"]
    state = ord_info["state"]
    ship_mode = ord_info["ship_mode"]
    segment = ord_info["segment"]
    customer_id = ord_info["cust_id"]
    customer = ord_info["cust_name"]
    postal_code = str(random.randint(10000, 99999))
    city = state + " City"

    sd = SHIP_DURATION[ship_mode]
    dur = int(np.clip(np.random.normal(sd[2], sd[3]), sd[0], sd[1]))
    ship_date = order_date + timedelta(days=dur)

    for _ in range(ord_info["item_count"]):
        subcat_name = random.choices(subcat_names, weights=subcat_weights)[0]
        sc = subcat_lookup[subcat_name]
        category, _, _, price_range, disc_mean, disc_std, margin_mean, margin_std = sc[:8]

        product_name = random.choice(PRODUCTS[subcat_name]) + f" {chr(random.randint(65, 90))}-{random.randint(100, 999)}"
        product_id = f"{category[:3].upper()}-{subcat_name[:2].upper()}-{random.randint(10000, 99999)}"

        quantity = random.choices([1, 2, 3, 4, 5, 6, 7], weights=[0.35, 0.25, 0.18, 0.10, 0.07, 0.03, 0.02])[0]
        unit_price = round(np.random.uniform(price_range[0], price_range[1]), 2)
        discount = round(float(np.clip(np.random.normal(disc_mean, disc_std), 0, 0.80)), 2)
        sales = max(round(unit_price * (1 - discount) * quantity, 2), 0.01)

        # Realistic margin: base margin minus discount erosion effect
        margin_pct = np.random.normal(margin_mean, margin_std) / 100.0
        margin_pct -= discount * 0.65    # tuned: gives ~11% blended margin
        profit = round(sales * margin_pct, 2)

        rows.append({
            "Row ID": row_id,
            "Order ID": order_id,
            "Order Date": order_date.strftime("%m/%d/%Y"),
            "Ship Date": ship_date.strftime("%m/%d/%Y"),
            "Ship Mode": ship_mode,
            "Customer ID": customer_id,
            "Customer Name": customer,
            "Segment": segment,
            "Country": "United States",
            "City": city,
            "State": state,
            "Postal Code": postal_code,
            "Region": region,
            "Product ID": product_id,
            "Category": category,
            "Sub-Category": subcat_name,
            "Product Name": product_name,
            "Sales": sales,
            "Quantity": quantity,
            "Discount": discount,
            "Profit": profit,
        })
        row_id += 1

df = pd.DataFrame(rows[:TOTAL_ROWS])
Path("data/raw").mkdir(parents=True, exist_ok=True)
df.to_csv("data/raw/superstore.csv", index=False)

print(f"Generated {len(df):,} rows x {len(df.columns)} columns")
print(f"Date range  : {df['Order Date'].iloc[0]} -> {df['Order Date'].iloc[-1]}")
print(f"Unique orders: {df['Order ID'].nunique():,}")
print(f"Categories  : {df['Category'].value_counts().to_dict()}")
print(f"Avg discount: {df['Discount'].mean():.1%}")
print(f"Avg margin  : {(df['Profit'].sum()/df['Sales'].sum()*100):.2f}%")
print(f"Neg profit  : {(df['Profit'] < 0).sum():,} rows ({(df['Profit']<0).mean():.1%})")
print(f"Saved: data/raw/superstore.csv")
