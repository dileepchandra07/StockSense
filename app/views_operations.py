"""Operations: receipts, delivery orders, internal transfers, adjustments.

All four are documents with the same shape and the same status workflow. Stock
changes only on validation.
"""

from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request, url_for,
)

from . import engine
from .auth import login_required
from .db import execute, query

bp = Blueprint("operations", __name__)


def _require_doc_type(doc_type: str) -> str:
    if doc_type not in engine.DOC_TYPES:
        abort(404)
    return doc_type


def _form_options():
    return {
        "warehouses": query("SELECT * FROM warehouses ORDER BY code"),
        "categories": query("SELECT * FROM categories ORDER BY name"),
        "products": query("SELECT * FROM products WHERE is_active = 1 ORDER BY sku"),
    }


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


@bp.route("/operations/<doc_type>")
@login_required
def listing(doc_type):
    doc_type = _require_doc_type(doc_type)
    filters = {
        "doc_type": doc_type,
        "status": request.args.get("status") or None,
        "warehouse_id": request.args.get("warehouse", type=int),
        "category_id": request.args.get("category", type=int),
        "search": request.args.get("q") or None,
    }
    return render_template(
        "operations/list.html",
        doc_type=doc_type,
        meta=engine.DOC_TYPES[doc_type],
        documents=engine.list_documents(**filters),
        filters=filters,
        has_filters=any(filters.values()),
        **_form_options(),
    )


@bp.route("/operations")
@login_required
def all_operations():
    return render_template(
        "operations/index.html",
        documents=engine.list_documents(limit=40),
        kpis=engine.dashboard_kpis(),
        type_counts=engine.type_counts(),
        status_counts=engine.status_counts(),
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@bp.route("/operations/<doc_type>/new", methods=("GET", "POST"))
@login_required
def create(doc_type):
    doc_type = _require_doc_type(doc_type)
    meta = engine.DOC_TYPES[doc_type]
    options = _form_options()

    if request.method == "POST":
        try:
            document_id = engine.create_document(
                doc_type=doc_type,
                user_id=g.user["id"],
                supplier=request.form.get("supplier", "").strip(),
                src_warehouse_id=request.form.get("src_warehouse_id", type=int),
                dst_warehouse_id=request.form.get("dst_warehouse_id", type=int),
                notes=request.form.get("notes", "").strip(),
            )
        except engine.DomainError as error:
            flash(str(error), "error")
            return render_template(
                "operations/form.html",
                doc_type=doc_type, meta=meta, form=request.form, **options,
            )

        flash(
            f"{meta['label']} created as a draft. Add the products, then validate it.",
            "success",
        )
        return redirect(url_for("operations.detail", document_id=document_id))

    return render_template(
        "operations/form.html", doc_type=doc_type, meta=meta, form={}, **options
    )


# ---------------------------------------------------------------------------
# Detail and line editing
# ---------------------------------------------------------------------------


def _load_document(document_id):
    document = engine.get_document(document_id)
    if document is None:
        abort(404)
    return document


@bp.route("/documents/<int:document_id>")
@login_required
def detail(document_id):
    document = _load_document(document_id)
    doc_type = document["doc_type"]

    return render_template(
        "operations/detail.html",
        document=document,
        doc_type=doc_type,
        meta=engine.DOC_TYPES[doc_type],
        lines=engine.document_lines(document_id),
        moves=engine.document_moves(document_id),
        locations=query("SELECT * FROM locations WHERE kind = 'internal' ORDER BY code"),
        **_form_options(),
    )


@bp.route("/documents/<int:document_id>/lines", methods=("POST",))
@login_required
def add_line(document_id):
    document = _load_document(document_id)
    if document["status"] != "draft":
        flash("Lines can only be changed while a document is a draft.", "error")
        return redirect(url_for("operations.detail", document_id=document_id))

    product_id = request.form.get("product_id", type=int)
    if not product_id:
        flash("Choose a product.", "error")
        return redirect(url_for("operations.detail", document_id=document_id))

    if document["doc_type"] == "adjustment":
        counted = request.form.get("counted_qty", type=float)
        if counted is None:
            flash("Enter the counted quantity.", "error")
            return redirect(url_for("operations.detail", document_id=document_id))
        engine.add_line(
            document_id,
            product_id,
            qty=0,
            counted_qty=counted,
            dst_location_id=request.form.get("location_id", type=int),
        )
    else:
        qty = request.form.get("qty", type=float)
        if not qty or qty <= 0:
            flash("Enter a quantity greater than zero.", "error")
            return redirect(url_for("operations.detail", document_id=document_id))
        engine.add_line(
            document_id,
            product_id,
            qty=qty,
            src_location_id=request.form.get("src_location_id", type=int),
            dst_location_id=request.form.get("dst_location_id", type=int),
        )

    flash("Line added.", "success")
    return redirect(url_for("operations.detail", document_id=document_id))


@bp.route("/documents/<int:document_id>/lines/<int:line_id>/delete", methods=("POST",))
@login_required
def delete_line(document_id, line_id):
    document = _load_document(document_id)
    if document["status"] != "draft":
        flash("Lines can only be changed while a document is a draft.", "error")
        return redirect(url_for("operations.detail", document_id=document_id))

    engine.delete_line(document_id, line_id)
    flash("Line removed.", "success")
    return redirect(url_for("operations.detail", document_id=document_id))


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


@bp.route("/documents/<int:document_id>/status", methods=("POST",))
@login_required
def set_status(document_id):
    _load_document(document_id)
    status = request.form.get("status", "")
    try:
        engine.set_status(document_id, status)
        flash(f"Status set to {engine.STATUS_LABELS.get(status, status)}.", "success")
    except engine.DomainError as error:
        flash(str(error), "error")
    return redirect(url_for("operations.detail", document_id=document_id))


@bp.route("/documents/<int:document_id>/validate", methods=("POST",))
@login_required
def validate(document_id):
    document = _load_document(document_id)
    try:
        count = engine.validate_document(document_id, user_id=g.user["id"])
    except engine.DomainError as error:
        flash(str(error), "error")
        return redirect(url_for("operations.detail", document_id=document_id))

    flash(
        f"{document['reference']} validated. {count} ledger "
        f"{'entry' if count == 1 else 'entries'} written.",
        "success",
    )
    return redirect(url_for("operations.detail", document_id=document_id))


@bp.route("/documents/<int:document_id>/delete", methods=("POST",))
@login_required
def delete(document_id):
    document = _load_document(document_id)
    if document["status"] == "done":
        flash("A validated document cannot be deleted -- its moves are in the ledger.", "error")
        return redirect(url_for("operations.detail", document_id=document_id))

    execute("DELETE FROM documents WHERE id = ?", (document_id,))
    flash(f"{document['reference']} deleted.", "success")
    return redirect(url_for("operations.listing", doc_type=document["doc_type"]))


# ---------------------------------------------------------------------------
# Move history -- the ledger
# ---------------------------------------------------------------------------


@bp.route("/moves")
@login_required
def moves():
    filters = {
        "product_id": request.args.get("product", type=int),
        "warehouse_id": request.args.get("warehouse", type=int),
        "doc_type": request.args.get("doc_type") or None,
        "search": request.args.get("q") or None,
    }
    return render_template(
        "operations/moves.html",
        moves=engine.move_history(**filters, limit=400),
        filters=filters,
        has_filters=any(filters.values()),
        **_form_options(),
    )
