# Architecture

**Stack decision: open.** This document lays out the options and the reasoning,
so the team can ratify a choice rather than re-litigate it. Everything else in
the repository — the domain model, the API contract, the reference
implementation — is deliberately independent of the answer.

---

## Design principles

1. **The domain is the product.** Inventory semantics are the hard part. Frameworks
   are the easy part. Keep the two separated and the framework becomes swappable.
2. **One source of truth.** The movement ledger. See [`domain-model.md`](domain-model.md).
3. **Modules own their data.** No module reaches into another's tables. They talk
   through defined interfaces.
4. **The contract is the integration point.** [`spec/openapi.yaml`](../spec/openapi.yaml)
   is what the frontend and backend agree on. Implement against it; change it
   deliberately, in a PR, with both sides aware.

## Layers

```
┌──────────────────────────────────────────────────────────┐
│  Dashboard / Operator UI                                 │
│  stock levels · move history · low-stock alerts · entry  │
└───────────────────────────┬──────────────────────────────┘
                            │  HTTP, per spec/openapi.yaml
┌───────────────────────────▼──────────────────────────────┐
│  API layer                                               │
│  routing · validation · serialisation · auth             │
└───────────────────────────┬──────────────────────────────┘
                            │  module interfaces
┌───────────────────────────▼──────────────────────────────┐
│  Domain modules                                          │
│  catalog · network · ledger · levels · reorder · valuation│
│  ← the part that must be correct, and is stack-independent│
└───────────────────────────┬──────────────────────────────┘
                            │  repository interfaces
┌───────────────────────────▼──────────────────────────────┐
│  Persistence                                             │
│  append-only moves table + master data tables            │
└──────────────────────────────────────────────────────────┘
```

The domain layer is where the value is. It has no knowledge of HTTP, of the
database, or of any web framework. `reference/stock_engine.py` is this layer,
written in the smallest possible form — read it to see exactly what the domain
does, independent of everything else.

## Module boundaries

| Module | Owns | Exposes |
| --- | --- | --- |
| `catalog` | Products, categories, UoM | `get_product(sku)`, `list_products()` |
| `network` | Warehouses, locations | `get_warehouse(code)`, `locations(warehouse)` |
| `ledger` | The move table | `record_move(...)`, `moves(filter)` |
| `levels` | Derivation from the ledger | `on_hand(sku, warehouse)`, `levels(filter)` |
| `reorder` | Rules and alerts | `low_stock()`, `set_rule(...)` |
| `valuation` | Costing | `valuation(warehouse)` |
| `dashboard` | Presentation | Consumes the API, owns no data |

**Dependency rule:** `ledger` depends on `catalog` and `network`. `levels`,
`reorder` and `valuation` depend on `ledger`. Nothing depends on `dashboard`.
There are no cycles. If you find yourself needing one, a boundary is wrong.

## Stack options

### Option A — Odoo 17/18 module (Python)

Build StockSense as a custom Odoo addon.

**For:** Odoo already ships `stock`, `product` and `stock.move` models with
warehouses, locations and multi-step routes. Much of the network and ledger
module exists and is battle-tested. Directly aligned with the hackathon's framing,
which judges may reward.

**Against:** You inherit Odoo's conventions, ORM and XML view system, and the
hackathon clock is short. A wrong turn in Odoo's framework costs hours. Your
domain model becomes a thin layer over `stock.move` rather than something you own.

**Choose this if:** the team has Odoo experience and the judging criteria
explicitly reward Odoo-native solutions.

### Option B — React + FastAPI + Postgres

**For:** Clean separation that mirrors the layering above almost exactly. FastAPI
maps directly onto the module structure, and the domain layer ports from
`reference/stock_engine.py` with little friction. Postgres gives real
transactions, which matters for the concurrency discussion in the domain model.
Strong fit if the team is comfortable in Python and JavaScript.

**Against:** Two runtimes to run and deploy. You build the UI from nothing — no
free admin panel, no pre-built forms.

**Choose this if:** you want a clean demo and control over every pixel, and the
team splits naturally into frontend and backend.

### Option C — Next.js + Postgres (Prisma)

**For:** One language, one codebase, one deploy. API routes collapse the API layer
into the app. Prisma makes the schema and migrations fast to iterate. Fastest path
to a genuinely polished UI, which is often what separates hackathon finalists.

**Against:** The domain layer ends up interleaved with route handlers unless
disciplined about it, which makes it harder to test the invariants in isolation.

**Choose this if:** UI polish and demo speed matter most and the team is
TypeScript-strong.

### Option D — Django + DRF

**For:** Batteries included — ORM, migrations, admin, auth, serialisation. The
admin panel is a working back office on day one. Python throughout.

**Against:** The admin is convenient but generic, and judges have seen it. Less
control over the final interface than B or C.

**Choose this if:** the team wants maximum functionality per hour and is
Python-strong.

### Comparison

| | A: Odoo | B: React+FastAPI | C: Next.js | D: Django |
| --- | --- | --- | --- | --- |
| Time to first working screen | Fast *if* Odoo-fluent | Medium | Fast | Fast |
| Time to polished demo UI | Slow | Medium | Fast | Medium |
| Domain layer testable in isolation | Partial | Excellent | Good | Good |
| Free admin/back office | Excellent | None | None | Excellent |
| Real transactions | Yes | Yes | Yes | Yes |
| Learning risk | High | Low | Low | Low |
| Aligns with hackathon framing | Best | Neutral | Neutral | Neutral |

## Recommendation

**Option B or C**, decided by one question: *is the team stronger in Python or
TypeScript?* Both give a clean domain layer and a real database. Pick the language
the team writes fastest in and stop deliberating — the domain model is identical
either way, and the API contract means the frontend can be built against a mock
from hour one regardless.

Option A is the right answer only if the judging criteria explicitly reward Odoo
and the team is already fluent. Do not learn Odoo on the clock.

This is a proposal. Ratify it in a `docs/` PR so the decision and its reasoning
are on the record.

## Persistence

Whatever the stack, the schema is the same shape:

- **Master data** — `product`, `warehouse`, `location`, `reorder_rule`. Mutable, small.
- **Ledger** — `stock_move`. **Append-only.** Indexed on `(sku, created_at)` and
  `(src)`, `(dst)` for level derivation.

Levels are derived. If you add a cache table, it must be rebuildable from
`stock_move` and periodically asserted equal to it. See the materialisation
section of [`domain-model.md`](domain-model.md).

## Concurrency

The append-only ledger removes the classic lost-update problem: there is no
counter to read-modify-write. The remaining race is the availability check before
a `delivery` or `transfer`.

Pick one and write it down:

- **Row lock** — `SELECT ... FOR UPDATE` on the `(sku, location)` pair inside the
  transaction. Correct and simple. Recommended.
- **Optimistic** — re-derive the level inside the transaction and abort on
  conflict.
- **Reconcile later** — accept the move, flag overdraws in a job. Cheapest, least
  safe, acceptable for a demo.

## Deployment for the demo

- **Option B** — FastAPI container + React static build + managed Postgres.
- **Option C** — single Node container + managed Postgres.
- **Option A** — Odoo container with the addon mounted, Postgres alongside.

Whichever you choose, seed the database with realistic data (multiple warehouses,
a few hundred products, a month of movement history) and write the demo script
*before* the final day. A demo that needs live data entry will not survive the
stage. See the demo script in [`roadmap.md`](roadmap.md).

## Explicitly not building

- Authentication beyond a demo login. It is not what is being judged.
- Reservations, lot tracking, multi-UoM, FIFO costing — see the omissions list in
  [`domain-model.md`](domain-model.md).
- Mobile apps. Responsive web is enough.
- A generic reporting engine. Four good reports beat a query builder.
