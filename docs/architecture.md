# Architecture

**Stack decision: made — Flask + SQLite + server-rendered Jinja2.**
See [the decision](#decision) below for why, and what was rejected. The rest of
this document records the reasoning and the options that were considered, so the
choice does not get re-litigated in the final hour.

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

## Decision

**Flask + SQLite + Jinja2, server-rendered, one hand-written stylesheet.**

The deciding factor was time-to-complete under a hard deadline, and it was not a
close call once framed that way:

- **No build step.** No bundler, no `node_modules`, no transpile. `pip install -r
  requirements.txt` and `python run.py` is the entire setup. A stack that fails
  to install on the demo machine is a stack that fails.
- **The domain layer ports cleanly.** `app/engine.py` is close to a direct
  translation of `reference/stock_engine.py`, which already had passing tests.
  Choosing a stack that made that translation hard would have thrown away the
  most valuable work in the repository.
- **One language.** Templates, views and domain logic are all Python. On a short
  deadline, context-switching between two languages costs more than it buys.
- **Server-rendered HTML is enough.** This is a forms-and-tables application.
  A client-side framework would add a build step and a state-sync problem in
  exchange for interactivity the spec does not ask for.

**Rejected, and why:**

| Option | Why not |
| --- | --- |
| Odoo 17/18 module | Highest ceiling, but the learning risk on the clock was unacceptable. We would have spent the budget learning Odoo's ORM and view system instead of building the product. |
| React + FastAPI | Would have meant two runtimes, a build step, and a UI built from nothing. More moving parts to break at demo time for no gain in what is being judged. |
| Next.js + Prisma | Fastest route to a polished UI, but it interleaves the domain with route handlers unless we were disciplined, which weakens the invariant tests that are the repository's main asset. |

**Consequences accepted:**

- The UI is less interactive than a React build could be. Pagination and filtering
  are full page loads.
- SQLite will not survive concurrent writers at production scale. Postgres is a
  `DATABASE` environment variable and a driver swap away, because all SQL lives
  behind `app/db.py`.
- The REST contract in `spec/openapi.yaml` is not currently served. It remains
  the documented interface and the target if the frontend is ever split out.

## Recommendation (superseded)

Kept for the record. This was the pre-decision analysis.

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
