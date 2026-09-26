# StockSense

**Real-time inventory tracking across warehouses.** StockSense replaces paper
registers and month-end spreadsheet reconciliation with an append-only movement
ledger, and stock levels that are always *derived* — never guessed.

Built for **Odoo Hackathon 2026**.

---

## Status

| Area | State |
| --- | --- |
| Repository foundation | done |
| Domain model | done — [`docs/domain-model.md`](docs/domain-model.md) |
| API contract | done — [`spec/openapi.yaml`](spec/openapi.yaml) |
| Reference implementation | runnable — [`reference/`](reference/) |
| Application stack | **not finalised** — options in [`docs/architecture.md`](docs/architecture.md) |

Nothing in this repository is throwaway. The domain model, the API contract and
the movement semantics are all stack-independent, so whichever framework the team
settles on, the reasoning in `docs/` still applies and the reference
implementation still runs.

---

## The problem

Small and mid-size distributors run their warehouses on paper registers and
Excel. The failure modes are predictable and expensive:

- **Counts drift.** Nothing reconciles what the register says against what is on the shelf.
- **Transfers vanish.** Stock moves between warehouses and nobody records it.
- **Reorder points are guesswork.** You find out you ran out when a customer asks.
- **No audit trail.** When the count is wrong, there is no way to find out why.
- **Month-end takes days.** Closing the books means manually tallying stacks of paper.

## The approach

One core idea carries the whole design:

> **Stock levels are derived. The movement ledger is the only source of truth.**

Every change to inventory — a receipt, a delivery, a transfer, a correction — is
an immutable entry in a single ledger. On-hand quantities are computed by folding
that ledger. This one decision buys three things at once: levels can never drift
out of sync with history, every number is traceable to the moves that produced
it, and audit is a by-product rather than a feature you have to build later.

## Modules

StockSense is deliberately modular. Each module owns one concern and can be built
and tested independently.

| Module | Responsibility |
| --- | --- |
| `catalog` | Products, SKUs, categories, units of measure |
| `network` | Warehouses and physical bin locations |
| `ledger` | Stock moves — receipts, deliveries, transfers, adjustments |
| `levels` | On-hand quantities derived from the ledger |
| `reorder` | Min/max rules and low-stock alerts |
| `valuation` | Inventory value at cost, per warehouse |
| `dashboard` | Reporting API and operator UI |

See [`docs/architecture.md`](docs/architecture.md) for how these fit together and
[`docs/roadmap.md`](docs/roadmap.md) for who builds what, when.

## Quickstart

The reference implementation has **no dependencies** — Python 3.11+ standard
library only.

```bash
cd reference
python3 demo.py          # end-to-end walkthrough, prints the derived state
python3 -m unittest -v   # 53 tests covering the core invariants
```

Abridged output from `demo.py`:

```
StockSense reference walkthrough
==================================================================

Receipts
  PO-2026-0114      120 x WIDGET-A   supplier -> MAIN/STOCK
  PO-2026-0115       40 x WIDGET-A   supplier -> NORTH/STOCK
  ...

Transfers
  TRF-2026-0031      30 x WIDGET-A   MAIN/STOCK -> NORTH/STOCK

On hand
  WIDGET-A   MAIN          65
  WIDGET-A   NORTH         70
  BOLT-M8    MAIN           8
  ------------------------------
  total                   390   (across 5 lines)

Availability guard
  Attempting to deliver 500 x WIDGET-A from MAIN ...
  refused: Cannot deliver 500 of WIDGET-A from MAIN/STOCK; only 65 on hand there

Low stock
  BOLT-M8    MAIN    8 on hand, minimum 50 -> order 92

Valuation
  MAIN           3,743.50
  NORTH          5,465.00
  total          9,208.50

Ledger (newest 6 of 8 moves)
  #8   2026-09-26 09:12:27  adjustment     6 x GASKET-3   ADJ-2026-0007
  ...
  Every number above traces back to one of these rows.
```

## Repository layout

```
.
├── README.md
├── CONTRIBUTING.md          # branch strategy, commit conventions, PR flow
├── docs/
│   ├── architecture.md      # system design + stack options
│   ├── domain-model.md      # entities, relationships, invariants
│   └── roadmap.md           # phased plan and workstreams
├── spec/
│   └── openapi.yaml         # REST contract — implement against this
└── reference/
    ├── stock_engine.py      # working implementation of the domain logic
    ├── test_stock_engine.py # invariant tests
    └── demo.py              # runnable walkthrough
```

## Team

| GitHub | Role |
| --- | --- |
| [@dileepchandra07](https://github.com/dileepchandra07) | Repository owner |
| [@bit-odoo](https://github.com/bit-odoo) | Collaborator |
| [@Xranger-rootX](https://github.com/Xranger-rootX) | Collaborator |
| [@kottanamanikanta1-dot](https://github.com/kottanamanikanta1-dot) | Collaborator |

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before your first push — `main` is the
demo-ready branch and is not committed to directly.

## License

MIT — see [`LICENSE`](LICENSE).
