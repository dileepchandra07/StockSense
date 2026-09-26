"""StockSense application factory."""

import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, current_app, g, redirect, render_template, url_for

from . import db as db_module
from . import engine

BASE_DIR = Path(__file__).resolve().parent.parent

# Timestamps are persisted as naive UTC strings. They are converted to this
# zone for display only -- storage stays UTC so the ledger means the same
# thing regardless of where it is read.
DEFAULT_DISPLAY_TZ = "Asia/Kolkata"


def _display_zone():
    """The configured display zone, or UTC if the name is unusable."""
    name = current_app.config.get("DISPLAY_TZ") or DEFAULT_DISPLAY_TZ
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        # A typo in configuration should degrade to UTC, not 500 the page.
        return timezone.utc


def _parse_utc(value):
    """Parse a stored UTC timestamp. Returns None when it is not one."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def create_app(test_config=None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "stocksense-dev-secret"),
        DATABASE=os.environ.get("DATABASE", str(BASE_DIR / "stocksense.db")),
        DISPLAY_TZ=os.environ.get("DISPLAY_TZ", DEFAULT_DISPLAY_TZ),
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

    @app.template_filter("localtime")
    def localtime(value, fmt="%d %b %Y, %H:%M"):
        """Render a stored UTC timestamp in the display timezone.

        Timestamps are written as naive UTC. Printing them raw reads as if
        they were local, which is wrong by the whole offset -- five and a
        half hours for IST, so a 09:22 UTC receipt showed as 09:22 when it
        happened at 14:52. Convert on the way out; store UTC on the way in.
        """
        stamp = _parse_utc(value)
        if stamp is None:
            # Not one of ours -- a blank, a date-only string, or free text.
            return str(value) if value else "—"
        return (
            stamp.replace(tzinfo=timezone.utc)
            .astimezone(_display_zone())
            .strftime(fmt)
        )

    @app.template_filter("ago")
    def ago(value):
        """A coarse relative age, for feeds where 'when' matters more than 'at'."""
        stamp = _parse_utc(value)
        if stamp is None:
            return "—"
        seconds = (datetime.now(timezone.utc).replace(tzinfo=None) - stamp).total_seconds()
        if seconds < 0:
            return "scheduled"
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            minutes = int(seconds // 60)
            return f"{minutes} min ago"
        if seconds < 86400:
            hours = int(seconds // 3600)
            return f"{hours} hr ago" if hours == 1 else f"{hours} hrs ago"
        days = int(seconds // 86400)
        if days < 30:
            return f"{days} day ago" if days == 1 else f"{days} days ago"
        return stamp.strftime("%d %b %Y")

    @app.template_filter("tzname")
    def tzname(value=None):
        """Short label for the display zone, e.g. 'IST'. Handles DST itself."""
        return datetime.now(_display_zone()).tzname() or "UTC"

    @app.context_processor
    def inject_vocabulary():
        return {
            "DOC_TYPES": engine.DOC_TYPES,
            "STATUSES": engine.STATUSES,
            "STATUS_LABELS": engine.STATUS_LABELS,
            "OPEN_STATUSES": engine.OPEN_STATUSES,
            "TZ_LABEL": tzname(),
            "FLOW_HINTS": engine.FLOW_HINTS,
            # Status words depend on the document type: a delivery is picked
            # and packed, a receipt is awaiting goods and then at the dock.
            "status_label": engine.status_label,
            "status_action": engine.status_action,
            "status_flow": engine.status_flow,
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
