"""End-to-end walkthrough of the StockSense reference engine.

Run it with::

    python3 demo.py

Builds two warehouses, four products, eight movements and four reorder rules,
then prints the derived state. Every number printed here is folded from the
ledger -- nothing is stored.
"""

from stock_engine import (
    ADJUSTMENT_LOCATION,
    CUSTOMER_LOCATION,
    SUPPLIER_LOCATION,
    MoveKind,
    StockEngine,
)

WIDTH = 66

VIRTUAL_LABELS = {
    SUPPLIER_LOCATION: "supplier",
    CUSTOMER_LOCATION: "customer",
    ADJUSTMENT_LOCATION: "adjustments",
}


def heading(text: str) -> None:
    print()
    print(text)
    print("-" * len(text))


def label(code: str) -> str:
    """Render a location code for humans."""
    return VIRTUAL_LABELS.get(code, code)


def money(value: float) -> str:
    return f"{value:,.2f}"


def build() -> StockEngine:
    """Seed a small but realistic dataset."""
    engine = StockEngine(operator="harsha")

    engine.add_warehouse("MAIN", "Main Distribution Centre", address="Plot 14, Industrial Estate")
    engine.add_warehouse("NORTH", "North Regional Depot")

    engine.add_product("WIDGET-A", "Steel widget, 12mm", category="fasteners", unit_cost=24.50)
    engine.add_product("BOLT-M8", "Hex bolt M8", category="fasteners", unit_cost=2.00)
    engine.add_product("GASKET-3", "Rubber gasket, 3in", category="seals", unit_cost=8.75)
    engine.add_product("PUMP-X", "Circulation pump X", category="machinery", unit_cost=1250.00)

    # Goods in
    engine.receive("WIDGET-A", "MAIN", 120, "PO-2026-0114")
    engine.receive("WIDGET-A", "NORTH", 40, "PO-2026-0115")
    engine.receive("BOLT-M8", "MAIN", 8, "PO-2026-0116")
    engine.receive("GASKET-3", "MAIN", 250, "PO-2026-0117")
    engine.receive("PUMP-X", "NORTH", 3, "PO-2026-0118")

    # Goods out
    engine.deliver("WIDGET-A", "MAIN", 25, "SO-2026-0431")

    # Relocation
    engine.transfer("WIDGET-A", "MAIN", "NORTH", 30, "TRF-2026-0031")

    # A miscount, corrected honestly
    engine.adjust("GASKET-3", "MAIN", 244, "ADJ-2026-0007")

    # Replenishment thresholds
    engine.set_reorder_rule("WIDGET-A", "MAIN", min_qty=50, max_qty=200)
    engine.set_reorder_rule("WIDGET-A", "NORTH", min_qty=25, max_qty=100)
    engine.set_reorder_rule("BOLT-M8", "MAIN", min_qty=50, max_qty=100)
    engine.set_reorder_rule("GASKET-3", "MAIN", min_qty=100, max_qty=400)

    return engine


def print_catalog(engine: StockEngine) -> None:
    heading("Catalog")
    for product in engine.products():
        print(
            f"  {product.sku:<10} {product.name:<24} "
            f"{money(product.unit_cost):>9} / {product.uom}"
        )


def print_network(engine: StockEngine) -> None:
    heading("Network")
    for warehouse in engine.warehouses():
        count = len(engine.locations(warehouse=warehouse.code))
        print(f"  {warehouse.code:<8} {warehouse.name:<30} {count} location(s)")


def print_moves(engine: StockEngine, kind: MoveKind, title: str) -> None:
    moves = engine.moves(kind=kind, newest_first=False)
    if not moves:
        return
    heading(title)
    for move in moves:
        print(
            f"  {move.reference:<14} {move.qty:>6g} x {move.sku:<10} "
            f"{label(move.src)} -> {label(move.dst)}"
        )


def print_on_hand(engine: StockEngine) -> None:
    heading("On hand")
    rows = engine.stock_levels()
    for row in rows:
        print(f"  {row['sku']:<10} {row['warehouse']:<8} {row['qty']:>7g}")
    print(f"  {'-' * 30}")
    total = sum(row["qty"] for row in rows)
    print(f"  {'total':<19} {total:>7g}   (across {len(rows)} lines)")


def print_availability_guard(engine: StockEngine) -> None:
    heading("Availability guard")
    print("  Attempting to deliver 500 x WIDGET-A from MAIN ...")
    try:
        engine.deliver("WIDGET-A", "MAIN", 500, "SO-2026-0432")
    except Exception as error:  # noqa: BLE001 - the refusal is the point
        print(f"  refused: {error}")
    print("  The ledger is unchanged. The system refuses to record an impossible state.")


def print_low_stock(engine: StockEngine) -> None:
    heading("Low stock")
    items = engine.low_stock()
    if not items:
        print("  Nothing below its reorder point.")
        return
    for item in items:
        print(
            f"  {item['sku']:<10} {item['warehouse']:<7} "
            f"{item['on_hand']:g} on hand, minimum {item['min_qty']:g} "
            f"-> order {item['suggested_order_qty']:g}"
        )


def print_valuation(engine: StockEngine) -> None:
    heading("Valuation")
    for warehouse_code, value in engine.valuation_by_warehouse().items():
        print(f"  {warehouse_code:<10} {money(value):>12}")
    print(f"  {'-' * 24}")
    print(f"  {'total':<10} {money(engine.valuation()):>12}")


def print_ledger(engine: StockEngine, limit: int = 6) -> None:
    heading(f"Ledger (newest {limit} of {len(engine.ledger())} moves)")
    for move in engine.moves(limit=limit):
        stamp = move.created_at.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"  #{move.id:<3} {stamp}  {move.kind.value:<10} "
            f"{move.qty:>5g} x {move.sku:<10} {move.reference}"
        )
    print()
    print("  Every number above traces back to one of these rows.")


def main() -> None:
    engine = build()

    print()
    print("StockSense reference walkthrough".center(WIDTH))
    print("=" * WIDTH)

    print_catalog(engine)
    print_network(engine)
    print_moves(engine, MoveKind.RECEIPT, "Receipts")
    print_moves(engine, MoveKind.DELIVERY, "Deliveries")
    print_moves(engine, MoveKind.TRANSFER, "Transfers")
    print_moves(engine, MoveKind.ADJUSTMENT, "Adjustments")
    print_on_hand(engine)
    print_availability_guard(engine)
    print_low_stock(engine)
    print_valuation(engine)
    print_ledger(engine)
    print()


if __name__ == "__main__":
    main()
