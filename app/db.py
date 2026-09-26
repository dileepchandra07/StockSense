"""SQLite access layer.

One connection per request, stored on Flask's ``g``. Row access is by name
(``row["sku"]``) because raw tuples make the query code unreadable.
"""

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db() -> sqlite3.Connection:
    """The request-scoped connection."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exception=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Create the schema. Idempotent."""
    db = get_db()
    db.executescript(SCHEMA_PATH.read_text())
    db.commit()


def query(sql: str, args=(), one: bool = False):
    """Run a SELECT. Returns rows, or a single row when ``one`` is set."""
    cursor = get_db().execute(sql, args)
    rows = cursor.fetchall()
    cursor.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, args=()) -> int:
    """Run a write statement and commit. Returns the new row id."""
    db = get_db()
    cursor = db.execute(sql, args)
    db.commit()
    row_id = cursor.lastrowid
    cursor.close()
    return row_id


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
