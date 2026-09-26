"""Seed StockSense with a realistic demo dataset.

    python -m app.seed        # from the repository root
    flask --app run seed      # or through the CLI

This wipes the database and rebuilds it. It is a demo seeder, not a migration.

Documents are created through the real engine and validated through the real
``validate_document`` path, so the seeded ledger is produced by exactly the same
code that runs in production. Nothing is hand-written into ``stock_moves``.
"""

from . import engine
from .auth import hash_password
from .db import execute, get_db, init_db

DEMO_EMAIL = "admin@stocksense.dev"
DEMO_PASSWORD = "demo1234"

# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

WAREHOUSES = [
    ("MAIN", "Main Warehouse", "Plot 14, Industrial Estate, Hyderabad"),
    ("PROD", "Production Floor", "Building B, Industrial Estate, Hyderabad"),
    ("NORTH", "North Regional Depot", "Sector 9, MIDC, Nagpur"),
]

EXTRA_LOCATIONS = [
    ("MAIN", "RACK-A", "Aisle A, rack 1"),
    ("MAIN", "RACK-B", "Aisle A, rack 2"),
    ("PROD", "FLOOR", "Assembly floor"),
]

CATEGORIES = [
    "Raw Materials", "Finished Goods", "Fasteners", "Consumables",
    "Packaging", "Spare Parts", "Tools", "Safety",
]

# (sku, name, category, uom, unit_cost, reorder_min, reorder_max)
PRODUCTS = [
    ("STL-ROD-12", "Steel Rod 12mm",           "Raw Materials",  "kg",    68.00,  200, 1000),
    ("STL-SHT-2",  "Steel Sheet 2mm",          "Raw Materials",  "kg",    74.50,  100,  600),
    ("CHAIR-ERG",  "Ergonomic Office Chair",   "Finished Goods", "unit", 4200.00,  30,  100),
    ("CHAIR-STK",  "Stacking Chair",           "Finished Goods", "unit", 1850.00,  20,   80),
    ("BOLT-M8",    "Hex Bolt M8",              "Fasteners",      "unit",    2.40,  500, 5000),
    ("NUT-M8",     "Hex Nut M8",               "Fasteners",      "unit",    1.10,  500, 5000),
    ("GASKET-3",   "Rubber Gasket 3in",        "Consumables",    "unit",    8.75,  400, 1000),
    ("CARTON-M",   "Corrugated Carton Medium", "Packaging",      "unit",   12.00,  200,  800),
    ("TAPE-50",    "Packing Tape 50mm",        "Packaging",      "roll",   45.00,  100,  400),
    ("WELD-ROD",   "Welding Electrode 3.15mm", "Consumables",    "kg",    210.00,   50,  200),
    ("PAINT-GRY",  "Epoxy Primer Grey",        "Consumables",    "litre", 340.00,   40,  150),
    ("BEAR-6204",  "Ball Bearing 6204",        "Spare Parts",    "unit",  145.00,   60,  250),
    ("DRIL-BIT-8", "HSS Drill Bit 8mm",        "Tools",          "unit",   95.00,   40,  150),
    ("HELM-SFT",   "Safety Helmet",            "Safety",         "unit",  260.00,   25,  100),
    ("GLOV-IND",   "Industrial Gloves",        "Safety",         "pair",   85.00,   50,  200),
]

USERS = [
    ("admin@stocksense.dev",   "Harsha Vardhan", "Administrator"),
    ("manager@stocksense.dev", "Dileep Chandra", "Inventory Manager"),
    ("staff@stocksense.dev",   "Mani Kanta",     "Warehouse Staff"),
]

# ---------------------------------------------------------------------------
# Documents, in the order they are created.
#
# Order matters: a delivery can only be validated once the stock it ships has
# been received. A line is a dict so locations can be pinned where the default
# stock area is not the right one -- rack to rack, for instance.
#
#   receipt / delivery / internal line: {"sku", "qty", "src"?, "dst"?}
#   adjustment line:                    {"sku", "counted", "location"}
# ---------------------------------------------------------------------------

RECEIPTS = [
    ("done", {"supplier": "Tata Steel", "dst": "MAIN",
              "notes": "Weekly raw material intake"},
     [{"sku": "STL-ROD-12", "qty": 500}, {"sku": "STL-SHT-2", "qty": 300}]),

    ("done", {"supplier": "Godrej Interio", "dst": "MAIN"},
     [{"sku": "CHAIR-ERG", "qty": 40}]),

    ("done", {"supplier": "Bharat Fasteners", "dst": "MAIN"},
     [{"sku": "BOLT-M8", "qty": 2000}, {"sku": "NUT-M8", "qty": 1500},
      {"sku": "GASKET-3", "qty": 400}]),

    ("done", {"supplier": "Industrial Supplies Co", "dst": "MAIN",
              "notes": "Consumables top-up"},
     [{"sku": "WELD-ROD", "qty": 120}, {"sku": "PAINT-GRY", "qty": 60},
      {"sku": "BEAR-6204", "qty": 90}, {"sku": "HELM-SFT", "qty": 40},
      {"sku": "GLOV-IND", "qty": 150}]),

    ("ready", {"supplier": "PackRight Industries", "dst": "MAIN",
               "notes": "Awaiting unloading bay"},
     [{"sku": "CARTON-M", "qty": 500}, {"sku": "TAPE-50", "qty": 150}]),

    ("waiting", {"supplier": "Tata Steel", "dst": "NORTH",
                 "notes": "Supplier confirmed dispatch"},
     [{"sku": "STL-ROD-12", "qty": 250}]),

    ("draft", {"supplier": "Godrej Interio", "dst": "MAIN"},
     [{"sku": "CHAIR-ERG", "qty": 15}]),
]

INTERNAL = [
    ("done", {"src": "MAIN", "dst": "PROD",
              "notes": "Materials issued to production"},
     [{"sku": "STL-ROD-12", "qty": 150, "src": "MAIN/STOCK", "dst": "PROD/FLOOR"}]),

    ("done", {"src": "MAIN", "dst": "MAIN", "notes": "Rack reorganisation"},
     [{"sku": "GASKET-3", "qty": 60, "src": "MAIN/STOCK", "dst": "MAIN/RACK-B"}]),

    ("ready", {"src": "MAIN", "dst": "NORTH", "notes": "Regional replenishment"},
     [{"sku": "STL-SHT-2", "qty": 80}]),

    ("waiting", {"src": "MAIN", "dst": "PROD", "notes": "Next production run"},
     [{"sku": "STL-ROD-12", "qty": 100, "src": "MAIN/STOCK", "dst": "PROD/FLOOR"}]),

    ("draft", {"src": "MAIN", "dst": "PROD"},
     [{"sku": "BOLT-M8", "qty": 200, "src": "MAIN/STOCK", "dst": "PROD/FLOOR"}]),
]

DELIVERIES = [
    ("done", {"src": "MAIN", "notes": "Customer order SO-4471"},
     [{"sku": "CHAIR-ERG", "qty": 12}]),

    ("done", {"src": "MAIN", "notes": "Customer order SO-4478"},
     [{"sku": "STL-ROD-12", "qty": 120}]),

    ("done", {"src": "MAIN", "notes": "Customer order SO-4480"},
     [{"sku": "GASKET-3", "qty": 30, "src": "MAIN/RACK-B"}]),

    ("ready", {"src": "MAIN", "notes": "Packed, awaiting carrier"},
     [{"sku": "CHAIR-ERG", "qty": 8}]),

    ("draft", {"src": "MAIN"},
     [{"sku": "STL-SHT-2", "qty": 40}]),

    ("canceled", {"src": "MAIN", "notes": "Customer cancelled the order"},
     [{"sku": "CHAIR-ERG", "qty": 5}]),
]

# Adjustments carry the *counted* quantity, not a delta. The engine records the
# difference between the count and the ledger.
ADJUSTMENTS = [
    ("done", {"warehouse": "PROD", "notes": "Physical count — 3 kg damaged in transit"},
     [{"sku": "STL-ROD-12", "counted": 147, "location": "PROD/FLOOR"}]),

    ("done", {"warehouse": "MAIN", "notes": "Physical count — 2 units damaged"},
     [{"sku": "GASKET-3", "counted": 28, "location": "MAIN/RACK-B"}]),

    ("draft", {"warehouse": "MAIN", "notes": "Cycle count scheduled"},
     [{"sku": "CHAIR-ERG", "counted": 27, "location": "MAIN/STOCK"}]),
]


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _warehouse_id(code: str) -> int:
    row = engine.query("SELECT id FROM warehouses WHERE code = ?", (code,), one=True)
    if row is None:
        raise RuntimeError(f"Warehouse {code} is missing")
    return row["id"]


def _product_id(sku: str) -> int:
    row = engine.query("SELECT id FROM products WHERE sku = ?", (sku,), one=True)
    if row is None:
        raise RuntimeError(f"Product {sku} is missing")
    return row["id"]


def _location_id(code: str) -> int:
    row = engine.query("SELECT id FROM locations WHERE code = ?", (code,), one=True)
    if row is None:
        raise RuntimeError(f"Location {code} is missing")
    return row["id"]


def _user_id(index: int) -> int:
    rows = engine.query("SELECT id FROM users ORDER BY id")
    return rows[index % len(rows)]["id"]


def _create(doc_type, status, header, lines, *, user_index=0):
    """Create a document, add its lines, and validate it when the status says so."""
    user_id = _user_id(user_index)

    # Adjustments name a single "warehouse"; the other types use src/dst.
    src_code = header.get("src") or header.get("warehouse")

    document_id = engine.create_document(
        doc_type=doc_type,
        user_id=user_id,
        supplier=header.get("supplier", ""),
        src_warehouse_id=_warehouse_id(src_code) if src_code else None,
        dst_warehouse_id=_warehouse_id(header["dst"]) if header.get("dst") else None,
        notes=header.get("notes", ""),
    )

    for line in lines:
        if doc_type == "adjustment":
            engine.add_line(
                document_id,
                _product_id(line["sku"]),
                qty=0,
                counted_qty=line["counted"],
                dst_location_id=_location_id(line["location"]),
            )
        else:
            engine.add_line(
                document_id,
                _product_id(line["sku"]),
                qty=line["qty"],
                src_location_id=_location_id(line["src"]) if line.get("src") else None,
                dst_location_id=_location_id(line["dst"]) if line.get("dst") else None,
            )

    if status == "done":
        engine.validate_document(document_id, user_id=user_id)
    else:
        engine.set_status(document_id, status)

    return document_id


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def reset() -> None:
    """Drop everything and rebuild the schema."""
    db = get_db()
    db.executescript("""
        PRAGMA foreign_keys = OFF;
        DROP VIEW  IF EXISTS v_stock_levels;
        DROP TABLE IF EXISTS stock_moves;
        DROP TABLE IF EXISTS document_lines;
        DROP TABLE IF EXISTS documents;
        DROP TABLE IF EXISTS locations;
        DROP TABLE IF EXISTS warehouses;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS categories;
        DROP TABLE IF EXISTS password_resets;
        DROP TABLE IF EXISTS users;
        PRAGMA foreign_keys = ON;
    """)
    db.commit()
    init_db()


def seed() -> None:
    reset()

    for email, name, role in USERS:
        execute(
            """INSERT INTO users (email, name, role, password_hash, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (email, name, role, hash_password(DEMO_PASSWORD), engine.now()),
        )

    for code, name, address in WAREHOUSES:
        execute(
            "INSERT INTO warehouses (code, name, address, created_at) VALUES (?, ?, ?, ?)",
            (code, name, address, engine.now()),
        )
        execute(
            "INSERT INTO locations (warehouse_id, code, name, kind) VALUES (?, ?, ?, 'internal')",
            (_warehouse_id(code), f"{code}/STOCK", "Stock area"),
        )

    for warehouse_code, code, name in EXTRA_LOCATIONS:
        execute(
            "INSERT INTO locations (warehouse_id, code, name, kind) VALUES (?, ?, ?, 'internal')",
            (_warehouse_id(warehouse_code), f"{warehouse_code}/{code}", name),
        )

    for name in CATEGORIES:
        execute("INSERT INTO categories (name) VALUES (?)", (name,))

    for sku, name, category, uom, cost, reorder_min, reorder_max in PRODUCTS:
        category_id = engine.query(
            "SELECT id FROM categories WHERE name = ?", (category,), one=True
        )["id"]
        execute(
            """INSERT INTO products
                   (sku, name, category_id, uom, unit_cost, reorder_min, reorder_max,
                    is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (sku, name, category_id, uom, cost, reorder_min, reorder_max, engine.now()),
        )

    # Receipts first: nothing else can happen until stock exists.
    for index, (status, header, lines) in enumerate(RECEIPTS):
        _create("receipt", status, header, lines, user_index=index)

    # Then internal movements, deliveries, and finally count corrections.
    for index, (status, header, lines) in enumerate(INTERNAL):
        _create("internal", status, header, lines, user_index=index + 1)

    for index, (status, header, lines) in enumerate(DELIVERIES):
        _create("delivery", status, header, lines, user_index=index + 2)

    for index, (status, header, lines) in enumerate(ADJUSTMENTS):
        _create("adjustment", status, header, lines, user_index=index)


def main() -> None:
    from . import create_app

    app = create_app()
    with app.app_context():
        seed()
        kpis = engine.dashboard_kpis()
        print("StockSense database seeded.")
        print(f"  products          {kpis['total_products']}")
        print(f"  in stock          {kpis['products_in_stock']} ({kpis['total_units']:,.0f} units)")
        print(f"  low / out         {kpis['low_stock']} / {kpis['out_of_stock']}")
        print(f"  pending receipts  {kpis['pending_receipts']}")
        print(f"  pending delivery  {kpis['pending_deliveries']}")
        print(f"  transfers         {kpis['scheduled_transfers']}")
        print(f"  ledger entries    {kpis['ledger_entries']}")
        print(f"  inventory value   {kpis['inventory_value']:,.2f}")
        print()
        print(f"  Sign in with {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
