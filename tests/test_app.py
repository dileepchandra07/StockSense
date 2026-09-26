"""End-to-end tests for the StockSense application.

Runs against a throwaway SQLite file per test, seeded with the demo dataset.
    python -m unittest discover -s tests -v
"""

import os
import re
import tempfile
import unittest

from app import create_app, engine
from app.db import query
from app.seed import DEMO_EMAIL, DEMO_PASSWORD, seed


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
