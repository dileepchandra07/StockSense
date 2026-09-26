# Design rationale

Why StockSense is built the way it is, and the questions that reasoning invites.

This is written for anyone reading the repository cold — a teammate, a reviewer, or
someone evaluating the work. It is not a summary of what the code does; that is the
code's job. It is the *reasoning* behind the decisions, and an honest account of
where the design is weak.

---

## The one idea everything hangs off

> **The movement ledger is the only source of truth. Stock levels are derived.**

`stock_moves` is append-only. There is no stored on-hand quantity anywhere in the
database. Levels are a SQL view that folds the ledger:

```sql
-- app/schema.sql
CREATE VIEW v_stock_levels AS
SELECT product_id, location_id, SUM(qty) AS qty
FROM (
    SELECT product_id, dst_location_id AS location_id,  qty FROM stock_moves
    UNION ALL
    SELECT product_id, src_location_id AS location_id, -qty FROM stock_moves
)
GROUP BY product_id, location_id;
```

Every other decision in the system is downstream of this one.

---

## Why not store the quantity on the product?

Because a stored number can drift from the history that produced it, and then you
have two truths and no way to tell which is right.

Deriving makes drift impossible: there is exactly one number, and it is computed
from the moves. It also means every figure is explainable — "why is it 377?" is
answered by opening the move history and counting the rows — and audit becomes a
by-product rather than a feature someone has to remember to build.

**What it costs.** Reading a level is O(moves) instead of O(1). That is a fine
trade at this scale. The path to fixing it without giving up the property is in
[`domain-model.md`](domain-model.md#materialisation): a cache table that must be
rebuildable from the ledger and periodically asserted equal to it. The ledger stays
authoritative; the table is an index over it.

## Why is a draft document not changing stock?

Because a document is a **plan** and a move is a **fact**, and conflating them is
what makes inventory systems unusable by actual people.

A warehouse clerk needs to prepare tomorrow's receipt without corrupting today's
inventory. Keeping the two apart means stock changes at exactly one moment —
validation — and it makes "pending receipts" a meaningful dashboard number rather
than a count of rows nobody has acted on.

```
draft ──→ waiting ──→ ready ──→ done          stock has moved, permanently
  │          │          │
  └──────────┴──────────┴──→ canceled          stock never will
```

`done` is terminal. To undo a validated document you record the reverse, which
leaves both the mistake and the correction visible. That is deliberate.

## Where is the transaction boundary?

In `validate_document`, the moves and the status change commit together:

```python
with db:  # single transaction: moves and status change together, or neither
    for product_id, src, dst, qty in planned:
        db.execute("INSERT INTO stock_moves ...")
    db.execute("UPDATE documents SET status = 'done' ...")
```

There is no window in which a document reports `done` while its ledger entries are
missing.

## How is negative stock prevented?

The availability guard aggregates planned draws **per `(product, source location)`
pair** before comparing against the derived level:

```python
draws = {}
for product_id, src, _dst, qty in planned:
    if doc_type in ("delivery", "internal"):
        draws[(product_id, src)] = draws.get((product_id, src), 0.0) + qty
```

The aggregation is the point. Two lines drawing 40 and 60 from a location holding 80
must be rejected **together**; checking each line independently against 80 would let
both through.

Adjustments are the deliberate exception — they may reduce stock to zero, because
that is what correcting a miscount means. They still cannot go negative: a negative
physical count is a data-entry error, not a fact.

## Why does an adjustment store the delta and not the count?

Because a miscount should be **visible**, not erased.

The operator enters the counted quantity; the system computes `counted - recorded`
and records the difference as a move with a reference and a reason. If the count
already matches, nothing is recorded at all.

The alternative — overwriting the number — would make the correction invisible, and
a wrong figure would have no traceable cause. Recording the delta means the ledger
can always answer "who changed this, when, and why".

---

## Questions this design invites

Answering these honestly is more useful than defending them.

### Two operators validate deliveries at the same time. What happens?

There is a genuine race window. The availability check is read-then-write, so both
requests could read the same level, both pass the guard, and both insert. SQLite
serialises writers so nothing corrupts, but the second delivery could overdraw.

The fixes, in order of preference:

1. **Row lock** on the `(product, location)` pair inside the transaction
   (`SELECT ... FOR UPDATE` on Postgres). Correct and simple.
2. **Optimistic** — re-derive the level inside the transaction, abort on conflict.
3. **Reconcile later** — accept the move and flag overdraws in a job.

We took none of these. That is a real gap, documented in
[`domain-model.md`](domain-model.md#concurrency), and it is the first thing to fix
with more time.

### Why Flask and SQLite for an Odoo hackathon?

Time-to-complete, and the domain layer.

The inventory rules already existed and were tested in
[`reference/stock_engine.py`](../reference/) — a dependency-free implementation with
53 passing tests. Flask let that logic port across nearly unchanged instead of being
rewritten against an unfamiliar ORM. There is no build step, one language, and two
commands to run it.

**What it costs us.** The UI is less interactive than a React build — filtering and
pagination are full page loads. SQLite will not take concurrent writers at
production scale. Both are recorded in [`architecture.md`](architecture.md). All SQL
sits behind `app/db.py`, so moving to Postgres is a connection string and a driver.

Odoo's own `stock` module is the right long-term answer inside an Odoo shop, and our
ledger maps onto `stock.move` conceptually. We chose not to learn Odoo's framework
on the clock, which is a schedule decision rather than a technical one.

### How do you know the numbers are right?

186 tests across two suites, and the split is deliberate:

- **53 reference tests** pin the domain semantics with no framework involved. If
  these fail, the *rules* are wrong.
- **133 application tests** drive the real Flask app against a throwaway database —
  every route, every workflow, every status transition — and re-check the domain
  invariants against real SQL. If these fail, the *wiring* is wrong.

Knowing which of the two broke tells you where to look.

One test is worth naming: `test_levels_match_an_independent_fold_of_the_ledger`
recomputes levels with a second, independently written SQL query and asserts it
equals what the application reports. Two independent folds of the same ledger must
agree — if they ever diverge, the derivation is wrong.

### How is the ledger actually immutable?

There is no `UPDATE` or `DELETE` against `stock_moves` anywhere in the codebase. The
only `INSERT` is inside `validate_document`.

In the reference implementation it is enforced by the type system: `StockMove` is a
frozen dataclass and `ledger()` returns a copy, so mutating the returned list does
not affect the engine.

---

## What is not built

Stated plainly, because owning the gaps reads as confidence and being caught by them
does not.

| Gap | Detail |
| --- | --- |
| **OTP delivery** | The reset code is displayed on screen, clearly labelled. No mail service is wired up. Swapping in a real send touches one function, `_deliver_otp`. |
| **Roles** | Recorded and displayed, but not enforced. Every signed-in user can do everything. |
| **CSRF** | No tokens. Flask-WTF is the fix. Fine for a demo, not for production. |
| **Level performance** | Folded on every read. O(moves). |
| **Reservations** | Soft-allocating stock to a pending order before it ships. |
| **Lot / serial tracking** | Moves do not carry a lot identifier. |
| **Multi-UoM conversion** | Buying in boxes and selling in units is not supported. |
| **Costing methods** | Flat `unit_cost`, not FIFO/LIFO/weighted-average. |

The last four are enumerated in
[`domain-model.md`](domain-model.md#deliberate-omissions) with notes on what each
would take to add.

## Where to look

| Question about | Open |
| --- | --- |
| How levels are derived | `app/schema.sql` — `v_stock_levels` |
| Validation, the guard, adjustments | `app/engine.py` — `validate_document` |
| Low stock, valuation, KPIs | `app/engine.py` — `low_stock`, `inventory_value`, `dashboard_kpis` |
| Status workflow | `app/engine.py` — `set_status`; `domain-model.md` |
| The framework-free domain | `reference/stock_engine.py` |
| Proof it works | `tests/test_app.py`, `reference/test_stock_engine.py` |
