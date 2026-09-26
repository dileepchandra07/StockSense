"""Products: catalogue, categories, per-location availability, reorder rules."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from . import engine
from .auth import login_required
from .db import execute, query

bp = Blueprint("products", __name__, url_prefix="/products")


def _categories():
    return query("SELECT * FROM categories ORDER BY name")


@bp.route("/")
@login_required
def index():
    search = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    stock_filter = request.args.get("stock", "")

    rows = engine.products_with_stock()

    if search:
        needle = search.lower()
        rows = [
            row for row in rows
            if needle in row["sku"].lower() or needle in row["name"].lower()
        ]
    if category_id:
        rows = [row for row in rows if row["category_id"] == category_id]
    if stock_filter == "low":
        rows = [row for row in rows if 0 < row["on_hand"] <= row["reorder_min"]]
    elif stock_filter == "out":
        # Must match engine.out_of_stock() exactly, or the dashboard KPI and the
        # filtered list disagree when someone clicks through.
        rows = [row for row in rows if row["on_hand"] <= 0]
    elif stock_filter == "in":
        rows = [row for row in rows if row["on_hand"] > 0]

    return render_template(
        "products/index.html",
        products=rows,
        categories=_categories(),
        search=search,
        category_id=category_id,
        stock_filter=stock_filter,
    )


@bp.route("/new", methods=("GET", "POST"))
@login_required
def create():
    if request.method == "POST":
        sku = request.form.get("sku", "").strip().upper()
        name = request.form.get("name", "").strip()
        category_id = request.form.get("category_id", type=int)
        uom = request.form.get("uom", "unit").strip() or "unit"
        unit_cost = request.form.get("unit_cost", type=float) or 0.0
        reorder_min = request.form.get("reorder_min", type=float) or 0.0
        reorder_max = request.form.get("reorder_max", type=float) or 0.0
        initial_stock = request.form.get("initial_stock", type=float) or 0.0
        warehouse_id = request.form.get("warehouse_id", type=int)

        errors = []
        if not sku:
            errors.append("A SKU is required.")
        if not name:
            errors.append("A product name is required.")
        if query("SELECT 1 FROM products WHERE sku = ?", (sku,), one=True):
            errors.append(f"SKU {sku} is already in use.")
        if reorder_max and reorder_min and reorder_max < reorder_min:
            errors.append("The reorder maximum cannot be below the minimum.")
        if initial_stock and not warehouse_id:
            errors.append("Choose a warehouse to place the initial stock in.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "products/form.html",
                product=request.form,
                categories=_categories(),
                warehouses=query("SELECT * FROM warehouses ORDER BY code"),
                mode="create",
            )

        product_id = execute(
            """INSERT INTO products
                   (sku, name, category_id, uom, unit_cost, reorder_min, reorder_max,
                    is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (sku, name, category_id, uom, unit_cost, reorder_min, reorder_max, engine.now()),
        )

        # Initial stock is recorded as a real receipt, not a magic number, so the
        # ledger explains where the quantity came from.
        if initial_stock and warehouse_id:
            document_id = engine.create_document(
                doc_type="receipt",
                user_id=None,
                supplier="Opening balance",
                dst_warehouse_id=warehouse_id,
                notes=f"Initial stock recorded when {sku} was created.",
            )
            engine.add_line(document_id, product_id, qty=initial_stock)
            engine.validate_document(document_id, user_id=None)

        flash(f"Product {sku} created.", "success")
        return redirect(url_for("products.detail", product_id=product_id))

    return render_template(
        "products/form.html",
        product={},
        categories=_categories(),
        warehouses=query("SELECT * FROM warehouses ORDER BY code"),
        mode="create",
    )


@bp.route("/<int:product_id>")
@login_required
def detail(product_id):
    product = query(
        """SELECT p.*, c.name AS category_name FROM products p
           LEFT JOIN categories c ON c.id = p.category_id WHERE p.id = ?""",
        (product_id,),
        one=True,
    )
    if product is None:
        flash("That product does not exist.", "error")
        return redirect(url_for("products.index"))

    return render_template(
        "products/detail.html",
        product=product,
        levels=engine.stock_levels(product_id=product_id),
        by_warehouse=engine.on_hand_by_warehouse(product_id),
        moves=engine.product_moves(product_id, limit=40),
        on_hand=engine.on_hand(product_id),
    )


@bp.route("/<int:product_id>/edit", methods=("GET", "POST"))
@login_required
def edit(product_id):
    product = query("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if product is None:
        flash("That product does not exist.", "error")
        return redirect(url_for("products.index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category_id = request.form.get("category_id", type=int)
        uom = request.form.get("uom", "unit").strip() or "unit"
        unit_cost = request.form.get("unit_cost", type=float) or 0.0
        reorder_min = request.form.get("reorder_min", type=float) or 0.0
        reorder_max = request.form.get("reorder_max", type=float) or 0.0

        errors = []
        if not name:
            errors.append("A product name is required.")
        if reorder_max and reorder_min and reorder_max < reorder_min:
            errors.append("The reorder maximum cannot be below the minimum.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "products/form.html",
                product={**dict(product), **request.form},
                categories=_categories(),
                warehouses=query("SELECT * FROM warehouses ORDER BY code"),
                mode="edit",
            )

        execute(
            """UPDATE products SET name = ?, category_id = ?, uom = ?, unit_cost = ?,
                   reorder_min = ?, reorder_max = ? WHERE id = ?""",
            (name, category_id, uom, unit_cost, reorder_min, reorder_max, product_id),
        )
        flash("Product updated.", "success")
        return redirect(url_for("products.detail", product_id=product_id))

    return render_template(
        "products/form.html",
        product=product,
        categories=_categories(),
        warehouses=query("SELECT * FROM warehouses ORDER BY code"),
        mode="edit",
    )


@bp.route("/<int:product_id>/archive", methods=("POST",))
@login_required
def archive(product_id):
    execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
    flash("Product archived. Its history is untouched.", "success")
    return redirect(url_for("products.index"))


@bp.route("/categories", methods=("POST",))
@login_required
def add_category():
    name = request.form.get("name", "").strip()
    if not name:
        flash("A category name is required.", "error")
    elif query("SELECT 1 FROM categories WHERE name = ?", (name,), one=True):
        flash(f"Category {name} already exists.", "warning")
    else:
        execute("INSERT INTO categories (name) VALUES (?)", (name,))
        flash(f"Category {name} added.", "success")
    return redirect(request.referrer or url_for("products.index"))
