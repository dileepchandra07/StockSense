"""StockSense reference implementation of the inventory domain.

Standard library only, Python 3.11+. Run it with::

    python3 demo.py            # end-to-end walkthrough
    python3 -m unittest -v     # invariant tests

This module exists to pin the domain semantics down in runnable form. It is a
reference, not the product -- see ``docs/architecture.md``. The rules it enforces
are the invariants listed in ``docs/domain-model.md``:

1. Stock levels are derived from the movement ledger, never stored
2. Transfers conserve total quantity
3. Internal stock never goes negative
4. Every move carries a non-empty reference
5. Every quantity is strictly positive
6. History is immutable -- moves are appended, never edited

The design decision that carries everything: **the ledger is the only source of
truth**. There is no code path here that sets an on-hand number directly.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


__all__ = [
    "LocationKind",
    "MoveKind",
    "StockError",
    "UnknownEntity",
    "DuplicateEntity",
    "InvalidQuantity",
    "InsufficientStock",
    "Product",
    "Warehouse",
    "Location",
    "StockMove",
    "ReorderRule",
    "StockEngine",
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LocationKind(str, Enum):
    """What a location represents.

    Only ``INTERNAL`` locations hold real, countable stock. The other three are
    virtual bookkeeping locations representing the outside world, which lets
    every movement -- including goods entering or leaving the business entirely
    -- be expressed as a uniform transfer between two locations.
    """

    INTERNAL = "internal"
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    ADJUSTMENT = "adjustment"


class MoveKind(str, Enum):
    """Why a movement happened. Metadata for reporting and validation."""

    RECEIPT = "receipt"
    DELIVERY = "delivery"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StockError(Exception):
    """Base class for domain rule violations."""


class UnknownEntity(StockError):
    """A referenced product, warehouse or location does not exist."""


class DuplicateEntity(StockError):
    """A natural key is already in use."""


class InvalidQuantity(StockError):
    """A quantity was zero, negative, or otherwise unusable."""


class InsufficientStock(StockError):
    """A move would drive internal stock below zero."""


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

SUPPLIER_LOCATION = "__supplier__"
CUSTOMER_LOCATION = "__customer__"
ADJUSTMENT_LOCATION = "__adjustment__"


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    uom: str = "unit"
    category: str = "uncategorised"
    unit_cost: float = 0.0
    is_active: bool = True


@dataclass(frozen=True)
class Warehouse:
    code: str
    name: str
    address: str = ""


@dataclass(frozen=True)
class Location:
    code: str
    warehouse_code: str | None
    kind: LocationKind
    name: str = ""


@dataclass(frozen=True)
class StockMove:
    """An immutable ledger entry. Never updated, never deleted.

    ``qty`` is always strictly positive. Direction is encoded in ``src`` and
    ``dst`` -- signed quantities invite double-negation bugs, explicit endpoints
    do not.
    """

    id: int
    sku: str
    src: str
    dst: str
    qty: float
    kind: MoveKind
    reference: str
    created_at: datetime
    created_by: str


@dataclass(frozen=True)
class ReorderRule:
    sku: str
    warehouse_code: str
    min_qty: float
    max_qty: float


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class StockEngine:
    """In-memory inventory engine.

    Single-threaded by construction. That is a deliberate simplification -- this
    is a reference, not the product. See ``docs/architecture.md`` for how the
    real stack should handle concurrency.
    """

    def __init__(self, operator: str = "system") -> None:
        self.operator = operator
        self._products: dict[str, Product] = {}
        self._warehouses: dict[str, Warehouse] = {}
        self._locations: dict[str, Location] = {}
        self._moves: list[StockMove] = []
        self._rules: dict[tuple[str, str], ReorderRule] = {}
        self._default_location: dict[str, str] = {}
        self._ids = itertools.count(1)
        self._install_virtual_locations()

    def _install_virtual_locations(self) -> None:
        for code, kind, name in (
            (SUPPLIER_LOCATION, LocationKind.SUPPLIER, "Suppliers"),
            (CUSTOMER_LOCATION, LocationKind.CUSTOMER, "Customers"),
            (ADJUSTMENT_LOCATION, LocationKind.ADJUSTMENT, "Inventory adjustments"),
        ):
            self._locations[code] = Location(
                code=code, warehouse_code=None, kind=kind, name=name
            )

    # -- catalog ------------------------------------------------------------

    def add_product(
        self,
        sku: str,
        name: str,
        *,
        uom: str = "unit",
        category: str = "uncategorised",
        unit_cost: float = 0.0,
        is_active: bool = True,
    ) -> Product:
        sku = sku.strip().upper()
        if not sku:
            raise ValueError("sku must not be empty")
        if sku in self._products:
            raise DuplicateEntity(f"A product with sku {sku!r} already exists")
        if unit_cost < 0:
            raise ValueError("unit_cost must not be negative")
        product = Product(
            sku=sku,
            name=name,
            uom=uom,
            category=category,
            unit_cost=float(unit_cost),
            is_active=is_active,
        )
        self._products[sku] = product
        return product

    def get_product(self, sku: str) -> Product:
        try:
            return self._products[sku.strip().upper()]
        except KeyError:
            raise UnknownEntity(f"No product with sku {sku!r}") from None

    def products(self) -> list[Product]:
        return sorted(self._products.values(), key=lambda p: p.sku)

    # -- network ------------------------------------------------------------

    def add_warehouse(self, code: str, name: str, *, address: str = "") -> Warehouse:
        """Create a warehouse, plus a default internal location it can receive into."""
        code = code.strip().upper()
        if not code:
            raise ValueError("warehouse code must not be empty")
        if code in self._warehouses:
            raise DuplicateEntity(f"A warehouse with code {code!r} already exists")
        warehouse = Warehouse(code=code, name=name, address=address)
        self._warehouses[code] = warehouse
        self.add_location(code, "STOCK", name="Stock area")
        return warehouse

    def add_location(
        self,
        warehouse_code: str,
        code: str,
        *,
        kind: LocationKind = LocationKind.INTERNAL,
        name: str = "",
    ) -> Location:
        warehouse_code = self._require_warehouse(warehouse_code).code
        code = code.strip().upper()
        full_code = f"{warehouse_code}/{code}"
        if full_code in self._locations:
            raise DuplicateEntity(f"A location with code {full_code!r} already exists")
        location = Location(
            code=full_code,
            warehouse_code=warehouse_code,
            kind=kind,
            name=name or code.replace("-", " ").title(),
        )
        self._locations[full_code] = location
        if kind is LocationKind.INTERNAL and warehouse_code not in self._default_location:
            self._default_location[warehouse_code] = full_code
        return location

    def get_warehouse(self, code: str) -> Warehouse:
        return self._require_warehouse(code)

    def warehouses(self) -> list[Warehouse]:
        return sorted(self._warehouses.values(), key=lambda w: w.code)

    def locations(
        self, *, warehouse: str | None = None, kind: LocationKind | None = None
    ) -> list[Location]:
        found = [
            loc
            for loc in self._locations.values()
            if (warehouse is None or loc.warehouse_code == warehouse.upper())
            and (kind is None or loc.kind is kind)
        ]
        return sorted(found, key=lambda loc: loc.code)

    def _require_warehouse(self, code: str) -> Warehouse:
        try:
            return self._warehouses[code.strip().upper()]
        except KeyError:
            raise UnknownEntity(f"No warehouse with code {code!r}") from None

    def _default_internal(self, warehouse_code: str) -> str:
        try:
            return self._default_location[warehouse_code]
        except KeyError:
            raise UnknownEntity(
                f"Warehouse {warehouse_code!r} has no internal location"
            ) from None

    def _target_internal(self, warehouse_code: str, location: str | None) -> str:
        """Resolve a warehouse (and optional bin) to a validated internal location code."""
        warehouse_code = self._require_warehouse(warehouse_code).code
        if location is None:
            return self._default_internal(warehouse_code)
        location = location.strip().upper()
        if "/" not in location:
            location = f"{warehouse_code}/{location}"
        found = self._locations.get(location)
        if found is None:
            raise UnknownEntity(f"No location with code {location!r}")
        if found.kind is not LocationKind.INTERNAL:
            raise StockError(
                f"{location!r} is a {found.kind.value} location and cannot hold stock"
            )
        if found.warehouse_code != warehouse_code:
            raise StockError(
                f"{location!r} does not belong to warehouse {warehouse_code!r}"
            )
        return location

    # -- ledger -------------------------------------------------------------

    def _record(
        self,
        *,
        sku: str,
        src: str,
        dst: str,
        qty: float,
        kind: MoveKind,
        reference: str,
        created_by: str | None,
    ) -> StockMove:
        """Append a move to the ledger. The single write path in the engine."""
        if sku not in self._products:
            raise UnknownEntity(f"No product with sku {sku!r}")
        if src not in self._locations:
            raise UnknownEntity(f"No location with code {src!r}")
        if dst not in self._locations:
            raise UnknownEntity(f"No location with code {dst!r}")
        if src == dst:
            raise StockError("A move cannot have the same source and destination")
        if not qty > 0:
            raise InvalidQuantity(f"qty must be greater than zero, got {qty!r}")
        if not reference or not reference.strip():
            raise StockError("Every move requires a non-empty reference")

        move = StockMove(
            id=next(self._ids),
            sku=sku,
            src=src,
            dst=dst,
            qty=float(qty),
            kind=kind,
            reference=reference.strip(),
            created_at=datetime.now(timezone.utc),
            created_by=created_by or self.operator,
        )
        self._moves.append(move)
        return move

    def receive(
        self,
        sku: str,
        warehouse_code: str,
        qty: float,
        reference: str,
        *,
        location: str | None = None,
        created_by: str | None = None,
    ) -> StockMove:
        """Goods arrive from a supplier."""
        sku = self.get_product(sku).sku
        dst = self._target_internal(warehouse_code, location)
        return self._record(
            sku=sku,
            src=SUPPLIER_LOCATION,
            dst=dst,
            qty=qty,
            kind=MoveKind.RECEIPT,
            reference=reference,
            created_by=created_by,
        )

    def deliver(
        self,
        sku: str,
        warehouse_code: str,
        qty: float,
        reference: str,
        *,
        location: str | None = None,
        created_by: str | None = None,
    ) -> StockMove:
        """Goods ship to a customer. Refuses to drive the source location negative."""
        sku = self.get_product(sku).sku
        src = self._target_internal(warehouse_code, location)
        available = self._level_at(sku, src)
        if qty > available:
            raise InsufficientStock(
                f"Cannot deliver {qty:g} of {sku} from {src}; "
                f"only {available:g} on hand there"
            )
        return self._record(
            sku=sku,
            src=src,
            dst=CUSTOMER_LOCATION,
            qty=qty,
            kind=MoveKind.DELIVERY,
            reference=reference,
            created_by=created_by,
        )

    def transfer(
        self,
        sku: str,
        from_warehouse: str,
        to_warehouse: str,
        qty: float,
        reference: str,
        *,
        created_by: str | None = None,
    ) -> StockMove:
        """Relocate stock between warehouses. Total quantity is unchanged."""
        sku = self.get_product(sku).sku
        src = self._target_internal(from_warehouse, None)
        dst = self._target_internal(to_warehouse, None)
        if src == dst:
            raise StockError("A transfer needs two different warehouses")
        available = self._level_at(sku, src)
        if qty > available:
            raise InsufficientStock(
                f"Cannot transfer {qty:g} of {sku} from {src}; "
                f"only {available:g} on hand there"
            )
        return self._record(
            sku=sku,
            src=src,
            dst=dst,
            qty=qty,
            kind=MoveKind.TRANSFER,
            reference=reference,
            created_by=created_by,
        )

    def adjust(
        self,
        sku: str,
        warehouse_code: str,
        target_qty: float,
        reference: str,
        *,
        location: str | None = None,
        created_by: str | None = None,
    ) -> StockMove | None:
        """Record a count correction.

        The count itself is not stored -- the *delta* is. A miscount therefore
        becomes a visible ledger entry rather than a silent edit, which is what
        makes a wrong number traceable to the moment someone fixed it.

        Returns ``None`` when the count already matches the ledger.
        """
        sku = self.get_product(sku).sku
        loc = self._target_internal(warehouse_code, location)
        if target_qty < 0:
            raise InvalidQuantity("A counted quantity cannot be negative")

        delta = target_qty - self._level_at(sku, loc)
        if delta == 0:
            return None
        if delta > 0:
            src, dst, qty = ADJUSTMENT_LOCATION, loc, delta
        else:
            src, dst, qty = loc, ADJUSTMENT_LOCATION, -delta
        return self._record(
            sku=sku,
            src=src,
            dst=dst,
            qty=qty,
            kind=MoveKind.ADJUSTMENT,
            reference=reference,
            created_by=created_by,
        )

    def moves(
        self,
        *,
        sku: str | None = None,
        warehouse: str | None = None,
        kind: MoveKind | None = None,
        newest_first: bool = True,
        limit: int | None = None,
    ) -> list[StockMove]:
        """Query the ledger."""
        warehouse = warehouse.upper() if warehouse else None
        found = []
        for move in self._moves:
            if sku is not None and move.sku != sku.upper():
                continue
            if kind is not None and move.kind is not kind:
                continue
            if warehouse is not None and not self._touches_warehouse(move, warehouse):
                continue
            found.append(move)
        if newest_first:
            found.reverse()
        return found[:limit] if limit is not None else found

    def _touches_warehouse(self, move: StockMove, warehouse: str) -> bool:
        for code in (move.src, move.dst):
            location = self._locations.get(code)
            if location is not None and location.warehouse_code == warehouse:
                return True
        return False

    # -- levels (derived) ---------------------------------------------------

    def _level_at(self, sku: str, location_code: str) -> float:
        """On-hand at one location, folded from the ledger."""
        total = 0.0
        for move in self._moves:
            if move.sku != sku:
                continue
            if move.dst == location_code:
                total += move.qty
            if move.src == location_code:
                total -= move.qty
        return total

    def levels(
        self,
        *,
        sku: str | None = None,
        warehouse: str | None = None,
        internal_only: bool = True,
    ) -> dict[tuple[str, str], float]:
        """Every ``(sku, location)`` level, folded from the ledger."""
        warehouse = warehouse.upper() if warehouse else None
        sku = sku.upper() if sku else None
        totals: dict[tuple[str, str], float] = {}
        for move in self._moves:
            if sku is not None and move.sku != sku:
                continue
            for code, sign in ((move.dst, 1.0), (move.src, -1.0)):
                location = self._locations[code]
                if internal_only and location.kind is not LocationKind.INTERNAL:
                    continue
                if warehouse is not None and location.warehouse_code != warehouse:
                    continue
                key = (move.sku, code)
                totals[key] = totals.get(key, 0.0) + sign * move.qty
        return {key: qty for key, qty in totals.items() if qty != 0.0}

    def on_hand(self, sku: str, warehouse: str | None = None) -> float:
        """Total internal stock for a product, optionally scoped to one warehouse."""
        return sum(self.levels(sku=sku, warehouse=warehouse).values())

    def on_hand_by_warehouse(self, sku: str) -> dict[str, float]:
        totals: dict[str, float] = {}
        for (_, location_code), qty in self.levels(sku=sku).items():
            warehouse_code = self._locations[location_code].warehouse_code
            totals[warehouse_code] = totals.get(warehouse_code, 0.0) + qty
        return totals

    def stock_levels(
        self, *, sku: str | None = None, warehouse: str | None = None
    ) -> list[dict]:
        """Reporting view: one row per ``(sku, location)`` with a non-zero level."""
        rows = []
        for (product_sku, location_code), qty in self.levels(
            sku=sku, warehouse=warehouse
        ).items():
            location = self._locations[location_code]
            rows.append(
                {
                    "sku": product_sku,
                    "location": location_code,
                    "warehouse": location.warehouse_code,
                    "qty": qty,
                }
            )
        return sorted(rows, key=lambda row: (row["sku"], row["location"]))

    # -- reorder ------------------------------------------------------------

    def set_reorder_rule(
        self, sku: str, warehouse_code: str, min_qty: float, max_qty: float
    ) -> ReorderRule:
        sku = self.get_product(sku).sku
        warehouse_code = self._require_warehouse(warehouse_code).code
        if min_qty < 0 or max_qty < 0:
            raise ValueError("Reorder thresholds must not be negative")
        if max_qty < min_qty:
            raise ValueError("max_qty must be greater than or equal to min_qty")
        rule = ReorderRule(
            sku=sku,
            warehouse_code=warehouse_code,
            min_qty=float(min_qty),
            max_qty=float(max_qty),
        )
        self._rules[(sku, warehouse_code)] = rule
        return rule

    def reorder_rules(self, *, warehouse: str | None = None) -> list[ReorderRule]:
        warehouse = warehouse.upper() if warehouse else None
        rules = [
            rule
            for rule in self._rules.values()
            if warehouse is None or rule.warehouse_code == warehouse
        ]
        return sorted(rules, key=lambda r: (r.warehouse_code, r.sku))

    def low_stock(self, *, warehouse: str | None = None) -> list[dict]:
        """Products below their reorder point, most urgent (largest shortfall) first."""
        warehouse = warehouse.upper() if warehouse else None
        items = []
        for rule in self.reorder_rules(warehouse=warehouse):
            on_hand = self.on_hand(rule.sku, rule.warehouse_code)
            if on_hand < rule.min_qty:
                items.append(
                    {
                        "sku": rule.sku,
                        "name": self._products[rule.sku].name,
                        "warehouse": rule.warehouse_code,
                        "on_hand": on_hand,
                        "min_qty": rule.min_qty,
                        "max_qty": rule.max_qty,
                        "shortfall": on_hand - rule.min_qty,
                        "suggested_order_qty": max(rule.max_qty - on_hand, 0.0),
                    }
                )
        return sorted(items, key=lambda item: item["shortfall"])

    # -- valuation ----------------------------------------------------------

    def valuation(self, *, warehouse: str | None = None) -> float:
        """Inventory value at cost."""
        return sum(
            qty * self._products[product_sku].unit_cost
            for (product_sku, _), qty in self.levels(warehouse=warehouse).items()
        )

    def valuation_by_warehouse(self) -> dict[str, float]:
        return {
            warehouse.code: self.valuation(warehouse=warehouse.code)
            for warehouse in self.warehouses()
        }

    # -- diagnostics --------------------------------------------------------

    def ledger(self) -> list[StockMove]:
        """The full ledger, oldest first. Immutable history."""
        return list(self._moves)

    def __repr__(self) -> str:
        return (
            f"<StockEngine products={len(self._products)} "
            f"warehouses={len(self._warehouses)} moves={len(self._moves)}>"
        )
