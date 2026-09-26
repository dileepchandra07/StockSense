-- StockSense schema.
--
-- The design decision that carries everything: stock_moves is an append-only
-- ledger and the ONLY source of truth for quantity. Levels are derived from it
-- by the v_stock_levels view. Nothing writes an on-hand number directly.
--
-- Documents carry a status workflow (draft -> waiting -> ready -> done /
-- canceled). Stock changes ONLY when a document reaches 'done'.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Identity
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'Inventory Manager',
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS password_resets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL COLLATE NOCASE,
    otp        TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Master data
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name        TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    uom         TEXT NOT NULL DEFAULT 'unit',
    unit_cost   REAL NOT NULL DEFAULT 0,
    reorder_min REAL NOT NULL DEFAULT 0,
    reorder_max REAL NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name       TEXT NOT NULL,
    address    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- kind: internal holds real countable stock. supplier / customer / adjustment
-- are virtual counterparts representing the outside world, so every movement
-- is a uniform transfer between two locations.
CREATE TABLE IF NOT EXISTS locations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_id INTEGER REFERENCES warehouses(id) ON DELETE CASCADE,
    code         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'internal'
);

-- ---------------------------------------------------------------------------
-- Operations: documents and their lines
-- ---------------------------------------------------------------------------

-- doc_type: receipt | delivery | internal | adjustment
-- status:   draft | waiting | ready | done | canceled
CREATE TABLE IF NOT EXISTS documents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type         TEXT NOT NULL,
    reference        TEXT NOT NULL UNIQUE,
    status           TEXT NOT NULL DEFAULT 'draft',
    supplier         TEXT NOT NULL DEFAULT '',
    src_warehouse_id INTEGER REFERENCES warehouses(id),
    dst_warehouse_id INTEGER REFERENCES warehouses(id),
    notes            TEXT NOT NULL DEFAULT '',
    created_by       INTEGER REFERENCES users(id),
    created_at       TEXT NOT NULL,
    validated_at     TEXT,
    validated_by     INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS document_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    qty             REAL NOT NULL DEFAULT 0,
    counted_qty     REAL,          -- adjustments only: the physical count
    src_location_id INTEGER REFERENCES locations(id),
    dst_location_id INTEGER REFERENCES locations(id)
);

-- ---------------------------------------------------------------------------
-- The ledger. Append-only: never updated, never deleted.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stock_moves (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    src_location_id INTEGER NOT NULL REFERENCES locations(id),
    dst_location_id INTEGER NOT NULL REFERENCES locations(id),
    qty             REAL NOT NULL,          -- always strictly positive
    kind            TEXT NOT NULL,
    document_id     INTEGER REFERENCES documents(id),
    reference       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    created_by      INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_moves_product   ON stock_moves(product_id);
CREATE INDEX IF NOT EXISTS idx_moves_src       ON stock_moves(src_location_id);
CREATE INDEX IF NOT EXISTS idx_moves_dst       ON stock_moves(dst_location_id);
CREATE INDEX IF NOT EXISTS idx_moves_created   ON stock_moves(created_at);
CREATE INDEX IF NOT EXISTS idx_lines_document  ON document_lines(document_id);
CREATE INDEX IF NOT EXISTS idx_docs_type_status ON documents(doc_type, status);

-- ---------------------------------------------------------------------------
-- Derived stock levels. This view IS the level table -- there is no stored
-- on-hand quantity anywhere in the database.
-- ---------------------------------------------------------------------------

DROP VIEW IF EXISTS v_stock_levels;

CREATE VIEW v_stock_levels AS
SELECT product_id, location_id, SUM(qty) AS qty
FROM (
    SELECT product_id, dst_location_id AS location_id,  qty FROM stock_moves
    UNION ALL
    SELECT product_id, src_location_id AS location_id, -qty FROM stock_moves
)
GROUP BY product_id, location_id;

-- ---------------------------------------------------------------------------
-- Virtual locations. These represent the outside world so that goods entering
-- or leaving the business entirely are still just a transfer between two
-- locations. They have no warehouse and hold no stock.
--
-- Inserted here rather than in the seeder so a fresh database can validate a
-- receipt immediately. OR IGNORE makes re-running the schema a no-op.
-- ---------------------------------------------------------------------------

INSERT OR IGNORE INTO locations (warehouse_id, code, name, kind) VALUES
    (NULL, '__supplier__',   'Suppliers',             'supplier'),
    (NULL, '__customer__',   'Customers',             'customer'),
    (NULL, '__adjustment__', 'Inventory Adjustments', 'adjustment');
