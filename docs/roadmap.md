# Roadmap

Four people, one hackathon clock. This document exists so that on day one
everybody knows what they are building and on day three nobody is surprised.

---

## Status

| Phase | State |
| --- | --- |
| 0 — Foundation | ✅ done |
| 1 — Stack ratified, walking skeleton | ✅ done — Flask + SQLite, seeded, CI green |
| 2 — Ledger and levels | ✅ done — all six invariants tested against real SQL |
| 3 — Reorder and valuation | ✅ done |
| 4 — Dashboard | ✅ done |
| 5 — Polish and rehearse | ⏳ in progress |

**The remaining work is rehearsal, not construction.** Every feature in the
problem statement is built and tested. What is left is running the demo script
below twice, on the actual demo machine, and fixing whatever breaks.

---

## Phases

### Phase 0 — Foundation ✅

*Done.*

- Repository scaffold, conventions, collaboration templates
- Domain model and invariants — [`domain-model.md`](domain-model.md)
- API contract — [`spec/openapi.yaml`](../spec/openapi.yaml)
- Runnable reference implementation of the domain logic — [`reference/`](../reference/)

### Phase 1 — Ratify the stack, build the walking skeleton

**Deliverable:** an empty but *running* application. Server starts, database
connects, migrations run, one endpoint returns real data from the database, the
frontend renders it.

- Ratify the stack in a `docs/` PR (see [architecture.md](architecture.md#recommendation))
- Schema and migrations for all entities in the domain model
- Seed script producing realistic data — multiple warehouses, a few hundred
  products, a month of movement history
- CI running the reference test suite on every push

**Exit criteria:** `docker compose up` (or equivalent) gives a working app with
seed data. Anyone on the team can run it from a clean checkout.

> Do not skip the seed script. It is what makes every later phase demoable.

### Phase 2 — The core: ledger and levels

**Deliverable:** the heart of the product, working end to end.

- Record receipts, deliveries, transfers, adjustments
- Derive stock levels from the ledger
- Move history with filters
- The availability guard (invariant 3) enforced at the API boundary
- Tests ported from `reference/test_stock_engine.py` to the real stack

**Exit criteria:** all six invariants from the domain model are enforced and
tested against the real database, not just the reference.

This is the phase where the product becomes real. Everything after it is
presentation and convenience.

### Phase 3 — Reorder and valuation

**Deliverable:** StockSense tells you what to buy and what it is worth.

- Reorder rules per product per warehouse
- Low-stock detection and a suggested order quantity
- Inventory valuation at cost, per warehouse
- A low-stock alert surface on the dashboard

**Exit criteria:** with seed data, the low-stock list is non-empty and the
numbers reconcile by hand against the ledger.

### Phase 4 — Dashboard

**Deliverable:** the screen you put on the projector.

- Live stock levels by product and warehouse
- Movement history with search and filter
- Low-stock alerts, actionable
- Fast entry forms for the four move kinds

**Exit criteria:** a warehouse operator who has never seen the app can record a
receipt without being told how.

### Phase 5 — Polish and rehearse

**Deliverable:** a demo that does not break on stage.

- Seed data tuned so every screen looks populated and plausible
- Written demo script, rehearsed at least twice, timed
- README quickstart verified from a clean clone on a machine that is not yours
- Empty and error states handled — judges click things you did not plan for
- Screenshots in the README

**Exit criteria:** two consecutive clean run-throughs, on time, no ad-libbing
around a broken feature.

## Workstreams

Module ownership. One person owns a module end to end — schema, logic, API,
tests. Modules are separated by the dependency rule in
[architecture.md](architecture.md#module-boundaries), so this parallelises
without merge conflicts.

| | Modules | Depends on | Notes |
| --- | --- | --- | --- |
| **A** | `catalog`, `network` | nothing | Build first — everyone else needs products and warehouses |
| **B** | `ledger`, `levels` | A | **Critical path.** The core. Give this your strongest person. |
| **C** | `reorder`, `valuation` | B | Can start against the reference implementation before B lands |
| **D** | `dashboard`, seed data | B, C | Can build against mocks from the API contract from hour one |

**Sequencing:** A and B start immediately. C and D build against the contract and
the reference implementation while B is in flight, then integrate. B is the
bottleneck — if it slips, everything slips, so protect it.

**Swarming:** when B is blocked or behind, everyone drops what they are doing and
helps. A demo with a polished dashboard over a broken ledger is a failed demo.

## Definition of done

A module is done when all of these are true. Not most of them.

- [ ] Behaviour matches [`domain-model.md`](domain-model.md)
- [ ] Invariants relevant to the module are tested against the real database
- [ ] Endpoints match [`spec/openapi.yaml`](../spec/openapi.yaml), or the spec is
      updated in the same PR
- [ ] Errors are handled — invalid input returns a useful message, not a stack trace
- [ ] Works against seeded data, not just a hand-built fixture
- [ ] Reviewed and approved by one teammate
- [ ] Merged to `main` via squash, with `main` still demo-ready

## Demo script

Write this in Phase 1, rehearse it in Phase 5. Six beats, three minutes:

1. **The problem** — hold up the paper register and the spreadsheet. Ten seconds.
2. **Receive stock** — goods arrive at MAIN. Record it. Level updates live.
3. **Transfer between warehouses** — 30 units MAIN → NORTH. Both levels move;
   total is unchanged. *This is the moment that lands.*
4. **Ship to a customer** — deliver. Show the availability guard rejecting an
   over-draw, so the system visibly refuses to lie.
5. **The alert** — open the low-stock list. BOLT-M8 is below minimum. It tells you
   to order 92. Nobody had to notice this manually.
6. **The ledger** — open the movement history. Every number on screen traces back
   to a row with a reference, a time and a person.

Close on the ledger. It is the thing that makes the rest credible.

## Risks

| Risk | Mitigation |
| --- | --- |
| Stack not ratified, work stalls | Decide in Phase 1, in writing, and move on |
| Ledger work (B) is underestimated | It is the critical path — staff it first, swarm if it slips |
| Seed data left to the end | Build it in Phase 1, not Phase 5 |
| Demo breaks on stage | Rehearse twice; keep a recorded backup run |
| Four people editing the same files | Module ownership plus small, short-lived branches |
| Levels drift from the ledger | Invariant tests in CI on every push — never bypass |
