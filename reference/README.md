# Reference implementation

A runnable statement of what StockSense's domain actually does.

```bash
python3 demo.py          # end-to-end walkthrough
python3 -m unittest -v   # 53 invariant tests
```

No dependencies. Python 3.11+ standard library only.

---

## What this is, and what it is not

**This is a specification you can execute.** [`docs/domain-model.md`](../docs/domain-model.md)
describes the rules in prose; this module is those same rules in code, with tests
that fail loudly if they are broken.

**This is not the product.** There is no HTTP layer, no database, no UI, and no
concurrency handling. State lives in memory and disappears when the process exits.
See [`docs/architecture.md`](../docs/architecture.md) for what the real stack
should look like.

The point is that the hard part of an inventory system — the semantics — is
settled and testable independently of any framework decision. When the team picks
a stack, this logic ports over and the tests come with it.

## Files

| File | Contents |
| --- | --- |
| `stock_engine.py` | The domain: entities, the ledger, derived levels, reorder, valuation |
| `test_stock_engine.py` | 53 tests, one per rule and invariant |
| `demo.py` | A seeded walkthrough that prints the derived state |

## Using it

```python
from stock_engine import StockEngine

engine = StockEngine(operator="harsha")
engine.add_warehouse("MAIN", "Main Distribution Centre")
engine.add_warehouse("NORTH", "North Regional Depot")
engine.add_product("WIDGET-A", "Steel widget, 12mm", unit_cost=24.50)

engine.receive("WIDGET-A", "MAIN", 120, "PO-2026-0114")
engine.transfer("WIDGET-A", "MAIN", "NORTH", 30, "TRF-2026-0031")
engine.deliver("WIDGET-A", "MAIN", 25, "SO-2026-0431")

engine.on_hand("WIDGET-A", "MAIN")     # 65.0
engine.on_hand("WIDGET-A", "NORTH")    # 30.0
engine.on_hand("WIDGET-A")             # 95.0 -- transfers conserve this
engine.valuation()                     # 2327.5
```

## The four operations

Every change to inventory is one of these. There is no fifth way.

| Operation | Signature | Effect |
| --- | --- | --- |
| Receive | `receive(sku, warehouse, qty, reference)` | Supplier → internal. Increases on-hand. |
| Deliver | `deliver(sku, warehouse, qty, reference)` | Internal → customer. Decreases on-hand. |
| Transfer | `transfer(sku, from_wh, to_wh, qty, reference)` | Internal → internal. Total unchanged. |
| Adjust | `adjust(sku, warehouse, target_qty, reference)` | Records the delta to reach a counted value. |

`deliver` and `transfer` raise `InsufficientStock` rather than driving a location
negative. `adjust` is the one operation permitted to reduce stock, because that is
exactly what correcting a miscount means.

## Reading the code

Three things are worth understanding before you change anything:

**`_record` is the only write path.** Every operation funnels through it, which is
where the invariants are enforced — positive quantity, non-empty reference,
existing endpoints, no self-moves. Add a new operation and it inherits all of them
for free.

**Levels are computed, never stored.** `_level_at` and `levels` fold the ledger on
every call. This is O(moves) and deliberately so: it is impossible for a stored
level to drift from history if no level is stored. `docs/domain-model.md`
describes how to add a cache later without giving that up.

**Moves are frozen dataclasses.** `StockMove` cannot be mutated after creation,
and `ledger()` returns a copy. History is append-only, and the type system enforces it.

## Extending it

If you need behaviour this module does not have, in rough order of likely need:

1. **Reservations** — `available = on_hand - reserved`. Needs a new entity and a
   change to the guard in `deliver`.
2. **Lot and serial tracking** — add a `lot` field to `StockMove` and to the level
   key. Straightforward, but it touches every fold.
3. **Costing methods** — replace the flat `unit_cost` with a per-move cost and
   derive valuation from the ledger. Do not add a stored average.

Add a test for the invariant first, then make it pass. The suite is the contract.

## Keeping this honest

If you change domain behaviour in the application, change it here too and run the
tests. A reference implementation that disagrees with the product is worse than no
reference implementation — it actively misleads. CI runs this suite on every push
for exactly that reason.
