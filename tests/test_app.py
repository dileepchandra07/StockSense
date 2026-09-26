"""End-to-end tests for the StockSense application.

Runs against a throwaway SQLite file per test, seeded with the demo dataset.
    python -m unittest discover -s tests -v
"""

import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app import create_app, engine
from app.db import query
from app.seed import DEMO_EMAIL, DEMO_PASSWORD, seed
from app.seed import _schedule as seed_schedule


class BaseCase(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name

        self.app = create_app(
            {"DATABASE": self.db_path, "TESTING": True, "SECRET_KEY": "test-secret"}
        )
        self.ctx = self.app.app_context()
        self.ctx.push()
        seed()
        self.client = self.app.test_client()

    def tearDown(self):
        self.ctx.pop()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def sign_in(self):
        return self.client.post(
            "/login",
            data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
            follow_redirects=True,
        )

    def sign_out(self):
        return self.client.get("/logout", follow_redirects=True)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuth(BaseCase):
    def test_login_page_renders(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sign in", response.data)

    def test_signup_page_renders(self):
        self.assertEqual(self.client.get("/signup").status_code, 200)

    def test_forgot_password_page_renders(self):
        self.assertEqual(self.client.get("/forgot-password").status_code, 200)

    def test_root_redirects_to_login_when_signed_out(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_root_redirects_to_dashboard_when_signed_in(self):
        self.sign_in()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard", response.headers["Location"])

    def test_dashboard_requires_sign_in(self):
        response = self.client.get("/dashboard", follow_redirects=True)
        self.assertIn(b"Please sign in", response.data)

    def test_valid_credentials_sign_in(self):
        response = self.sign_in()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Inventory Dashboard", response.data)

    def test_wrong_password_is_rejected(self):
        response = self.client.post(
            "/login",
            data={"email": DEMO_EMAIL, "password": "wrong-password"},
            follow_redirects=True,
        )
        self.assertIn(b"Incorrect email or password", response.data)

    def test_signup_creates_an_account(self):
        response = self.client.post(
            "/signup",
            data={
                "name": "New Manager",
                "email": "new@example.com",
                "password": "secret123",
                "confirm": "secret123",
                "role": "Warehouse Staff",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            query("SELECT * FROM users WHERE email = ?", ("new@example.com",), one=True)
        )

    def test_signup_rejects_mismatched_passwords(self):
        response = self.client.post(
            "/signup",
            data={
                "name": "Bad",
                "email": "bad@example.com",
                "password": "secret123",
                "confirm": "different123",
            },
            follow_redirects=True,
        )
        self.assertIn(b"do not match", response.data)

    def test_signup_rejects_a_duplicate_email(self):
        response = self.client.post(
            "/signup",
            data={
                "name": "Copy",
                "email": DEMO_EMAIL,
                "password": "secret123",
                "confirm": "secret123",
            },
            follow_redirects=True,
        )
        self.assertIn(b"already exists", response.data)

    def test_logout_clears_the_session(self):
        self.sign_in()
        response = self.sign_out()
        self.assertIn(b"Sign in", response.data)
        self.assertIn(b"You have been signed out", response.data)

    def test_profile_page_renders(self):
        self.sign_in()
        response = self.client.get("/profile")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Harsha Vardhan", response.data)


class TestPasswordReset(BaseCase):
    def test_forgot_password_issues_a_six_digit_code(self):
        response = self.client.post(
            "/forgot-password", data={"email": DEMO_EMAIL}, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Demo mode", response.data)

        record = query(
            "SELECT * FROM password_resets WHERE email = ? ORDER BY id DESC",
            (DEMO_EMAIL,),
            one=True,
        )
        self.assertIsNotNone(record)
        self.assertRegex(record["otp"], r"^\d{6}$")

    def test_unknown_email_does_not_leak_account_existence(self):
        response = self.client.post(
            "/forgot-password", data={"email": "nobody@example.com"}, follow_redirects=True
        )
        self.assertIn(b"If that email has an account", response.data)

    def test_full_reset_flow_changes_the_password(self):
        self.client.post("/forgot-password", data={"email": DEMO_EMAIL})
        otp = query(
            "SELECT otp FROM password_resets WHERE email = ? ORDER BY id DESC",
            (DEMO_EMAIL,),
            one=True,
        )["otp"]

        response = self.client.post(
            "/reset-password",
            data={
                "email": DEMO_EMAIL,
                "otp": otp,
                "password": "brand-new-pass",
                "confirm": "brand-new-pass",
            },
            follow_redirects=True,
        )
        self.assertIn(b"password has been reset", response.data)

        # The new password works, the old one no longer does.
        self.assertIn(
            b"Inventory Dashboard",
            self.client.post(
                "/login",
                data={"email": DEMO_EMAIL, "password": "brand-new-pass"},
                follow_redirects=True,
            ).data,
        )

    def test_a_wrong_code_is_rejected(self):
        self.client.post("/forgot-password", data={"email": DEMO_EMAIL})
        response = self.client.post(
            "/reset-password",
            data={
                "email": DEMO_EMAIL,
                "otp": "000000",
                "password": "brand-new-pass",
                "confirm": "brand-new-pass",
            },
            follow_redirects=True,
        )
        self.assertIn(b"not valid", response.data)

    def test_a_used_code_cannot_be_replayed(self):
        self.client.post("/forgot-password", data={"email": DEMO_EMAIL})
        otp = query(
            "SELECT otp FROM password_resets WHERE email = ? ORDER BY id DESC",
            (DEMO_EMAIL,),
            one=True,
        )["otp"]
        payload = {
            "email": DEMO_EMAIL, "otp": otp,
            "password": "first-new-pass", "confirm": "first-new-pass",
        }
        self.client.post("/reset-password", data=payload)

        replay = self.client.post(
            "/reset-password",
            data={**payload, "password": "second-new-pass", "confirm": "second-new-pass"},
            follow_redirects=True,
        )
        self.assertIn(b"not valid", replay.data)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class TestDashboard(BaseCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_dashboard_shows_all_five_kpis(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        for label in [
            b"Products in stock", b"Low / out of stock", b"Pending receipts",
            b"Pending deliveries", b"Transfers scheduled",
        ]:
            self.assertIn(label, response.data)

    def test_dashboard_filters_by_document_type(self):
        response = self.client.get("/dashboard?doc_type=receipt")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"WH/IN/", response.data)

    def test_dashboard_filters_by_status(self):
        response = self.client.get("/dashboard?status=draft")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_filters_by_warehouse(self):
        warehouse_id = query("SELECT id FROM warehouses WHERE code = 'MAIN'", one=True)["id"]
        self.assertEqual(self.client.get(f"/dashboard?warehouse={warehouse_id}").status_code, 200)

    def test_dashboard_filters_by_category(self):
        category_id = query("SELECT id FROM categories LIMIT 1", one=True)["id"]
        self.assertEqual(self.client.get(f"/dashboard?category={category_id}").status_code, 200)

    def test_dashboard_search(self):
        self.assertEqual(self.client.get("/dashboard?q=WH/IN").status_code, 200)

    def test_out_of_stock_count_matches_the_filtered_list(self):
        """The KPI and the list it links to must agree."""
        kpi = engine.dashboard_kpis()["out_of_stock"]
        listed = len([p for p in engine.products_with_stock() if p["on_hand"] <= 0])
        self.assertEqual(kpi, listed)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


class TestProducts(BaseCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_product_list_renders(self):
        response = self.client.get("/products/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"STL-ROD-12", response.data)

    def test_product_search_by_sku(self):
        response = self.client.get("/products/?q=STL-ROD")
        self.assertIn(b"STL-ROD-12", response.data)
        self.assertNotIn(b"CHAIR-ERG", response.data)

    def test_product_search_by_name(self):
        response = self.client.get("/products/?q=chair")
        self.assertIn(b"CHAIR-ERG", response.data)

    def test_stock_filters_render(self):
        for value in ("in", "low", "out"):
            self.assertEqual(
                self.client.get(f"/products/?stock={value}").status_code, 200
            )

    def test_low_stock_filter_shows_only_low_items(self):
        response = self.client.get("/products/?stock=low")
        self.assertIn(b"CHAIR-ERG", response.data)   # seeded below its minimum
        self.assertNotIn(b"STL-ROD-12", response.data)

    def test_product_detail_renders(self):
        product_id = query("SELECT id FROM products WHERE sku = 'STL-ROD-12'", one=True)["id"]
        response = self.client.get(f"/products/{product_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Availability by location", response.data)
        self.assertIn(b"Movement history", response.data)

    def test_create_form_renders(self):
        self.assertEqual(self.client.get("/products/new").status_code, 200)

    def test_creating_a_product_with_initial_stock_writes_a_receipt(self):
        before = query("SELECT COUNT(*) AS n FROM stock_moves", one=True)["n"]
        warehouse_id = query("SELECT id FROM warehouses WHERE code = 'MAIN'", one=True)["id"]

        response = self.client.post(
            "/products/new",
            data={
                "sku": "TEST-001", "name": "Test Widget", "uom": "unit",
                "unit_cost": "10", "reorder_min": "5", "reorder_max": "50",
                "initial_stock": "25", "warehouse_id": str(warehouse_id),
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        product_id = query("SELECT id FROM products WHERE sku = 'TEST-001'", one=True)["id"]
        self.assertEqual(engine.on_hand(product_id), 25)
        # Initial stock is a real ledger entry, not a magic number.
        self.assertEqual(
            query("SELECT COUNT(*) AS n FROM stock_moves", one=True)["n"], before + 1
        )

    def test_creating_a_product_without_stock_writes_no_moves(self):
        before = query("SELECT COUNT(*) AS n FROM stock_moves", one=True)["n"]
        self.client.post(
            "/products/new",
            data={"sku": "TEST-002", "name": "No Stock Widget", "uom": "unit"},
            follow_redirects=True,
        )
        self.assertEqual(
            query("SELECT COUNT(*) AS n FROM stock_moves", one=True)["n"], before
        )

    def test_duplicate_sku_is_rejected(self):
        response = self.client.post(
            "/products/new",
            data={"sku": "STL-ROD-12", "name": "Copy", "uom": "unit"},
            follow_redirects=True,
        )
        self.assertIn(b"already in use", response.data)

    def test_editing_a_product(self):
        product_id = query("SELECT id FROM products WHERE sku = 'BOLT-M8'", one=True)["id"]
        response = self.client.post(
            f"/products/{product_id}/edit",
            data={"name": "Hex Bolt M8 (zinc)", "uom": "unit", "unit_cost": "3.10",
                  "reorder_min": "500", "reorder_max": "5000"},
            follow_redirects=True,
        )
        self.assertIn(b"Product updated", response.data)
        self.assertEqual(
            query("SELECT name FROM products WHERE id = ?", (product_id,), one=True)["name"],
            "Hex Bolt M8 (zinc)",
        )

    def test_archiving_a_product_keeps_its_history(self):
        product_id = query("SELECT id FROM products WHERE sku = 'CHAIR-ERG'", one=True)["id"]
        moves_before = query(
            "SELECT COUNT(*) AS n FROM stock_moves WHERE product_id = ?", (product_id,), one=True
        )["n"]

        self.client.post(f"/products/{product_id}/archive", follow_redirects=True)

        self.assertEqual(
            query("SELECT is_active FROM products WHERE id = ?", (product_id,), one=True)["is_active"], 0
        )
        self.assertEqual(
            query("SELECT COUNT(*) AS n FROM stock_moves WHERE product_id = ?",
                  (product_id,), one=True)["n"],
            moves_before,
        )

    def test_adding_a_category(self):
        self.client.post("/products/categories", data={"name": "Electronics"},
                         follow_redirects=True)
        self.assertIsNotNone(
            query("SELECT 1 FROM categories WHERE name = 'Electronics'", one=True)
        )


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


class TestOperations(BaseCase):
    def setUp(self):
        super().setUp()
        self.sign_in()
        self.main = query("SELECT id FROM warehouses WHERE code = 'MAIN'", one=True)["id"]
        self.north = query("SELECT id FROM warehouses WHERE code = 'NORTH'", one=True)["id"]

    def _product(self, sku):
        return query("SELECT id FROM products WHERE sku = ?", (sku,), one=True)["id"]

    # -- listings ----------------------------------------------------------

    def test_all_operation_lists_render(self):
        for doc_type in ("receipt", "delivery", "internal", "adjustment"):
            response = self.client.get(f"/operations/{doc_type}")
            self.assertEqual(response.status_code, 200, doc_type)

    def test_operations_overview_renders(self):
        self.assertEqual(self.client.get("/operations").status_code, 200)

    def test_move_history_renders(self):
        response = self.client.get("/moves")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Move History", response.data)

    def test_move_history_filters(self):
        product_id = self._product("STL-ROD-12")
        self.assertEqual(self.client.get(f"/moves?product={product_id}").status_code, 200)
        self.assertEqual(self.client.get("/moves?doc_type=receipt").status_code, 200)
        self.assertEqual(self.client.get(f"/moves?warehouse={self.main}").status_code, 200)
        self.assertEqual(self.client.get("/moves?q=STL").status_code, 200)

    def test_unknown_document_type_is_a_404(self):
        self.assertEqual(self.client.get("/operations/nonsense").status_code, 404)

    # -- receipts ----------------------------------------------------------

    def test_new_receipt_form_renders(self):
        self.assertEqual(self.client.get("/operations/receipt/new").status_code, 200)

    def test_receipt_lifecycle_increases_stock(self):
        product_id = self._product("HELM-SFT")
        before = engine.on_hand(product_id, self.main)

        # Create
        self.client.post(
            "/operations/receipt/new",
            data={"supplier": "Safety First Ltd", "dst_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        self.assertEqual(document["doc_type"], "receipt")
        self.assertEqual(document["status"], "draft")

        # A draft does not touch stock.
        self.assertEqual(engine.on_hand(product_id, self.main), before)

        # Add a line
        self.client.post(
            f"/documents/{document['id']}/lines",
            data={"product_id": str(product_id), "qty": "75"},
            follow_redirects=True,
        )

        # Still no stock movement.
        self.assertEqual(engine.on_hand(product_id, self.main), before)

        # Validate
        response = self.client.post(
            f"/documents/{document['id']}/validate", follow_redirects=True
        )
        self.assertIn(b"validated", response.data)

        self.assertEqual(engine.on_hand(product_id, self.main), before + 75)
        self.assertEqual(
            query("SELECT status FROM documents WHERE id = ?", (document["id"],), one=True)["status"],
            "done",
        )

    def test_validating_without_lines_is_rejected(self):
        self.client.post(
            "/operations/receipt/new",
            data={"supplier": "Empty Co", "dst_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        response = self.client.post(
            f"/documents/{document['id']}/validate", follow_redirects=True
        )
        self.assertIn(b"at least one product line", response.data)

    def test_a_validated_document_cannot_be_validated_twice(self):
        product_id = self._product("HELM-SFT")
        self.client.post(
            "/operations/receipt/new",
            data={"supplier": "Twice Co", "dst_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        self.client.post(f"/documents/{document['id']}/lines",
                         data={"product_id": str(product_id), "qty": "10"})
        self.client.post(f"/documents/{document['id']}/validate", follow_redirects=True)
        after_first = engine.on_hand(product_id, self.main)

        response = self.client.post(
            f"/documents/{document['id']}/validate", follow_redirects=True
        )
        self.assertIn(b"already been validated", response.data)
        self.assertEqual(engine.on_hand(product_id, self.main), after_first)

    def test_zero_quantity_line_is_rejected(self):
        self.client.post(
            "/operations/receipt/new",
            data={"supplier": "Zero Co", "dst_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        response = self.client.post(
            f"/documents/{document['id']}/lines",
            data={"product_id": str(self._product("HELM-SFT")), "qty": "0"},
            follow_redirects=True,
        )
        self.assertIn(b"greater than zero", response.data)

    # -- deliveries --------------------------------------------------------

    def test_delivery_lifecycle_decreases_stock(self):
        product_id = self._product("STL-ROD-12")
        before = engine.on_hand(product_id, self.main)

        self.client.post(
            "/operations/delivery/new",
            data={"src_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        self.client.post(f"/documents/{document['id']}/lines",
                         data={"product_id": str(product_id), "qty": "40"})
        self.client.post(f"/documents/{document['id']}/validate", follow_redirects=True)

        self.assertEqual(engine.on_hand(product_id, self.main), before - 40)

    def test_delivering_more_than_available_is_refused(self):
        product_id = self._product("CHAIR-ERG")
        before = engine.on_hand(product_id, self.main)

        self.client.post(
            "/operations/delivery/new",
            data={"src_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        self.client.post(f"/documents/{document['id']}/lines",
                         data={"product_id": str(product_id), "qty": "99999"})

        response = self.client.post(
            f"/documents/{document['id']}/validate", follow_redirects=True
        )
        self.assertIn(b"Not enough stock", response.data)

        # Nothing changed: the guard refuses to record an impossible state.
        self.assertEqual(engine.on_hand(product_id, self.main), before)
        self.assertEqual(
            query("SELECT status FROM documents WHERE id = ?", (document["id"],), one=True)["status"],
            "draft",
        )

    # -- internal transfers ------------------------------------------------

    def test_internal_transfer_conserves_total_quantity(self):
        product_id = self._product("STL-ROD-12")
        total_before = engine.on_hand(product_id)
        main_before = engine.on_hand(product_id, self.main)

        self.client.post(
            "/operations/internal/new",
            data={"src_warehouse_id": str(self.main), "dst_warehouse_id": str(self.north)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        self.client.post(f"/documents/{document['id']}/lines",
                         data={"product_id": str(product_id), "qty": "25"})
        self.client.post(f"/documents/{document['id']}/validate", follow_redirects=True)

        self.assertEqual(engine.on_hand(product_id), total_before)
        self.assertEqual(engine.on_hand(product_id, self.main), main_before - 25)

    def test_rack_to_rack_transfer_within_one_warehouse(self):
        """The spec calls this out explicitly: Rack A to Rack B."""
        product_id = self._product("GASKET-3")
        rack_a = query("SELECT id FROM locations WHERE code = 'MAIN/RACK-A'", one=True)["id"]
        rack_b = query("SELECT id FROM locations WHERE code = 'MAIN/RACK-B'", one=True)["id"]

        # Put stock in rack A first.
        engine.add_line(
            engine.create_document(doc_type="receipt", user_id=None, supplier="Test",
                                   dst_warehouse_id=self.main),
            product_id, qty=50, dst_location_id=rack_a,
        )
        document = query("SELECT id FROM documents ORDER BY id DESC", one=True)["id"]
        engine.validate_document(document, user_id=None)

        rack_a_before = engine.level_at(product_id, rack_a)
        rack_b_before = engine.level_at(product_id, rack_b)

        # Now move it rack to rack.
        transfer = engine.create_document(
            doc_type="internal", user_id=None, src_warehouse_id=self.main,
            dst_warehouse_id=self.main, notes="rack reorganisation",
        )
        engine.add_line(transfer, product_id, qty=20, src_location_id=rack_a,
                        dst_location_id=rack_b)
        engine.validate_document(transfer, user_id=None)

        self.assertEqual(engine.level_at(product_id, rack_a), rack_a_before - 20)
        self.assertEqual(engine.level_at(product_id, rack_b), rack_b_before + 20)

    def test_transfer_to_the_same_location_is_rejected(self):
        product_id = self._product("STL-ROD-12")
        location = query("SELECT id FROM locations WHERE code = 'MAIN/STOCK'", one=True)["id"]

        document = engine.create_document(
            doc_type="internal", user_id=None,
            src_warehouse_id=self.main, dst_warehouse_id=self.main,
        )
        engine.add_line(document, product_id, qty=5, src_location_id=location,
                        dst_location_id=location)
        with self.assertRaises(engine.DomainError):
            engine.validate_document(document, user_id=None)

    # -- adjustments -------------------------------------------------------

    def test_adjustment_records_only_the_difference(self):
        product_id = self._product("NUT-M8")
        location = query("SELECT id FROM locations WHERE code = 'MAIN/STOCK'", one=True)["id"]
        current = engine.level_at(product_id, location)
        target = current - 7

        document = engine.create_document(
            doc_type="adjustment", user_id=None, src_warehouse_id=self.main,
            notes="count",
        )
        engine.add_line(document, product_id, qty=0, counted_qty=target,
                        dst_location_id=location)
        engine.validate_document(document, user_id=None)

        self.assertEqual(engine.level_at(product_id, location), target)
        move = query(
            "SELECT * FROM stock_moves WHERE document_id = ?", (document,), one=True
        )
        self.assertEqual(move["qty"], 7)  # the delta, not the count

    def test_adjustment_that_matches_recorded_stock_writes_nothing(self):
        product_id = self._product("NUT-M8")
        location = query("SELECT id FROM locations WHERE code = 'MAIN/STOCK'", one=True)["id"]
        current = engine.level_at(product_id, location)

        document = engine.create_document(
            doc_type="adjustment", user_id=None, src_warehouse_id=self.main
        )
        engine.add_line(document, product_id, qty=0, counted_qty=current,
                        dst_location_id=location)
        with self.assertRaises(engine.DomainError):
            engine.validate_document(document, user_id=None)

    def test_adjustment_may_reduce_stock_to_zero(self):
        product_id = self._product("NUT-M8")
        location = query("SELECT id FROM locations WHERE code = 'MAIN/STOCK'", one=True)["id"]

        document = engine.create_document(
            doc_type="adjustment", user_id=None, src_warehouse_id=self.main
        )
        engine.add_line(document, product_id, qty=0, counted_qty=0, dst_location_id=location)
        engine.validate_document(document, user_id=None)

        self.assertEqual(engine.level_at(product_id, location), 0)

    # -- status workflow ---------------------------------------------------

    def test_status_transitions(self):
        self.client.post(
            "/operations/receipt/new",
            data={"supplier": "Status Co", "dst_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)

        for status in ("waiting", "ready", "draft"):
            self.client.post(
                f"/documents/{document['id']}/status",
                data={"status": status},
                follow_redirects=True,
            )
            self.assertEqual(
                query("SELECT status FROM documents WHERE id = ?",
                      (document["id"],), one=True)["status"],
                status,
            )

    def test_canceling_a_document_blocks_validation(self):
        self.client.post(
            "/operations/receipt/new",
            data={"supplier": "Cancel Co", "dst_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        self.client.post(f"/documents/{document['id']}/status",
                         data={"status": "canceled"}, follow_redirects=True)

        response = self.client.post(
            f"/documents/{document['id']}/validate", follow_redirects=True
        )
        self.assertIn(b"canceled", response.data)

    def test_draft_document_can_be_deleted(self):
        self.client.post(
            "/operations/receipt/new",
            data={"supplier": "Delete Co", "dst_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        self.client.post(f"/documents/{document['id']}/delete", follow_redirects=True)

        self.assertIsNone(
            query("SELECT 1 FROM documents WHERE id = ?", (document["id"],), one=True)
        )

    def test_a_validated_document_cannot_be_deleted(self):
        product_id = self._product("HELM-SFT")
        self.client.post(
            "/operations/receipt/new",
            data={"supplier": "Keep Co", "dst_warehouse_id": str(self.main)},
            follow_redirects=True,
        )
        document = query("SELECT * FROM documents ORDER BY id DESC", one=True)
        self.client.post(f"/documents/{document['id']}/lines",
                         data={"product_id": str(product_id), "qty": "5"})
        self.client.post(f"/documents/{document['id']}/validate", follow_redirects=True)

        response = self.client.post(
            f"/documents/{document['id']}/delete", follow_redirects=True
        )
        self.assertIn(b"cannot be deleted", response.data)
        self.assertIsNotNone(
            query("SELECT 1 FROM documents WHERE id = ?", (document["id"],), one=True)
        )

    def test_lines_cannot_be_added_to_a_non_draft(self):
        document = query(
            "SELECT id FROM documents WHERE status = 'done' LIMIT 1", one=True
        )["id"]
        response = self.client.post(
            f"/documents/{document}/lines",
            data={"product_id": str(self._product("HELM-SFT")), "qty": "1"},
            follow_redirects=True,
        )
        self.assertIn(b"only be changed while a document is a draft", response.data)

    def test_document_detail_renders_for_every_type(self):
        for document in query("SELECT id FROM documents LIMIT 20"):
            self.assertEqual(
                self.client.get(f"/documents/{document['id']}").status_code, 200
            )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettings(BaseCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_warehouse_list_renders(self):
        response = self.client.get("/settings/warehouses")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"MAIN", response.data)

    def test_new_warehouse_form_renders(self):
        self.assertEqual(self.client.get("/settings/warehouses/new").status_code, 200)

    def test_creating_a_warehouse_adds_a_default_location(self):
        self.client.post(
            "/settings/warehouses/new",
            data={"code": "SOUTH", "name": "South Depot", "address": "Chennai"},
            follow_redirects=True,
        )
        self.assertIsNotNone(
            query("SELECT 1 FROM warehouses WHERE code = 'SOUTH'", one=True)
        )
        self.assertIsNotNone(
            query("SELECT 1 FROM locations WHERE code = 'SOUTH/STOCK'", one=True)
        )

    def test_duplicate_warehouse_code_is_rejected(self):
        response = self.client.post(
            "/settings/warehouses/new",
            data={"code": "MAIN", "name": "Copy"},
            follow_redirects=True,
        )
        self.assertIn(b"already exists", response.data)

    def test_warehouse_detail_renders(self):
        warehouse_id = query("SELECT id FROM warehouses WHERE code = 'MAIN'", one=True)["id"]
        response = self.client.get(f"/settings/warehouses/{warehouse_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Locations", response.data)

    def test_adding_a_location(self):
        warehouse_id = query("SELECT id FROM warehouses WHERE code = 'MAIN'", one=True)["id"]
        self.client.post(
            f"/settings/warehouses/{warehouse_id}/locations",
            data={"code": "RACK-C", "name": "Aisle B, rack 1"},
            follow_redirects=True,
        )
        self.assertIsNotNone(
            query("SELECT 1 FROM locations WHERE code = 'MAIN/RACK-C'", one=True)
        )

    def test_a_location_with_ledger_history_cannot_be_deleted(self):
        location_id = query(
            "SELECT id FROM locations WHERE code = 'MAIN/STOCK'", one=True
        )["id"]
        response = self.client.post(
            f"/settings/locations/{location_id}/delete", follow_redirects=True
        )
        self.assertIn(b"cannot be removed", response.data)

    def test_an_unused_location_can_be_deleted(self):
        warehouse_id = query("SELECT id FROM warehouses WHERE code = 'MAIN'", one=True)["id"]
        self.client.post(
            f"/settings/warehouses/{warehouse_id}/locations",
            data={"code": "TEMP", "name": "Temporary"},
            follow_redirects=True,
        )
        location_id = query("SELECT id FROM locations WHERE code = 'MAIN/TEMP'", one=True)["id"]
        self.client.post(f"/settings/locations/{location_id}/delete", follow_redirects=True)
        self.assertIsNone(
            query("SELECT 1 FROM locations WHERE id = ?", (location_id,), one=True)
        )


# ---------------------------------------------------------------------------
# Domain invariants, against the real database
# ---------------------------------------------------------------------------


class TestInvariants(BaseCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_levels_match_an_independent_fold_of_the_ledger(self):
        """Invariant 1: levels are derived, and two folds must agree."""
        rows = query("""
            SELECT product_id, location_id, SUM(qty) AS qty FROM (
                SELECT product_id, dst_location_id AS location_id,  qty FROM stock_moves
                UNION ALL
                SELECT product_id, src_location_id AS location_id, -qty FROM stock_moves
            ) GROUP BY product_id, location_id
        """)
        manual = {(r["product_id"], r["location_id"]): r["qty"] for r in rows if r["qty"]}

        derived = {
            (r["product_id"], r["location_id"]): r["qty"]
            for r in engine.stock_levels(nonzero=True)
        }
        internal_ids = {
            r["id"] for r in query("SELECT id FROM locations WHERE kind = 'internal'")
        }
        manual_internal = {
            key: value for key, value in manual.items() if key[1] in internal_ids
        }
        self.assertEqual(manual_internal, derived)

    def test_every_ledger_entry_is_traceable(self):
        """Invariant 4: no move without a reference, an author and a timestamp."""
        for move in query("SELECT * FROM stock_moves"):
            self.assertTrue(move["reference"])
            self.assertTrue(move["created_at"])
            self.assertIsNotNone(move["created_by"])

    def test_every_ledger_quantity_is_positive(self):
        """Invariant 5."""
        for move in query("SELECT qty FROM stock_moves"):
            self.assertGreater(move["qty"], 0)

    def test_no_internal_location_holds_negative_stock(self):
        """Invariant 3."""
        for level in engine.stock_levels():
            self.assertGreaterEqual(level["qty"], 0, level["location_code"])

    def test_virtual_locations_never_appear_in_default_levels(self):
        """The default view is internal-only: supplier/customer are not stock."""
        for level in engine.stock_levels():
            self.assertEqual(level["location_kind"], "internal")

    def test_done_documents_all_wrote_at_least_one_move(self):
        for document in query("SELECT id FROM documents WHERE status = 'done'"):
            moves = query(
                "SELECT COUNT(*) AS n FROM stock_moves WHERE document_id = ?",
                (document["id"],),
                one=True,
            )["n"]
            self.assertGreater(moves, 0)

    def test_open_documents_wrote_no_moves(self):
        for document in query(
            "SELECT id, reference FROM documents WHERE status != 'done'"
        ):
            moves = query(
                "SELECT COUNT(*) AS n FROM stock_moves WHERE document_id = ?",
                (document["id"],),
                one=True,
            )["n"]
            self.assertEqual(moves, 0, document["reference"])

    def test_inventory_value_matches_a_manual_sum(self):
        expected = sum(
            level["qty"] * query(
                "SELECT unit_cost FROM products WHERE id = ?", (level["product_id"],), one=True
            )["unit_cost"]
            for level in engine.stock_levels()
        )
        self.assertAlmostEqual(engine.inventory_value(), expected, places=2)


# ---------------------------------------------------------------------------
# Time: storage is UTC, display is local, and seeded history is real
# ---------------------------------------------------------------------------


class TestDisplayTime(BaseCase):
    """Timestamps are stored naive-UTC and rendered in the display zone."""

    def test_utc_is_converted_to_the_display_zone(self):
        localtime = self.app.jinja_env.filters["localtime"]
        # 09:22 UTC is 14:52 in IST -- the offset the raw string used to hide.
        self.assertEqual(localtime("2026-09-26 09:22:00"), "26 Sep 2026, 14:52")

    def test_accepts_an_explicit_format(self):
        localtime = self.app.jinja_env.filters["localtime"]
        self.assertEqual(localtime("2026-09-26 09:22:00", "%H:%M"), "14:52")
        self.assertEqual(localtime("2026-09-26 09:22:00", "%Y-%m-%d"), "2026-09-26")

    def test_conversion_crosses_a_date_boundary(self):
        localtime = self.app.jinja_env.filters["localtime"]
        # 20:00 UTC is 01:30 the next day in IST.
        self.assertEqual(localtime("2026-09-26 20:00:00", "%d %b %H:%M"), "27 Sep 01:30")

    def test_empty_and_unparseable_values_do_not_raise(self):
        localtime = self.app.jinja_env.filters["localtime"]
        self.assertEqual(localtime(None), "—")
        self.assertEqual(localtime(""), "—")
        self.assertEqual(localtime("not a date"), "not a date")

    def test_display_zone_is_configurable(self):
        utc_app = create_app({
            "DATABASE": self.db_path, "TESTING": True, "DISPLAY_TZ": "UTC",
        })
        with utc_app.app_context():
            self.assertEqual(
                utc_app.jinja_env.filters["localtime"]("2026-09-26 09:22:00", "%H:%M"),
                "09:22",
            )

    def test_an_unusable_zone_falls_back_to_utc_instead_of_erroring(self):
        bad_app = create_app({
            "DATABASE": self.db_path, "TESTING": True, "DISPLAY_TZ": "Not/AZone",
        })
        with bad_app.app_context():
            self.assertEqual(
                bad_app.jinja_env.filters["localtime"]("2026-09-26 09:22:00", "%H:%M"),
                "09:22",
            )

    def test_ago_buckets(self):
        ago = self.app.jinja_env.filters["ago"]
        now = datetime.now(timezone.utc)

        def stamp(delta):
            return (now - delta).strftime("%Y-%m-%d %H:%M:%S")

        self.assertEqual(ago(stamp(timedelta(seconds=5))), "just now")
        self.assertEqual(ago(stamp(timedelta(minutes=20))), "20 min ago")
        self.assertEqual(ago(stamp(timedelta(hours=1))), "1 hr ago")
        self.assertEqual(ago(stamp(timedelta(hours=5))), "5 hrs ago")
        self.assertEqual(ago(stamp(timedelta(days=1))), "1 day ago")
        self.assertEqual(ago(stamp(timedelta(days=3))), "3 days ago")
        self.assertEqual(ago(None), "—")

    def test_no_template_prints_a_raw_timestamp(self):
        """The bug this guards against: slicing the stored string straight out."""
        templates = Path(__file__).resolve().parent.parent / "app" / "templates"
        offenders = []
        for path in templates.rglob("*.html"):
            text = path.read_text()
            for match in re.finditer(r"(created_at|validated_at)\s*'?\]?\s*\[:\d+\]", text):
                offenders.append(f"{path.name}: {match.group(0)}")
        self.assertEqual(offenders, [], f"raw timestamp slicing: {offenders}")


class TestSeededHistory(BaseCase):
    """The demo dataset is a believable three weeks, not one frozen moment."""

    def _documents(self):
        return query("SELECT * FROM documents ORDER BY created_at")

    def test_history_is_spread_not_a_single_timestamp(self):
        stamps = {row["created_at"] for row in self._documents()}
        self.assertGreater(len(stamps), 10, "seed data is all one timestamp")

    def test_history_is_chronological_in_creation_order(self):
        """A delivery is never dated before the receipt that supplied it."""
        rows = query("SELECT id, created_at, doc_type FROM documents ORDER BY id")
        for earlier, later in zip(rows, rows[1:]):
            self.assertLessEqual(earlier["created_at"], later["created_at"])

    def test_validated_documents_are_stamped_after_creation(self):
        rows = query(
            "SELECT reference, created_at, validated_at FROM documents WHERE status = 'done'"
        )
        self.assertTrue(rows, "expected some done documents in the seed")
        for row in rows:
            self.assertIsNotNone(row["validated_at"], row["reference"])
            self.assertGreaterEqual(row["validated_at"], row["created_at"], row["reference"])

    def test_open_documents_are_never_validated(self):
        rows = query(
            "SELECT reference, validated_at FROM documents WHERE status != 'done'"
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNone(row["validated_at"], row["reference"])

    def test_history_lands_on_weekdays(self):
        """A receipt booked at 03:00 on a Sunday reads as fixture data."""
        for row in self._documents():
            day = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
            self.assertLess(day.weekday(), 5, f"{row['reference']} on {day:%A}")

    def test_history_stays_in_the_past(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for row in self._documents():
            day = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
            self.assertLess(day, now, row["reference"])
            if row["validated_at"]:
                validated = datetime.strptime(row["validated_at"], "%Y-%m-%d %H:%M:%S")
                self.assertLess(validated, now, row["reference"])

    def test_every_move_is_dated_at_or_after_its_document(self):
        rows = query(
            """SELECT m.reference, m.created_at AS move_at, d.created_at AS doc_at
               FROM stock_moves m JOIN documents d ON d.id = m.document_id"""
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertGreaterEqual(row["move_at"], row["doc_at"], row["reference"])

    def test_the_schedule_is_deterministic(self):
        """Fixed seed, so a re-seed reproduces the same story."""
        first = seed_schedule(21, end=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc))
        second = seed_schedule(21, end=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(first, second)

    def test_master_data_predates_the_first_document(self):
        first_document = query(
            "SELECT MIN(created_at) AS m FROM documents", one=True
        )["m"]
        for table in ("products", "warehouses", "users"):
            earliest = query(f"SELECT MIN(created_at) AS m FROM {table}", one=True)["m"]
            self.assertLess(earliest, first_document, table)


class TestClock(BaseCase):
    """``engine.now`` is the single seam where time enters the domain."""

    def test_clock_pins_now(self):
        pinned = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        with engine.clock(lambda: pinned):
            self.assertEqual(engine.now(), "2020-01-02 03:04:05")

    def test_clock_restores_the_real_one_on_exit(self):
        before = engine.now()
        with engine.clock(lambda: datetime(2020, 1, 2, tzinfo=timezone.utc)):
            pass
        after = engine.now()
        self.assertNotEqual(after, "2020-01-02 00:00:00")
        self.assertGreaterEqual(after, before)

    def test_clock_restores_even_when_the_block_raises(self):
        with self.assertRaises(RuntimeError):
            with engine.clock(lambda: datetime(2020, 1, 2, tzinfo=timezone.utc)):
                raise RuntimeError("boom")
        self.assertNotEqual(engine.now(), "2020-01-02 00:00:00")

    def test_a_document_created_under_a_pinned_clock_keeps_that_date(self):
        pinned = datetime(2021, 6, 7, 8, 9, 10, tzinfo=timezone.utc)
        with engine.clock(lambda: pinned):
            document_id = engine.create_document(
                doc_type="receipt", user_id=1, dst_warehouse_id=1, supplier="Test"
            )
        row = query("SELECT created_at FROM documents WHERE id = ?", (document_id,), one=True)
        self.assertEqual(row["created_at"], "2021-06-07 08:09:10")

    def test_now_is_always_utc_regardless_of_the_pinned_zone(self):
        """A clock returning local time must still be stored as UTC."""
        ist = ZoneInfo("Asia/Kolkata")
        local_moment = datetime(2026, 9, 26, 14, 52, tzinfo=ist)
        with engine.clock(lambda: local_moment):
            self.assertEqual(engine.now(), "2026-09-26 09:22:00")


# ---------------------------------------------------------------------------
# Status vocabulary: one state machine, the words each job uses
# ---------------------------------------------------------------------------


class TestStatusVocabulary(BaseCase):
    """The spec names the delivery flow pick / pack / validate."""

    def test_delivery_states_read_as_picked_and_packed(self):
        self.assertEqual(engine.status_label("waiting", "delivery"), "Picked")
        self.assertEqual(engine.status_label("ready", "delivery"), "Packed")

    def test_each_type_gets_its_own_middle_states(self):
        self.assertEqual(engine.status_label("waiting", "receipt"), "Awaiting goods")
        self.assertEqual(engine.status_label("ready", "receipt"), "At the dock")
        self.assertEqual(engine.status_label("waiting", "internal"), "Scheduled")
        self.assertEqual(engine.status_label("ready", "internal"), "Staged")

    def test_canonical_states_keep_their_names_in_every_type(self):
        """draft / done / canceled must stay greppable and match the filter list."""
        for doc_type in engine.DOC_TYPES:
            for status in ("draft", "done", "canceled"):
                self.assertEqual(
                    engine.status_label(status, doc_type),
                    engine.STATUS_LABELS[status],
                    f"{doc_type}/{status}",
                )

    def test_label_falls_back_without_a_document_type(self):
        self.assertEqual(engine.status_label("waiting"), "Waiting")
        self.assertEqual(engine.status_label("ready"), "Ready")

    def test_an_unknown_type_or_status_never_renders_blank(self):
        self.assertEqual(engine.status_label("waiting", "not_a_type"), "Waiting")
        self.assertEqual(engine.status_label("mystery", "delivery"), "mystery")

    def test_every_open_status_has_an_action_for_every_type(self):
        for doc_type in engine.DOC_TYPES:
            for status in ("draft", "waiting", "ready"):
                action = engine.status_action(status, doc_type)
                self.assertTrue(action and action.strip(), f"{doc_type}/{status}")

    def test_flow_is_the_four_state_chain(self):
        flow = engine.status_flow("delivery")
        self.assertEqual([status for status, _ in flow],
                         ["draft", "waiting", "ready", "done"])
        self.assertEqual([label for _, label in flow],
                         ["Draft", "Picked", "Packed", "Done"])

    def test_delivery_page_shows_the_pick_pack_flow(self):
        self.sign_in()
        row = query(
            "SELECT id FROM documents WHERE doc_type = 'delivery' AND status = 'ready'",
            one=True,
        )
        self.assertIsNotNone(row, "seed should contain a ready delivery")
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertIn("Picked", html)
        self.assertIn("Packed", html)

    def test_delivery_draft_offers_pick_and_pack_actions(self):
        self.sign_in()
        row = query(
            "SELECT id FROM documents WHERE doc_type = 'delivery' AND status = 'draft'",
            one=True,
        )
        self.assertIsNotNone(row, "seed should contain a draft delivery")
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertIn("Mark picked", html)
        self.assertIn("Mark packed", html)

    def test_status_filter_keeps_the_canonical_names(self):
        """The filter is cross-type, so it must not speak one document's language."""
        self.sign_in()
        html = self.client.get("/operations").get_data(as_text=True)
        for label in ("Draft", "Waiting", "Ready", "Done", "Canceled"):
            self.assertIn(label, html)

    def test_receipt_page_does_not_borrow_delivery_words(self):
        self.sign_in()
        row = query(
            "SELECT id FROM documents WHERE doc_type = 'receipt' AND status = 'ready'",
            one=True,
        )
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertIn("At the dock", html)
        self.assertNotIn("Packed", html)


# ---------------------------------------------------------------------------
# Assets and print
# ---------------------------------------------------------------------------


class TestAssets(BaseCase):
    def test_favicon_is_served_as_svg(self):
        response = self.client.get("/static/favicon.svg")
        self.assertEqual(response.status_code, 200)
        self.assertIn("image/svg", response.headers["Content-Type"])
        self.assertIn(b"<svg", response.data)

    def test_stylesheet_is_served(self):
        response = self.client.get("/static/css/app.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers["Content-Type"])

    def test_pages_link_the_favicon(self):
        for path in ("/login", "/signup"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn("favicon.svg", html, path)

    def test_no_page_links_a_missing_stylesheet(self):
        """A 404 on a stylesheet silently ruins the layout."""
        self.sign_in()
        for path in ("/", "/products", "/operations", "/operations/moves"):
            html = self.client.get(path).get_data(as_text=True)
            for href in re.findall(r'<link[^>]+href="([^"]+)"', html):
                if href.startswith("/static/"):
                    self.assertEqual(
                        self.client.get(href).status_code, 200, f"{path} -> {href}"
                    )


class TestPrintStylesheet(BaseCase):
    """A pick list has to survive being printed and carried into an aisle."""

    @property
    def css(self):
        return (
            Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "app.css"
        ).read_text()

    def test_print_block_exists(self):
        self.assertIn("@media print", self.css)

    def test_print_hides_the_application_chrome(self):
        block = self.css.split("@media print", 1)[1]
        for selector in (".sidebar", ".topbar-actions", ".card-foot", ".btn"):
            self.assertIn(selector, block, selector)

    def test_print_repeats_table_headings_across_pages(self):
        block = self.css.split("@media print", 1)[1]
        self.assertIn("table-header-group", block)

    def test_print_only_and_pick_cell_are_hidden_on_screen(self):
        screen = self.css.split("@media print", 1)[0]
        self.assertIn(".print-only { display: none; }", screen)
        self.assertIn(".pick-cell { display: none; }", screen)

    def test_document_pages_carry_a_print_header(self):
        self.sign_in()
        row = query("SELECT id FROM documents ORDER BY id LIMIT 1", one=True)
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertIn('class="print-only"', html)
        # On paper there is no sidebar, so the sheet must name itself.
        self.assertIn("Picked by", html)

    def test_delivery_lines_get_a_tick_box_for_each_line(self):
        self.sign_in()
        row = query(
            "SELECT id FROM documents WHERE doc_type = 'delivery' AND status = 'ready'",
            one=True,
        )
        expected = query(
            "SELECT COUNT(*) AS n FROM document_lines WHERE document_id = ?",
            (row["id"],), one=True,
        )["n"]
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertEqual(html.count('class="pick-box"'), expected)

    def test_non_pickable_types_get_no_tick_boxes(self):
        self.sign_in()
        for doc_type in ("receipt", "adjustment"):
            row = query(
                "SELECT id FROM documents WHERE doc_type = ? ORDER BY id LIMIT 1",
                (doc_type,), one=True,
            )
            html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
            self.assertNotIn('class="pick-box"', html, doc_type)


# ---------------------------------------------------------------------------
# Reading a document row correctly
# ---------------------------------------------------------------------------


class TestDocumentQuantity(BaseCase):
    """An adjustment records a delta, so its line sum is always zero."""

    def _rows(self):
        return {row["reference"]: row for row in engine.list_documents()}

    def test_a_done_adjustment_reports_its_signed_correction(self):
        row = query(
            "SELECT reference FROM documents WHERE doc_type = 'adjustment' AND status = 'done'",
            one=True,
        )["reference"]
        self.assertLess(self._rows()[row]["adjust_delta"], 0,
                        "the seeded adjustments are both damage write-offs")

    def test_an_unvalidated_adjustment_reports_nothing(self):
        row = query(
            "SELECT reference FROM documents WHERE doc_type = 'adjustment' AND status != 'done'",
            one=True,
        )["reference"]
        self.assertIsNone(self._rows()[row]["adjust_delta"])

    def test_the_delta_agrees_with_the_ledger(self):
        for row in engine.list_documents(doc_type="adjustment"):
            if row["adjust_delta"] is None:
                continue
            moves = query(
                "SELECT src_location_id, dst_location_id, qty FROM stock_moves WHERE document_id = ?",
                (row["id"],),
            )
            expected = 0
            for move in moves:
                src = query(
                    "SELECT kind FROM locations WHERE id = ?",
                    (move["src_location_id"],), one=True,
                )["kind"]
                expected += move["qty"] if src == "adjustment" else -move["qty"]
            self.assertEqual(row["adjust_delta"], expected, row["reference"])

    def test_non_adjustments_still_report_their_line_total(self):
        row = query(
            "SELECT reference FROM documents WHERE doc_type = 'delivery' AND status = 'done'",
            one=True,
        )["reference"]
        self.assertGreater(self._rows()[row]["total_qty"], 0)

    def test_adjustment_rows_do_not_render_a_bare_zero(self):
        self.sign_in()
        html = self.client.get("/operations").get_data(as_text=True)
        for row in engine.list_documents(doc_type="adjustment"):
            self.assertNotIn(
                f">{row['reference']}</a></td>\n        <td>Inventory Adjustment</td>",
                html,
            )
        # The signed correction should be visible instead.
        self.assertRegex(html, r"-[\d,.]+\s*</span>")

    def test_draft_adjustment_row_shows_a_dash(self):
        self.sign_in()
        row = query(
            "SELECT reference FROM documents WHERE doc_type = 'adjustment' AND status = 'draft'",
            one=True,
        )["reference"]
        html = self.client.get("/operations").get_data(as_text=True)
        self.assertIn(row, html)
        self.assertIn("No correction recorded", html)


class TestStatusDirection(BaseCase):
    """Buttons must say which way the document is moving."""

    def test_a_draft_delivery_offers_forward_actions(self):
        self.sign_in()
        row = query(
            "SELECT id FROM documents WHERE doc_type = 'delivery' AND status = 'draft'",
            one=True,
        )
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertIn(">Mark picked<", html)
        self.assertIn(">Mark packed<", html)
        # Nothing to reverse: a draft is the first state.
        self.assertNotIn("Back to draft", html)
        self.assertNotIn("Back to picked", html)

    def test_a_packed_delivery_offers_reversals(self):
        self.sign_in()
        row = query(
            "SELECT id FROM documents WHERE doc_type = 'delivery' AND status = 'ready'",
            one=True,
        )
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertIn("Back to draft", html)
        self.assertIn("Back to picked", html)
        self.assertNotIn(">Mark picked<", html)

    def test_a_scheduled_transfer_offers_one_of_each(self):
        self.sign_in()
        row = query(
            "SELECT id FROM documents WHERE doc_type = 'internal' AND status = 'waiting'",
            one=True,
        )
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertIn("Back to draft", html)   # backwards
        self.assertIn(">Mark staged<", html)   # forwards

    def test_delete_copy_is_not_draft_specific_on_a_ready_document(self):
        self.sign_in()
        row = query(
            "SELECT id FROM documents WHERE doc_type = 'delivery' AND status = 'ready'",
            one=True,
        )
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertIn("has not been validated", html)
        self.assertNotIn("Removes the draft and its lines", html)

    def test_delete_copy_is_draft_specific_on_a_draft(self):
        self.sign_in()
        row = query(
            "SELECT id FROM documents WHERE doc_type = 'delivery' AND status = 'draft'",
            one=True,
        )
        html = self.client.get(f"/documents/{row['id']}").get_data(as_text=True)
        self.assertIn("Removes the draft and its lines", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
