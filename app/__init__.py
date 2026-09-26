"""StockSense application factory."""

import os
from pathlib import Path

from flask import Flask, g, redirect, render_template, url_for

from . import db as db_module
from . import engine

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app(test_config=None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "stocksense-dev-secret"),
        DATABASE=os.environ.get("DATABASE", str(BASE_DIR / "stocksense.db")),
    )
    if test_config:
        app.config.update(test_config)

    db_module.init_app(app)

    from . import auth, views_dashboard, views_operations, views_products, views_settings

    app.register_blueprint(auth.bp)
    app.register_blueprint(views_dashboard.bp)
    app.register_blueprint(views_products.bp)
    app.register_blueprint(views_operations.bp)
    app.register_blueprint(views_settings.bp)

    # --- template helpers ---------------------------------------------------

    @app.template_filter("money")
    def money(value):
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return "0.00"

    @app.template_filter("qty")
    def qty(value):
        """Quantities read better without a trailing .0 on whole numbers."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "0"
        return f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"

    @app.context_processor
    def inject_vocabulary():
        return {
            "DOC_TYPES": engine.DOC_TYPES,
            "STATUSES": engine.STATUSES,
            "STATUS_LABELS": engine.STATUS_LABELS,
            "OPEN_STATUSES": engine.OPEN_STATUSES,
        }

    # --- routes -------------------------------------------------------------

    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))
        return redirect(url_for("dashboard.index"))

    @app.errorhandler(404)
    def not_found(error):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(error):
        return render_template("500.html"), 500

    # --- CLI ----------------------------------------------------------------

    @app.cli.command("seed")
    def seed_command():
        """Rebuild the database with demo data."""
        from .seed import seed

        seed()
        print("Database seeded. Sign in with admin@stocksense.dev / demo1234")

    # Create the schema on first boot so a fresh clone just works.
    with app.app_context():
        db_module.init_db()

    return app
