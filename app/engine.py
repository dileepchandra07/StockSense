"""Inventory domain service.

Two rules govern everything here:

1. ``stock_moves`` is the only source of truth for quantity. Levels are derived
   by folding it (the ``v_stock_levels`` view). No code sets an on-hand number.
2. Documents carry a status workflow. **Stock changes only when a document is
   validated** -- that is, when it reaches ``done``. Draft, waiting, ready and
   canceled documents have no effect on quantity.

See ``docs/domain-model.md`` for the invariants these functions enforce.
"""

from datetime import datetime, timedelta, timezone

from .db import execute, get_db, query

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

DOC_TYPES = {
    "receipt": {"label": "Receipt", "prefix": "WH/IN", "plural": "Receipts"},
    "delivery": {"label": "Delivery Order", "prefix": "WH/OUT", "plural": "Delivery Orders"},
    "internal": {"label": "Internal Transfer", "prefix": "WH/INT", "plural": "Internal Transfers"},
    "adjustment": {"label": "Inventory Adjustment", "prefix": "WH/ADJ", "plural": "Adjustments"},
}

STATUSES = ["draft", "waiting", "ready", "done", "canceled"]

STATUS_LABELS = {
    "draft": "Draft",
    "waiting": "Waiting",
    "ready": "Ready",
    "done": "Done",
    "canceled": "Canceled",
}

# Statuses that mean "still in flight" -- what the dashboard counts as pending.
OPEN_STATUSES = ("draft", "waiting", "ready")

VIRTUAL_LOCATIONS = {
    "supplier": ("__supplier__", "Suppliers"),
    "customer": ("__customer__", "Customers"),
    "adjustment": ("__adjustment__", "Inventory Adjustments"),
}


class DomainError(Exception):
    """A business rule was violated. Message is safe to show the user."""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def virtual_location(kind: str):
    row = query(
        "SELECT * FROM locations WHERE kind = ? AND warehouse_id IS NULL",
        (kind,),
        one=True,
    )
    if row is None:
        raise DomainError(f"Virtual location {kind!r} is missing from the database")
    return row


def internal_locations(warehouse_id=None):
    sql = "SELECT * FROM locations WHERE kind = 'internal'"
    args = []
    if warehouse_id:
        sql += " AND warehouse_id = ?"
        args.append(warehouse_id)
    return query(sql + " ORDER BY code", args)


def default_internal_location(warehouse_id: int):
    """The location a document falls back to when no bin is chosen."""
    row = query(
        "SELECT * FROM locations WHERE warehouse_id = ? AND kind = 'internal' ORDER BY id LIMIT 1",
        (warehouse_id,),
        one=True,
    )
    if row is None:
        raise DomainError("That warehouse has no internal location to move stock into")
    return row


# ---------------------------------------------------------------------------
# Derived levels
# ---------------------------------------------------------------------------


def stock_levels(*, product_id=None, warehouse_id=None, internal_only=True, nonzero=True):
    """Every ``(product, location)`` level, folded from the ledger."""
    sql = """
        SELECT l.product_id, l.location_id, l.qty,
               loc.code AS location_code, loc.name AS location_name,
               loc.kind AS location_kind, loc.warehouse_id,
               w.code AS warehouse_code, w.name AS warehouse_name,
               p.sku, p.name AS product_name, p.uom
        FROM v_stock_levels l
        JOIN locations  loc ON loc.id = l.location_id
        JOIN products   p   ON p.id = l.product_id
        LEFT JOIN warehouses w ON w.id = loc.warehouse_id
        WHERE 1 = 1
    """
    args = []
    if internal_only:
        sql += " AND loc.kind = 'internal'"
    if product_id:
        sql += " AND l.product_id = ?"
        args.append(product_id)
    if warehouse_id:
        sql += " AND loc.warehouse_id = ?"
        args.append(warehouse_id)
    if nonzero:
        sql += " AND l.qty != 0"
    return query(sql + " ORDER BY p.sku, loc.code", args)


def level_at(product_id: int, location_id: int) -> float:
    row = query(
        "SELECT qty FROM v_stock_levels WHERE product_id = ? AND location_id = ?",
        (product_id, location_id),
        one=True,
    )
    return float(row["qty"]) if row else 0.0


def on_hand(product_id: int, warehouse_id=None) -> float:
    """Total internal stock for a product, optionally scoped to one warehouse."""
    sql = """
        SELECT COALESCE(SUM(l.qty), 0) AS qty
        FROM v_stock_levels l
        JOIN locations loc ON loc.id = l.location_id
        WHERE l.product_id = ? AND loc.kind = 'internal'
    """
    args = [product_id]
    if warehouse_id:
        sql += " AND loc.warehouse_id = ?"
        args.append(warehouse_id)
    return float(query(sql, args, one=True)["qty"])


def on_hand_by_warehouse(product_id: int):
    """``{warehouse_code: qty}`` for the product detail page."""
    rows = query(
        """
        SELECT w.code AS warehouse_code, w.name AS warehouse_name, SUM(l.qty) AS qty
        FROM v_stock_levels l
        JOIN locations  loc ON loc.id = l.location_id
        JOIN warehouses w   ON w.id = loc.warehouse_id
        WHERE l.product_id = ? AND loc.kind = 'internal'
        GROUP BY w.id
        ORDER BY w.code
        """,
        (product_id,),
    )
    return rows


def products_with_stock():
    """Products joined to their total on-hand and category, for list views."""
    return query("""
        SELECT p.*, c.name AS category_name,
               COALESCE((
                   SELECT SUM(l.qty) FROM v_stock_levels l
                   JOIN locations loc ON loc.id = l.location_id
                   WHERE l.product_id = p.id AND loc.kind = 'internal'
               ), 0) AS on_hand
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_active = 1
        ORDER BY p.sku
    """)


def low_stock():
    """Products at or below their reorder minimum, but not yet out of stock."""
    return [row for row in products_with_stock() if 0 < row["on_hand"] <= row["reorder_min"]]


def out_of_stock():
    return [row for row in products_with_stock() if row["on_hand"] <= 0]


def inventory_value() -> float:
    row = query("""
        SELECT COALESCE(SUM(l.qty * p.unit_cost), 0) AS value
        FROM v_stock_levels l
        JOIN locations loc ON loc.id = l.location_id
        JOIN products  p   ON p.id = l.product_id
        WHERE loc.kind = 'internal'
    """, one=True)
    return float(row["value"])


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def next_reference(doc_type: str) -> str:
    """Human-readable document number, e.g. ``WH/IN/00007``."""
    prefix = DOC_TYPES[doc_type]["prefix"]
    count = query(
        "SELECT COUNT(*) AS n FROM documents WHERE doc_type = ?", (doc_type,), one=True
    )["n"]
    while True:
        count += 1
        reference = f"{prefix}/{count:05d}"
        exists = query("SELECT 1 FROM documents WHERE reference = ?", (reference,), one=True)
        if exists is None:
            return reference


def get_document(document_id: int):
    return query(
        """
        SELECT d.*,
               sw.code AS src_warehouse_code, sw.name AS src_warehouse_name,
               dw.code AS dst_warehouse_code, dw.name AS dst_warehouse_name,
               u.name  AS created_by_name, v.name AS validated_by_name
        FROM documents d
        LEFT JOIN warehouses sw ON sw.id = d.src_warehouse_id
        LEFT JOIN warehouses dw ON dw.id = d.dst_warehouse_id
        LEFT JOIN users      u  ON u.id  = d.created_by
        LEFT JOIN users      v  ON v.id  = d.validated_by
        WHERE d.id = ?
        """,
        (document_id,),
        one=True,
    )


def document_lines(document_id: int):
    return query(
        """
        SELECT dl.*, p.sku, p.name AS product_name, p.uom, p.unit_cost,
               sl.code AS src_code, dl_src.name AS src_name,
               dl_dst.code AS dst_code, dl_dst.name AS dst_name
        FROM document_lines dl
        JOIN products p ON p.id = dl.product_id
        LEFT JOIN locations sl     ON sl.id     = dl.src_location_id
        LEFT JOIN locations dl_src ON dl_src.id = dl.src_location_id
        LEFT JOIN locations dl_dst ON dl_dst.id = dl.dst_location_id
        WHERE dl.document_id = ?
        ORDER BY dl.id
        """,
        (document_id,),
    )


def list_documents(
    *, doc_type=None, status=None, warehouse_id=None, category_id=None, search=None, limit=200
):
    """Document list with the dashboard's dynamic filters applied."""
    sql = """
        SELECT d.*,
               sw.code AS src_warehouse_code, dw.code AS dst_warehouse_code,
               u.name  AS created_by_name,
               (SELECT COUNT(*) FROM document_lines dl WHERE dl.document_id = d.id) AS line_count,
               (SELECT COALESCE(SUM(dl.qty), 0) FROM document_lines dl
                WHERE dl.document_id = d.id) AS total_qty
        FROM documents d
        LEFT JOIN warehouses sw ON sw.id = d.src_warehouse_id
        LEFT JOIN warehouses dw ON dw.id = d.dst_warehouse_id
        LEFT JOIN users      u  ON u.id  = d.created_by
        WHERE 1 = 1
    """
    args = []
    if doc_type:
        sql += " AND d.doc_type = ?"
        args.append(doc_type)
    if status:
        sql += " AND d.status = ?"
        args.append(status)
    if warehouse_id:
        sql += " AND (d.src_warehouse_id = ? OR d.dst_warehouse_id = ?)"
        args.extend([warehouse_id, warehouse_id])
    if category_id:
        sql += """ AND EXISTS (
            SELECT 1 FROM document_lines dl JOIN products p ON p.id = dl.product_id
            WHERE dl.document_id = d.id AND p.category_id = ?
        )"""
        args.append(category_id)
    if search:
        sql += " AND (d.reference LIKE ? OR d.supplier LIKE ?)"
        args.extend([f"%{search}%", f"%{search}%"])
    sql += " ORDER BY d.id DESC LIMIT ?"
    args.append(limit)
    return query(sql, args)


def create_document(*, doc_type, user_id, supplier="", src_warehouse_id=None,
                    dst_warehouse_id=None, notes=""):
    if doc_type not in DOC_TYPES:
        raise DomainError(f"Unknown document type {doc_type!r}")
    if doc_type == "receipt" and not dst_warehouse_id:
        raise DomainError("A receipt needs a destination warehouse")
    if doc_type == "delivery" and not src_warehouse_id:
        raise DomainError("A delivery needs a source warehouse")
    if doc_type in ("internal", "adjustment") and not (src_warehouse_id or dst_warehouse_id):
        raise DomainError("Choose a warehouse")
    if doc_type == "internal" and not dst_warehouse_id:
        raise DomainError("An internal transfer needs a destination warehouse")
    # Note: a same-warehouse transfer is legitimate -- rack A to rack B is a
    # first-class case. The guard that matters is that the two *locations*
    # differ, which validate_document enforces.

    return execute(
        """
        INSERT INTO documents
            (doc_type, reference, status, supplier, src_warehouse_id, dst_warehouse_id,
             notes, created_by, created_at)
        VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?)
        """,
        (
            doc_type,
            next_reference(doc_type),
            supplier,
            src_warehouse_id,
            dst_warehouse_id,
            notes,
            user_id,
            now(),
        ),
    )


def add_line(document_id, product_id, qty=0, counted_qty=None,
             src_location_id=None, dst_location_id=None):
    return execute(
        """
        INSERT INTO document_lines
            (document_id, product_id, qty, counted_qty, src_location_id, dst_location_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (document_id, product_id, qty, counted_qty, src_location_id, dst_location_id),
    )


def delete_line(line_id: int) -> None:
    execute("DELETE FROM document_lines WHERE id = ?", (line_id,))


def set_status(document_id: int, status: str) -> None:
    if status not in STATUSES:
        raise DomainError(f"Unknown status {status!r}")
    if status == "done":
        raise DomainError("Use validate to complete a document")
    document = get_document(document_id)
    if document is None:
        raise DomainError("Document not found")
    if document["status"] == "done":
        raise DomainError("A validated document cannot be changed")
    execute("UPDATE documents SET status = ? WHERE id = ?", (status, document_id))


# ---------------------------------------------------------------------------
# Validation -- the only path that changes stock
# ---------------------------------------------------------------------------


def validate_document(document_id: int, user_id: int) -> int:
    """Apply a document's lines to the ledger and mark it done.

    Returns the number of ledger entries written. Raises ``DomainError`` if the
    document would drive stock negative -- the system refuses to record an
    impossible state rather than silently going into the red.
    """
    db = get_db()
    document = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if document is None:
        raise DomainError("Document not found")
    if document["status"] == "done":
        raise DomainError("This document has already been validated")
    if document["status"] == "canceled":
        raise DomainError("A canceled document cannot be validated")

    lines = db.execute(
        "SELECT * FROM document_lines WHERE document_id = ?", (document_id,)
    ).fetchall()
    if not lines:
        raise DomainError("Add at least one product line before validating")

    doc_type = document["doc_type"]
    supplier_loc = virtual_location("supplier")["id"]
    customer_loc = virtual_location("customer")["id"]
    adjustment_loc = virtual_location("adjustment")["id"]

    # Build the moves this document implies, validating as we go.
    planned = []  # (product_id, src, dst, qty)
    for line in lines:
        product_id = line["product_id"]

        if doc_type == "adjustment":
            if line["counted_qty"] is None:
                raise DomainError("Every adjustment line needs a counted quantity")
            location_id = line["dst_location_id"] or default_internal_location(
                document["src_warehouse_id"] or document["dst_warehouse_id"]
            )["id"]
            delta = float(line["counted_qty"]) - level_at(product_id, location_id)
            if delta == 0:
                continue  # already matches; record nothing
            if delta > 0:
                planned.append((product_id, adjustment_loc, location_id, delta))
            else:
                planned.append((product_id, location_id, adjustment_loc, -delta))
            continue

        if float(line["qty"]) <= 0:
            raise DomainError("Line quantities must be greater than zero")

        if doc_type == "receipt":
            src = supplier_loc
            dst = line["dst_location_id"] or default_internal_location(
                document["dst_warehouse_id"]
            )["id"]
        elif doc_type == "delivery":
            src = line["src_location_id"] or default_internal_location(
                document["src_warehouse_id"]
            )["id"]
            dst = customer_loc
        else:  # internal
            src = line["src_location_id"] or default_internal_location(
                document["src_warehouse_id"]
            )["id"]
            dst = line["dst_location_id"] or default_internal_location(
                document["dst_warehouse_id"]
            )["id"]

        if src == dst:
            raise DomainError("A line cannot move stock to the location it came from")
        planned.append((product_id, src, dst, float(line["qty"])))

    # Availability guard. Aggregate per (product, source) so multiple lines
    # drawing on the same location are checked together, not one at a time.
    draws = {}
    for product_id, src, _dst, qty in planned:
        if doc_type in ("delivery", "internal"):
            draws[(product_id, src)] = draws.get((product_id, src), 0.0) + qty
    for (product_id, src), total in draws.items():
        available = level_at(product_id, src)
        if total > available:
            product = db.execute(
                "SELECT sku FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            location = db.execute(
                "SELECT code FROM locations WHERE id = ?", (src,)
            ).fetchone()
            raise DomainError(
                f"Not enough stock: {product['sku']} has {available:g} at "
                f"{location['code']} but the document needs {total:g}"
            )

    if not planned:
        raise DomainError("Nothing to do -- every line already matches the recorded stock")

    timestamp = now()
    with db:  # single transaction: moves and status change together, or neither
        for product_id, src, dst, qty in planned:
            db.execute(
                """
                INSERT INTO stock_moves
                    (product_id, src_location_id, dst_location_id, qty, kind,
                     document_id, reference, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, src, dst, qty, doc_type, document_id,
                 document["reference"], timestamp, user_id),
            )
        db.execute(
            "UPDATE documents SET status = 'done', validated_at = ?, validated_by = ? WHERE id = ?",
            (timestamp, user_id, document_id),
        )
    return len(planned)


# ---------------------------------------------------------------------------
# Move history
# ---------------------------------------------------------------------------


def move_history(*, product_id=None, warehouse_id=None, doc_type=None, search=None, limit=300):
    """The ledger, newest first, with everything a human needs to trace a number."""
    sql = """
        SELECT m.*, p.sku, p.name AS product_name, p.uom,
               sl.code AS src_code, sl.name AS src_name, sl.kind AS src_kind,
               dl.code AS dst_code, dl.name AS dst_name, dl.kind AS dst_kind,
               u.name  AS created_by_name,
               d.reference AS document_reference, d.status AS document_status
        FROM stock_moves m
        JOIN products  p  ON p.id  = m.product_id
        JOIN locations sl ON sl.id = m.src_location_id
        JOIN locations dl ON dl.id = m.dst_location_id
        LEFT JOIN users     u ON u.id = m.created_by
        LEFT JOIN documents d ON d.id = m.document_id
        WHERE 1 = 1
    """
    args = []
    if product_id:
        sql += " AND m.product_id = ?"
        args.append(product_id)
    if doc_type:
        sql += " AND m.kind = ?"
        args.append(doc_type)
    if warehouse_id:
        sql += " AND (sl.warehouse_id = ? OR dl.warehouse_id = ?)"
        args.extend([warehouse_id, warehouse_id])
    if search:
        sql += " AND (m.reference LIKE ? OR p.sku LIKE ? OR p.name LIKE ?)"
        args.extend([f"%{search}%"] * 3)
    sql += " ORDER BY m.id DESC LIMIT ?"
    args.append(limit)
    return query(sql, args)


def product_moves(product_id: int, limit=100):
    return move_history(product_id=product_id, limit=limit)


def document_moves(document_id: int):
    """The ledger entries this document wrote. Empty until it is validated."""
    return query(
        """
        SELECT m.*, p.sku, p.name AS product_name, p.uom,
               sl.code AS src_code, sl.kind AS src_kind,
               dl.code AS dst_code, dl.kind AS dst_kind,
               u.name  AS created_by_name
        FROM stock_moves m
        JOIN products  p  ON p.id  = m.product_id
        JOIN locations sl ON sl.id = m.src_location_id
        JOIN locations dl ON dl.id = m.dst_location_id
        LEFT JOIN users u ON u.id  = m.created_by
        WHERE m.document_id = ?
        ORDER BY m.id
        """,
        (document_id,),
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def dashboard_kpis() -> dict:
    """The five KPIs the spec asks for, plus inventory value."""
    in_stock = query("""
        SELECT COUNT(DISTINCT l.product_id) AS n
        FROM v_stock_levels l JOIN locations loc ON loc.id = l.location_id
        WHERE loc.kind = 'internal' AND l.qty > 0
    """, one=True)["n"]

    total_units = query("""
        SELECT COALESCE(SUM(l.qty), 0) AS n
        FROM v_stock_levels l JOIN locations loc ON loc.id = l.location_id
        WHERE loc.kind = 'internal'
    """, one=True)["n"]

    def pending(doc_type):
        return query(
            f"""SELECT COUNT(*) AS n FROM documents
                WHERE doc_type = ? AND status IN ({','.join('?' * len(OPEN_STATUSES))})""",
            (doc_type, *OPEN_STATUSES),
            one=True,
        )["n"]

    return {
        "products_in_stock": in_stock,
        "total_units": total_units,
        "total_products": query(
            "SELECT COUNT(*) AS n FROM products WHERE is_active = 1", one=True
        )["n"],
        "low_stock": len(low_stock()),
        "out_of_stock": len(out_of_stock()),
        "pending_receipts": pending("receipt"),
        "pending_deliveries": pending("delivery"),
        "scheduled_transfers": pending("internal"),
        "pending_adjustments": pending("adjustment"),
        "inventory_value": inventory_value(),
        "ledger_entries": query("SELECT COUNT(*) AS n FROM stock_moves", one=True)["n"],
    }


def recent_moves(limit=8):
    return move_history(limit=limit)


def status_counts() -> dict:
    rows = query("SELECT status, COUNT(*) AS n FROM documents GROUP BY status")
    return {row["status"]: row["n"] for row in rows}


def type_counts() -> dict:
    rows = query("SELECT doc_type, COUNT(*) AS n FROM documents GROUP BY doc_type")
    return {row["doc_type"]: row["n"] for row in rows}
