"""Settings: warehouses and their locations."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from . import engine
from .auth import login_required
from .db import execute, query

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/warehouses")
@login_required
def warehouses():
    rows = query("""
        SELECT w.*,
               (SELECT COUNT(*) FROM locations l WHERE l.warehouse_id = w.id) AS location_count,
               (SELECT COUNT(*) FROM documents d
                 WHERE d.src_warehouse_id = w.id OR d.dst_warehouse_id = w.id) AS document_count
        FROM warehouses w
        ORDER BY w.code
    """)
    return render_template("settings/warehouses.html", warehouses=rows)


@bp.route("/warehouses/new", methods=("GET", "POST"))
@login_required
def create_warehouse():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        name = request.form.get("name", "").strip()
        address = request.form.get("address", "").strip()

        errors = []
        if not code:
            errors.append("A warehouse code is required.")
        if not name:
            errors.append("A warehouse name is required.")
        if code and query("SELECT 1 FROM warehouses WHERE code = ?", (code,), one=True):
            errors.append(f"Warehouse {code} already exists.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("settings/warehouse_form.html", form=request.form)

        warehouse_id = execute(
            "INSERT INTO warehouses (code, name, address, created_at) VALUES (?, ?, ?, ?)",
            (code, name, address, engine.now()),
        )
        # Every warehouse needs somewhere to put stock, so create the default
        # location immediately -- otherwise a new warehouse cannot receive.
        execute(
            "INSERT INTO locations (warehouse_id, code, name, kind) VALUES (?, ?, ?, 'internal')",
            (warehouse_id, f"{code}/STOCK", "Stock area"),
        )
        flash(f"Warehouse {code} created with a default stock location.", "success")
        return redirect(url_for("settings.warehouse_detail", warehouse_id=warehouse_id))

    return render_template("settings/warehouse_form.html", form={})


@bp.route("/warehouses/<int:warehouse_id>", methods=("GET", "POST"))
@login_required
def warehouse_detail(warehouse_id):
    warehouse = query("SELECT * FROM warehouses WHERE id = ?", (warehouse_id,), one=True)
    if warehouse is None:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        address = request.form.get("address", "").strip()
        if not name:
            flash("A warehouse name is required.", "error")
        else:
            execute(
                "UPDATE warehouses SET name = ?, address = ? WHERE id = ?",
                (name, address, warehouse_id),
            )
            flash("Warehouse updated.", "success")
        return redirect(url_for("settings.warehouse_detail", warehouse_id=warehouse_id))

    return render_template(
        "settings/warehouse_detail.html",
        warehouse=warehouse,
        locations=query(
            "SELECT * FROM locations WHERE warehouse_id = ? ORDER BY code", (warehouse_id,)
        ),
        levels=engine.stock_levels(warehouse_id=warehouse_id),
    )


@bp.route("/warehouses/<int:warehouse_id>/locations", methods=("POST",))
@login_required
def add_location(warehouse_id):
    warehouse = query("SELECT * FROM warehouses WHERE id = ?", (warehouse_id,), one=True)
    if warehouse is None:
        abort(404)

    code = request.form.get("code", "").strip().upper()
    name = request.form.get("name", "").strip()
    full_code = f"{warehouse['code']}/{code}" if code else ""

    if not code:
        flash("A location code is required.", "error")
    elif query("SELECT 1 FROM locations WHERE code = ?", (full_code,), one=True):
        flash(f"Location {full_code} already exists.", "error")
    else:
        execute(
            "INSERT INTO locations (warehouse_id, code, name, kind) VALUES (?, ?, ?, 'internal')",
            (warehouse_id, full_code, name or code),
        )
        flash(f"Location {full_code} added.", "success")

    return redirect(url_for("settings.warehouse_detail", warehouse_id=warehouse_id))


@bp.route("/locations/<int:location_id>/delete", methods=("POST",))
@login_required
def delete_location(location_id):
    location = query("SELECT * FROM locations WHERE id = ?", (location_id,), one=True)
    if location is None:
        abort(404)

    moved = query(
        "SELECT COUNT(*) AS n FROM stock_moves WHERE src_location_id = ? OR dst_location_id = ?",
        (location_id, location_id),
        one=True,
    )["n"]
    if moved:
        flash(
            f"{location['code']} is referenced by {moved} ledger "
            f"{'entry' if moved == 1 else 'entries'} and cannot be removed.",
            "error",
        )
    else:
        execute("DELETE FROM locations WHERE id = ?", (location_id,))
        flash(f"Location {location['code']} removed.", "success")

    return redirect(
        url_for("settings.warehouse_detail", warehouse_id=location["warehouse_id"])
    )
