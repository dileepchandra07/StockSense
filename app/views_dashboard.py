"""Dashboard: the landing page after sign-in.

Five KPIs and four filter dimensions, exactly as the spec asks for, plus the
recent activity an inventory manager actually opens the app to see.
"""

from flask import Blueprint, render_template, request

from . import engine
from .auth import login_required
from .db import query

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
@login_required
def index():
    filters = {
        "doc_type": request.args.get("doc_type") or None,
        "status": request.args.get("status") or None,
        "warehouse_id": request.args.get("warehouse", type=int),
        "category_id": request.args.get("category", type=int),
        "search": request.args.get("q") or None,
    }
    has_filters = any(filters.values())

    return render_template(
        "dashboard.html",
        kpis=engine.dashboard_kpis(),
        documents=engine.list_documents(**filters, limit=12),
        filters=filters,
        has_filters=has_filters,
        warehouses=query("SELECT * FROM warehouses ORDER BY code"),
        categories=query("SELECT * FROM categories ORDER BY name"),
        low=engine.low_stock()[:6],
        out=engine.out_of_stock()[:6],
        recent=engine.recent_moves(8),
        status_counts=engine.status_counts(),
        type_counts=engine.type_counts(),
    )
