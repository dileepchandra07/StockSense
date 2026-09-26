# Domain model

This document is the contract. If the implementation and this document disagree,
one of them is a bug — decide which, then fix it.

---

## The core principle

> **The movement ledger is the only source of truth. Stock levels are derived.**

Every quantity in StockSense is the result of folding the ledger of moves. There
is no code path anywhere that sets an on-hand number directly. If you want to
change how much of something you have, you record a move.

This is not a stylistic preference. It is the decision that makes the rest of the
system work:

| Consequence | Why it matters |
| --- | --- |
| Levels cannot drift from history | There is only one number, and it is computed from the moves |
| Every figure is explainable | "Why is it 65?" — fold the ledger, see the four moves |
| Audit is free | The ledger *is* the audit trail |
| Corrections are honest | A miscount becomes a visible adjustment move, not a silent edit |
| Concurrency is tractable | Append-only writes, no read-modify-write on a counter |

The cost is that naive folding is O(moves). That is fine at hackathon scale and
fine for years of real use with the materialisation strategy described at the end.

## Entities

### Product

| Field | Type | Notes |
| --- | --- | --- |
| `sku` | string | Natural key. Immutable once created. |
| `name` | string | Display name |
| `category` | string | Free-form grouping for reporting |
| `uom` | string | Unit of measure — `unit`, `kg`, `litre`, `box` |
| `unit_cost` | decimal | Cost basis used for valuation |
| `is_active` | bool | Soft delete. Inactive products keep their history. |

### Warehouse

| Field | Type | Notes |
| --- | --- | --- |
| `code` | string | Natural key, uppercase — `MAIN`, `NORTH` |
| `name` | string | Display name |
| `address` | string | Optional |

### Location

Locations are where stock physically or logically sits. Every location has a
`kind`, and the kind determines what moves are legal.

| Field | Type | Notes |
| --- | --- | --- |
| `code` | string | Unique, namespaced by warehouse — `MAIN/STOCK`, `MAIN/A1` |
| `warehouse_code` | string \| null | `null` for virtual locations |
| `kind` | enum | See below |
| `name` | string | Display name |

**Location kinds:**

| Kind | Warehouse-bound | Meaning |
| --- | --- | --- |
| `internal` | yes | Real, countable stock. A warehouse floor, a shelf, a bin. |
| `supplier` | no | Virtual. The outside world we receive from. |
| `customer` | no | Virtual. The outside world we ship to. |
| `adjustment` | no | Virtual. Where miscounts go to be recorded honestly. |

Stock at `internal` locations is the only stock that counts toward on-hand. The
virtual locations are a bookkeeping device: they let every movement — including
goods entering or leaving the business entirely — be expressed as a transfer
between two locations, using one uniform operation.

### StockMove

The ledger entry. **Append-only — never updated, never deleted.**

| Field | Type | Notes |
| --- | --- | --- |
| `id` | integer | Monotonic |
| `sku` | string | Product moved |
| `src` | string | Source location code |
| `dst` | string | Destination location code |
| `qty` | decimal | **Always positive.** Direction is encoded in `src`/`dst`. |
| `kind` | enum | `receipt`, `delivery`, `transfer`, `adjustment` |
| `reference` | string | Human traceable — PO number, order id, incident ticket |
| `created_at` | timestamp | UTC |
| `created_by` | string | Operator |

> **Quantity is always positive.** A move from `A` to `B` of 30 is one row with
> `src=A, dst=B, qty=30`. It is never `qty=-30`. Signed quantities invite
> double-negation bugs; explicit endpoints do not.

### StockLevel — derived, not stored

A `StockLevel` is the pair `(sku, location_code) -> qty`. It is computed, never
written. See [Derived quantities](#derived-quantities).

### ReorderRule

| Field | Type | Notes |
| --- | --- | --- |
| `sku` | string | |
| `warehouse_code` | string | Rules are per warehouse — each has its own lead times |
| `min_qty` | decimal | Trigger threshold |
| `max_qty` | decimal | Replenishment target |

## Relationships

```
        Product ──────────────┐
           │                  │
           │ sku              │ sku
           ▼                  ▼
      StockMove ────────► ReorderRule
        │      │              │
    src │      │ dst          │ warehouse_code
        ▼      ▼              ▼
     Location ◄──────── Warehouse
        │
        └── kind: internal | supplier | customer | adjustment
```

## Move kinds

Every kind is a `StockMove` between two locations. The kind is metadata for
reporting and validation — the arithmetic is identical for all four.

| Kind | `src` | `dst` | Business meaning |
| --- | --- | --- | --- |
| `receipt` | `supplier` | `internal` | Goods arrive from a vendor |
| `delivery` | `internal` | `customer` | Goods ship to a customer |
| `transfer` | `internal` | `internal` | Stock relocates between warehouses or bins |
| `adjustment` | either | either | A miscount is corrected, with a reason |

Adjustments are the interesting one. To set a shelf to a counted value, you
compute the delta between the ledger and the count and record *that delta* as an
adjustment move. The count itself is not stored — the correction is. This is why
a wrong number can always be traced back to the moment someone fixed it and why.

## Invariants

These are the properties the system must never violate. Each has a corresponding
test in `reference/test_stock_engine.py`.

### 1. Levels are derived from the ledger

For any `(sku, location)`:

```
level(sku, location) == Σ (dst == location ? +qty : 0)
                      + Σ (src == location ? -qty : 0)
```

There is no other source of on-hand quantity. A cache may exist for performance,
but it must be rebuildable from the ledger with an identical result.

### 2. Transfers conserve quantity

```
total_on_hand(before) == total_on_hand(after)   # for any transfer
```

An internal-to-internal move relocates stock. It cannot create or destroy it. If
this test fails, the arithmetic is wrong — this is the single most common
inventory bug.

### 3. Internal stock never goes negative

A `delivery` or `transfer` may not draw more from an internal location than is
present there. The guard is checked against the *current* derived level.

> Deliberate exception: an `adjustment` may take a location to zero or reduce it
> below its ledger value, because that is precisely what a correction is. It may
> not go negative — a negative physical count is a data-entry error, not a fact.

### 4. Every move is traceable

`reference` is mandatory and non-empty on every move. When a count is disputed,
the ledger has to answer "who did this, when, and against what document". A move
without a reference is an unanswerable question.

### 5. Quantity is strictly positive

`qty > 0` on every move. A zero-quantity move is noise; a negative one is a bug.

### 6. History is immutable

Moves are appended, never edited or deleted. To undo a move, record the inverse
with a reference pointing at the original. The correction is then visible in the
history, which is the entire point.

## Derived quantities

| Quantity | Definition |
| --- | --- |
| `on_hand(sku, warehouse)` | Σ level over `internal` locations in that warehouse |
| `on_hand(sku)` | Σ level over all `internal` locations |
| `low_stock()` | Every `(sku, warehouse)` with a rule where `on_hand < min_qty` |
| `suggested_order_qty` | `max_qty - on_hand`, floored at zero |
| `valuation(warehouse)` | Σ `on_hand(sku) × unit_cost(sku)` over that warehouse |

## Concurrency

Two operators receiving into the same bin simultaneously must not lose a write.
Because the ledger is append-only, this reduces to safe concurrent appends:

- **Database** — inserts only. No read-modify-write on a counter, so no lost
  updates. Isolation handles the rest.
- **In-memory reference** — single-threaded by construction. This is a deliberate
  simplification; it is a reference, not the product.

The check in invariant 3 is a read-then-write and therefore has a race window
under concurrency. Production implementations should either take a row lock on
the `(sku, location)` pair or accept the move and let a reconciliation job flag
overdraws. Note it, pick one, document the choice.

## Deliberate omissions

Out of scope for the MVP. Listed so nobody assumes they are handled:

- **Reservations** — soft-allocating stock to a pending order before it ships.
  Changes `available` from `on_hand` to `on_hand - reserved`.
- **Lot and serial tracking** — moves carry a lot/serial identifier.
- **Multi-UoM conversion** — buying in boxes, selling in units.
- **Costing methods** — FIFO/LIFO/weighted-average. We use a flat `unit_cost`.
- **Cycle counting workflows** — scheduled counts and variance reports.

## Materialisation

For the MVP, fold the ledger on every read. It is simple and provably correct.

When that becomes slow, add a `stock_level` table maintained inside the same
transaction as each move insert, with:

- a periodic job that rebuilds it from the ledger and asserts equality
- the rebuild as the authoritative fallback if the cache is ever suspect

The ledger stays the source of truth. The table is an index over it, and must
always be reproducible from it.
