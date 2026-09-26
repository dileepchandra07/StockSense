"""Invariant tests for the StockSense reference engine.

Every rule in ``docs/domain-model.md`` has a test here. Run with::

    python3 -m unittest -v
"""

import dataclasses
import unittest

from stock_engine import (
    ADJUSTMENT_LOCATION,
    CUSTOMER_LOCATION,
    SUPPLIER_LOCATION,
    DuplicateEntity,
    InsufficientStock,
    InvalidQuantity,
    LocationKind,
    MoveKind,
    StockEngine,
    StockError,
    UnknownEntity,
)


def build_engine() -> StockEngine:
    """Two warehouses, two products, no stock. The standard fixture."""
    engine = StockEngine(operator="tester")
    engine.add_warehouse("MAIN", "Main Distribution Centre")
    engine.add_warehouse("NORTH", "North Regional Depot")
    engine.add_product(
        "WIDGET-A", "Steel widget, 12mm", category="fasteners", unit_cost=24.50
    )
    engine.add_product("BOLT-M8", "Hex bolt M8", category="fasteners", unit_cost=2.00)
    return engine


def fold_ledger_by_hand(engine: StockEngine) -> dict[tuple[str, str], float]:
    """Independently recompute levels from the ledger, without engine.levels().

    This is the point of the invariant-1 test: two independent folds of the same
    ledger must agree. If they ever diverge, the derivation is wrong.
    """
    kinds = {location.code: location.kind for location in engine.locations()}
    totals: dict[tuple[str, str], float] = {}
    for move in engine.ledger():
        for code, sign in ((move.dst, 1.0), (move.src, -1.0)):
            if kinds[code] is not LocationKind.INTERNAL:
                continue
            key = (move.sku, code)
            totals[key] = totals.get(key, 0.0) + sign * move.qty
    return {key: qty for key, qty in totals.items() if qty != 0.0}


# ---------------------------------------------------------------------------
# Invariant 1 -- levels are derived from the ledger
# ---------------------------------------------------------------------------


class TestLevelsAreDerived(unittest.TestCase):
    def test_levels_match_an_independent_fold_of_the_ledger(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 120, "PO-1")
        engine.receive("WIDGET-A", "NORTH", 40, "PO-2")
        engine.deliver("WIDGET-A", "MAIN", 25, "SO-1")
        engine.transfer("WIDGET-A", "MAIN", "NORTH", 30, "TRF-1")
        engine.adjust("WIDGET-A", "MAIN", 60, "ADJ-1")

        self.assertEqual(fold_ledger_by_hand(engine), engine.levels())

    def test_no_endpoint_sets_a_level_directly(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.deliver("WIDGET-A", "MAIN", 40, "SO-1")

        # The level is 60 only because the ledger says so. There is no other path.
        self.assertEqual(engine.on_hand("WIDGET-A", "MAIN"), 60)
        self.assertEqual(len(engine.ledger()), 2)

    def test_levels_are_zero_for_products_with_no_moves(self):
        engine = build_engine()
        self.assertEqual(engine.on_hand("WIDGET-A"), 0.0)
        self.assertEqual(engine.levels(), {})

    def test_levels_are_scoped_per_location_not_per_warehouse(self):
        engine = build_engine()
        engine.add_location("MAIN", "A1")
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.receive("WIDGET-A", "MAIN", 40, "PO-2", location="A1")

        # Deliberately order-independent: the reporting view sorts by location code,
        # so indexing into it would make this test fragile for no good reason.
        by_location = {
            row["location"]: row["qty"] for row in engine.stock_levels(sku="WIDGET-A")
        }
        self.assertEqual(by_location, {"MAIN/STOCK": 100, "MAIN/A1": 40})
        self.assertEqual(engine.on_hand("WIDGET-A", "MAIN"), 140)


# ---------------------------------------------------------------------------
# Invariant 2 -- transfers conserve quantity
# ---------------------------------------------------------------------------


class TestTransfersConserveQuantity(unittest.TestCase):
    def test_total_quantity_is_unchanged_by_a_transfer(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        before = engine.on_hand("WIDGET-A")

        engine.transfer("WIDGET-A", "MAIN", "NORTH", 30, "TRF-1")

        self.assertEqual(engine.on_hand("WIDGET-A"), before)

    def test_transfer_moves_stock_between_warehouses(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.transfer("WIDGET-A", "MAIN", "NORTH", 30, "TRF-1")

        self.assertEqual(engine.on_hand("WIDGET-A", "MAIN"), 70)
        self.assertEqual(engine.on_hand("WIDGET-A", "NORTH"), 30)

    def test_transfer_records_a_single_move_of_positive_quantity(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        move = engine.transfer("WIDGET-A", "MAIN", "NORTH", 30, "TRF-1")

        self.assertEqual(move.kind, MoveKind.TRANSFER)
        self.assertEqual(move.qty, 30)
        self.assertEqual(move.src, "MAIN/STOCK")
        self.assertEqual(move.dst, "NORTH/STOCK")

    def test_transfer_within_one_warehouse_is_rejected(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        with self.assertRaises(StockError):
            engine.transfer("WIDGET-A", "MAIN", "MAIN", 10, "TRF-1")


# ---------------------------------------------------------------------------
# Invariant 3 -- internal stock never goes negative
# ---------------------------------------------------------------------------


class TestStockNeverGoesNegative(unittest.TestCase):
    def test_delivering_more_than_available_is_rejected(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 65, "PO-1")

        with self.assertRaises(InsufficientStock) as caught:
            engine.deliver("WIDGET-A", "MAIN", 500, "SO-1")

        self.assertIn("only 65 on hand", str(caught.exception))

    def test_a_rejected_delivery_leaves_the_ledger_untouched(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 65, "PO-1")

        with self.assertRaises(InsufficientStock):
            engine.deliver("WIDGET-A", "MAIN", 500, "SO-1")

        self.assertEqual(len(engine.ledger()), 1)
        self.assertEqual(engine.on_hand("WIDGET-A", "MAIN"), 65)

    def test_transferring_more_than_available_is_rejected(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 10, "PO-1")

        with self.assertRaises(InsufficientStock):
            engine.transfer("WIDGET-A", "MAIN", "NORTH", 50, "TRF-1")

    def test_delivering_exactly_the_available_quantity_is_allowed(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 65, "PO-1")
        engine.deliver("WIDGET-A", "MAIN", 65, "SO-1")

        self.assertEqual(engine.on_hand("WIDGET-A", "MAIN"), 0.0)

    def test_an_adjustment_may_reduce_stock_to_zero(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.adjust("WIDGET-A", "MAIN", 0, "ADJ-1")

        self.assertEqual(engine.on_hand("WIDGET-A", "MAIN"), 0.0)

    def test_a_negative_count_is_rejected(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")

        with self.assertRaises(InvalidQuantity):
            engine.adjust("WIDGET-A", "MAIN", -5, "ADJ-1")


# ---------------------------------------------------------------------------
# Invariant 4 -- every move is traceable
# ---------------------------------------------------------------------------


class TestEveryMoveIsTraceable(unittest.TestCase):
    def test_an_empty_reference_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(StockError):
            engine.receive("WIDGET-A", "MAIN", 10, "")

    def test_a_whitespace_reference_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(StockError):
            engine.receive("WIDGET-A", "MAIN", 10, "   ")

    def test_every_recorded_move_carries_its_reference_and_author(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1", created_by="harsha")
        engine.deliver("WIDGET-A", "MAIN", 10, "SO-1", created_by="harsha")

        for move in engine.ledger():
            self.assertTrue(move.reference)
            self.assertEqual(move.created_by, "harsha")
            self.assertIsNotNone(move.created_at)


# ---------------------------------------------------------------------------
# Invariant 5 -- quantity is strictly positive
# ---------------------------------------------------------------------------


class TestQuantityIsPositive(unittest.TestCase):
    def test_a_zero_quantity_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(InvalidQuantity):
            engine.receive("WIDGET-A", "MAIN", 0, "PO-1")

    def test_a_negative_quantity_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(InvalidQuantity):
            engine.receive("WIDGET-A", "MAIN", -10, "PO-1")

    def test_direction_is_encoded_in_endpoints_not_in_sign(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        move = engine.deliver("WIDGET-A", "MAIN", 25, "SO-1")

        self.assertEqual(move.qty, 25)  # positive
        self.assertEqual(move.src, "MAIN/STOCK")  # direction is here
        self.assertEqual(move.dst, CUSTOMER_LOCATION)


# ---------------------------------------------------------------------------
# Invariant 6 -- history is immutable
# ---------------------------------------------------------------------------


class TestHistoryIsImmutable(unittest.TestCase):
    def test_a_recorded_move_cannot_be_mutated(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")

        with self.assertRaises(dataclasses.FrozenInstanceError):
            engine.ledger()[0].qty = 999

    def test_the_returned_ledger_is_a_copy(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")

        snapshot = engine.ledger()
        snapshot.clear()

        self.assertEqual(len(engine.ledger()), 1)

    def test_moves_accumulate_in_order(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.deliver("WIDGET-A", "MAIN", 10, "SO-1")
        engine.transfer("WIDGET-A", "MAIN", "NORTH", 5, "TRF-1")

        self.assertEqual([move.id for move in engine.ledger()], [1, 2, 3])
        self.assertEqual(
            [move.kind for move in engine.ledger()],
            [MoveKind.RECEIPT, MoveKind.DELIVERY, MoveKind.TRANSFER],
        )


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------


class TestAdjustments(unittest.TestCase):
    def test_an_adjustment_records_the_delta_not_the_count(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        move = engine.adjust("WIDGET-A", "MAIN", 97, "ADJ-1")

        self.assertEqual(move.qty, 3)
        self.assertEqual(move.src, "MAIN/STOCK")
        self.assertEqual(move.dst, ADJUSTMENT_LOCATION)
        self.assertEqual(engine.on_hand("WIDGET-A", "MAIN"), 97)

    def test_an_upward_adjustment_draws_from_the_adjustment_location(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        move = engine.adjust("WIDGET-A", "MAIN", 104, "ADJ-1")

        self.assertEqual(move.qty, 4)
        self.assertEqual(move.src, ADJUSTMENT_LOCATION)
        self.assertEqual(move.dst, "MAIN/STOCK")
        self.assertEqual(engine.on_hand("WIDGET-A", "MAIN"), 104)

    def test_a_count_that_already_matches_records_nothing(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")

        self.assertIsNone(engine.adjust("WIDGET-A", "MAIN", 100, "ADJ-1"))
        self.assertEqual(len(engine.ledger()), 1)

    def test_a_correction_is_visible_in_the_history(self):
        """The whole point: a wrong number traces back to the moment it was fixed."""
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.adjust("WIDGET-A", "MAIN", 97, "ADJ-2026-0007")

        correction = engine.moves(kind=MoveKind.ADJUSTMENT)[0]
        self.assertEqual(correction.reference, "ADJ-2026-0007")
        self.assertEqual(correction.kind, MoveKind.ADJUSTMENT)


# ---------------------------------------------------------------------------
# Catalog and network validation
# ---------------------------------------------------------------------------


class TestValidation(unittest.TestCase):
    def test_an_unknown_product_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(UnknownEntity):
            engine.receive("NOPE", "MAIN", 10, "PO-1")

    def test_an_unknown_warehouse_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(UnknownEntity):
            engine.receive("WIDGET-A", "NOWHERE", 10, "PO-1")

    def test_a_duplicate_product_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(DuplicateEntity):
            engine.add_product("WIDGET-A", "Another widget")

    def test_a_duplicate_warehouse_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(DuplicateEntity):
            engine.add_warehouse("MAIN", "Duplicate")

    def test_a_negative_unit_cost_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(ValueError):
            engine.add_product("BAD", "Bad product", unit_cost=-1)

    def test_receiving_into_a_specific_bin_works(self):
        engine = build_engine()
        engine.add_location("MAIN", "A1")
        engine.receive("WIDGET-A", "MAIN", 40, "PO-1", location="A1")

        self.assertEqual(engine.stock_levels(sku="WIDGET-A")[0]["location"], "MAIN/A1")

    def test_a_bin_may_be_named_without_the_warehouse_prefix(self):
        engine = build_engine()
        engine.add_location("MAIN", "A1")
        engine.receive("WIDGET-A", "MAIN", 40, "PO-1", location="A1")

        self.assertEqual(engine.on_hand("WIDGET-A", "MAIN"), 40)

    def test_receiving_into_a_virtual_location_is_rejected(self):
        engine = build_engine()
        engine.add_location("MAIN", "STAGING", kind=LocationKind.SUPPLIER)

        with self.assertRaises(StockError):
            engine.receive("WIDGET-A", "MAIN", 10, "PO-1", location="STAGING")

    def test_using_another_warehouse_bin_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(StockError):
            engine.receive("WIDGET-A", "MAIN", 10, "PO-1", location="NORTH/STOCK")

    def test_virtual_locations_never_appear_in_levels(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.deliver("WIDGET-A", "MAIN", 10, "SO-1")
        engine.adjust("WIDGET-A", "MAIN", 95, "ADJ-1")

        virtual = {SUPPLIER_LOCATION, CUSTOMER_LOCATION, ADJUSTMENT_LOCATION}
        for (_, location_code) in engine.levels():
            self.assertNotIn(location_code, virtual)

    def test_a_new_warehouse_gets_a_default_internal_location(self):
        engine = build_engine()
        internal = engine.locations(warehouse="MAIN", kind=LocationKind.INTERNAL)

        self.assertEqual([location.code for location in internal], ["MAIN/STOCK"])


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


class TestReorder(unittest.TestCase):
    def test_a_product_below_its_minimum_is_reported(self):
        engine = build_engine()
        engine.receive("BOLT-M8", "MAIN", 8, "PO-1")
        engine.set_reorder_rule("BOLT-M8", "MAIN", min_qty=50, max_qty=100)

        low = engine.low_stock()

        self.assertEqual(len(low), 1)
        self.assertEqual(low[0]["sku"], "BOLT-M8")
        self.assertEqual(low[0]["on_hand"], 8)
        self.assertEqual(low[0]["suggested_order_qty"], 92)

    def test_a_product_at_or_above_its_minimum_is_not_reported(self):
        engine = build_engine()
        engine.receive("BOLT-M8", "MAIN", 50, "PO-1")
        engine.set_reorder_rule("BOLT-M8", "MAIN", min_qty=50, max_qty=100)

        self.assertEqual(engine.low_stock(), [])

    def test_low_stock_is_ordered_by_largest_shortfall(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 90, "PO-1")
        engine.receive("BOLT-M8", "MAIN", 8, "PO-2")
        engine.set_reorder_rule("WIDGET-A", "MAIN", min_qty=100, max_qty=200)
        engine.set_reorder_rule("BOLT-M8", "MAIN", min_qty=50, max_qty=100)

        low = engine.low_stock()

        self.assertEqual([item["sku"] for item in low], ["BOLT-M8", "WIDGET-A"])

    def test_rules_are_scoped_per_warehouse(self):
        engine = build_engine()
        engine.receive("BOLT-M8", "MAIN", 8, "PO-1")
        engine.receive("BOLT-M8", "NORTH", 500, "PO-2")
        engine.set_reorder_rule("BOLT-M8", "MAIN", min_qty=50, max_qty=100)
        engine.set_reorder_rule("BOLT-M8", "NORTH", min_qty=50, max_qty=100)

        self.assertEqual([item["warehouse"] for item in engine.low_stock()], ["MAIN"])

    def test_an_inverted_rule_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(ValueError):
            engine.set_reorder_rule("BOLT-M8", "MAIN", min_qty=100, max_qty=50)

    def test_a_rule_for_an_unknown_product_is_rejected(self):
        engine = build_engine()
        with self.assertRaises(UnknownEntity):
            engine.set_reorder_rule("NOPE", "MAIN", min_qty=1, max_qty=2)


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------


class TestValuation(unittest.TestCase):
    def test_valuation_is_quantity_times_unit_cost(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")

        self.assertEqual(engine.valuation(), 2450.0)

    def test_valuation_spans_products_and_warehouses(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.receive("BOLT-M8", "NORTH", 50, "PO-2")

        self.assertEqual(engine.valuation(), 2450.0 + 100.0)

    def test_valuation_can_be_scoped_to_a_warehouse(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.receive("WIDGET-A", "NORTH", 10, "PO-2")

        self.assertEqual(engine.valuation(warehouse="MAIN"), 2450.0)
        self.assertEqual(engine.valuation(warehouse="NORTH"), 245.0)
        self.assertEqual(
            engine.valuation_by_warehouse(), {"MAIN": 2450.0, "NORTH": 245.0}
        )

    def test_valuation_drops_after_a_delivery(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.deliver("WIDGET-A", "MAIN", 100, "SO-1")

        self.assertEqual(engine.valuation(), 0.0)


# ---------------------------------------------------------------------------
# Ledger queries
# ---------------------------------------------------------------------------


class TestLedgerQueries(unittest.TestCase):
    def test_moves_are_returned_newest_first_by_default(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.deliver("WIDGET-A", "MAIN", 10, "SO-1")

        self.assertEqual(engine.moves()[0].reference, "SO-1")
        self.assertEqual(engine.moves(newest_first=False)[0].reference, "PO-1")

    def test_moves_can_be_filtered_by_kind(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.deliver("WIDGET-A", "MAIN", 10, "SO-1")

        receipts = engine.moves(kind=MoveKind.RECEIPT)
        self.assertEqual([move.reference for move in receipts], ["PO-1"])

    def test_moves_can_be_filtered_by_warehouse(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.receive("WIDGET-A", "NORTH", 50, "PO-2")

        self.assertEqual(
            [move.reference for move in engine.moves(warehouse="NORTH")], ["PO-2"]
        )

    def test_a_transfer_is_visible_from_both_warehouses(self):
        engine = build_engine()
        engine.receive("WIDGET-A", "MAIN", 100, "PO-1")
        engine.transfer("WIDGET-A", "MAIN", "NORTH", 30, "TRF-1")

        self.assertEqual(len(engine.moves(warehouse="MAIN")), 2)
        self.assertEqual(len(engine.moves(warehouse="NORTH")), 1)

    def test_moves_can_be_limited(self):
        engine = build_engine()
        for index in range(5):
            engine.receive("WIDGET-A", "MAIN", 10, f"PO-{index}")

        self.assertEqual(len(engine.moves(limit=2)), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
